import json
import os
import unittest
from unittest.mock import Mock, patch
import main


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.state = main.State(':memory:')
        # Hard stop: tests must never contact Gmail, AI, Render or Telegram.
        self.network = patch('requests.sessions.Session.request', side_effect=AssertionError('network forbidden'))
        self.network.start()
        self.env = patch.dict(os.environ, {'GROQ_API_KEY':'', 'OPENROUTER_API_KEY':'', 'OPENAI_API_KEY':''})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.network.stop()
        self.state.db.close()

    def test_all_companies_officer_updates(self):
        self.assertTrue(main.excluded_notice('דלתא-שינוי החזקות נושאי משרה'))
        for title in ['בזק-שינוי אחזקות נושאי משרה', 'מינוי נושא משרה', 'סיום כהונת מנכ״ל', 'Appointment of CEO', 'Director remuneration']:
            self.assertTrue(main.excluded_notice(title), title)
        for s in ['דלתא גליל - החזקות בעלי עניין ונושאי משרה', 'דלתא-דוח רבעוני ועדכון אחזקות נושאי משרה',
                  'דלתא-שינוי החזקות נושאי משרה; הפכה לבעלת עניין-הראל', 'דלתא-עסקה מהותית']:
            self.assertFalse(main.excluded_notice(s), s)

    def test_priority_and_deferred_job_does_not_block_next(self):
        for rid, subject in [('1','חברה-חדלה להיות בעלת עניין-הראל'), ('2','חברה-מיזוג'), ('3','חברה-דוח רבעון 3')]:
            self.state.db.execute('INSERT INTO jobs(id,subject) VALUES (?,?)',(rid,subject))
        self.state.db.commit()
        with patch.object(main,'evaluate',side_effect=main.WorkDeferred(60)) as evaluate:
            main.process(self.state,'model','key')
            self.assertEqual(evaluate.call_args.args[1],'3')
            main.process(self.state,'model','key')
            self.assertEqual(evaluate.call_args.args[1],'2')
        self.assertEqual(self.state.db.execute('SELECT sum(attempts) FROM jobs').fetchone()[0],0)

    def test_archives_old_pending_and_outbox_not_sent(self):
        self.state.db.execute("INSERT INTO jobs(id,date) VALUES ('1','Thu, 19 Nov 2026 12:00:00 +0200')")
        self.state.db.execute("INSERT INTO outbox(id,text) VALUES ('1','old')")
        self.state.db.execute("INSERT INTO jobs(id,date) VALUES ('2','Wed, 25 Nov 2026 13:00:00 +0200')")
        main.skip_old_reports(self.state)
        self.assertEqual(self.state.db.execute("SELECT status FROM jobs WHERE id='1'").fetchone()[0],'skipped_cutoff')
        self.assertEqual(self.state.db.execute("SELECT status FROM outbox").fetchone()[0],'skipped_cutoff')
        self.assertEqual(self.state.db.execute("SELECT status FROM jobs WHERE id='2'").fetchone()[0],'pending')

    def test_one_provider_attempt_then_next_route(self):
        with patch.dict(os.environ, {'GROQ_API_KEY':'fake'}), patch.object(main,'analyze',side_effect=main.AnalysisRateLimit('120')) as primary, patch.object(main,'chunked_groq',return_value={'decision':'not_material'}) as groq:
            with self.assertRaises(main.WorkDeferred):
                main.route_analysis(self.state,[{'text':'test'}],{},'model','fake')
            groq.assert_not_called()
            result=main.route_analysis(self.state,[{'text':'test'}],{},'model','fake')
            self.assertEqual(result['decision'],'not_material')
            self.assertEqual(primary.call_count,1)

    def test_validation_failure_not_reported_as_http_503(self):
        with patch.dict(os.environ, {'GROQ_API_KEY':'fake'}), patch.object(main,'chunked_groq',side_effect=ValueError('sensitive input must not be logged')):
            with self.assertLogs(main.LOG, level='WARNING') as logs:
                with self.assertRaises(main.WorkDeferred):
                    main.route_analysis(self.state,[{'text':'test'}],{},'model','')
        message=' '.join(logs.output)
        self.assertIn('category=validation_or_extraction',message)
        self.assertIn('HTTP=none',message)
        self.assertIn('delay=3600s',message)
        self.assertNotIn('sensitive input',message)

    def test_exhausted_credit_long_cooldown(self):
        self.state.set('gemini_resume', main.time.time()+1000)
        response=Mock(status_code=429, headers={})
        response.json.return_value={'error':{'code':'credit_balance_exhausted'}}
        error=main.requests.HTTPError(response=response)
        with patch.dict(os.environ,{'OPENAI_API_KEY':'fake'}),patch.object(main,'analyze_backup',side_effect=error) as backup:
            with self.assertRaises(main.WorkDeferred): main.route_analysis(self.state,[],{},'model','fake')
            self.assertGreater(float(self.state.get('openai_resume')),main.time.time()+21000)
            with self.assertRaises(main.WorkDeferred): main.route_analysis(self.state,[],{},'model','fake')
            self.assertEqual(backup.call_count,1)

    def test_413_shrinks_payload_not_global_block(self):
        self.state.set('gemini_resume',main.time.time()+1000)
        response=Mock(status_code=413,headers={})
        response.json.return_value={}
        with patch.dict(os.environ,{'GROQ_API_KEY':'fake'}),patch.object(main,'chunked_groq',side_effect=main.requests.HTTPError(response=response)):
            with self.assertRaises(main.WorkDeferred): main.route_analysis(self.state,[{'text':'x'}],{},'model','fake')
        self.assertEqual(self.state.get('groq_budget:'+main.digest([{'text':'x'}])),'2000')
        self.assertIsNone(self.state.get('groq_resume'))

    def test_chunk_resume_and_tail_coverage(self):
        parts=[{'text':'מקור: https://mayafiles.tase.co.il/example.htm'}, {'text':'א'*8500+'הערת סוף חשובה'}]
        response=Mock(status_code=200)
        response.json.return_value={'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'readable':True,'notes':'סיכום נתונים ותנאים מן המקור'})}}]}
        with patch.object(main.requests,'post',return_value=response) as send:
            for _ in range(4):
                with self.assertRaises(main.WorkDeferred): main.chunked_groq(self.state,parts,{},'fake')
            sent=[call.kwargs['json']['messages'][1]['content'] for call in send.call_args_list]
            self.assertEqual(len(sent),len(set(sent)))
            self.assertTrue(any('הערת סוף חשובה' in s for s in sent))

    def test_source_cache_survives_provider_deferral(self):
        self.state.db.execute("INSERT INTO jobs(id,url) VALUES ('123','url')")
        with patch.object(main,'collect_documents',return_value=(['source'],[{'text':'full text'}])) as docs, patch.object(main,'analyze_with_backup',side_effect=main.WorkDeferred()):
            for _ in range(2):
                with self.assertRaises(main.WorkDeferred): main.evaluate(self.state,'123','url','model','fake')
            self.assertEqual(docs.call_count,1)

    def test_chunk_pipeline_completes_after_all_chunks(self):
        parts=[{'text':'מקור: https://mayafiles.tase.co.il/example.htm'}, {'text':'תוכן מלא '*1200+'הערת סוף'}]
        answer=dict.fromkeys(main.FIELDS,'')
        answer['decision']='not_material'
        calls=[]
        def reply(*args,**kwargs):
            calls.append(kwargs['json'])
            extraction=kwargs['json']['messages'][0]['content']==main.CHUNK_PROMPT
            value={'readable':True,'notes':'הערת סוף: נתונים מתוך המקטע'} if extraction else answer
            response=Mock(status_code=200)
            response.json.return_value={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(value)}}]}
            return response
        with patch.object(main.requests,'post',side_effect=reply):
            for _ in range(20):
                try:
                    result=main.chunked_groq(self.state,parts,{},'fake')
                    break
                except main.WorkDeferred:
                    pass
            else:
                self.fail('pipeline never finished')
        self.assertEqual(result['decision'],'not_material')
        self.assertIn('all_chunks',calls[-1]['messages'][1]['content'])
        self.assertGreater(len(calls),2)

    def test_scanned_page_does_not_become_nonmaterial(self):
        page=Mock()
        page.extract_text.return_value=''
        with patch('pypdf.PdfReader',return_value=Mock(pages=[page])):
            with self.assertRaises(ValueError):
                main.text_documents([{'inlineData':{'data':'JVBERi0=', 'mimeType':'application/pdf'}}])

    def test_queued_delta_alert_suppressed_without_send(self):
        self.state.db.execute("INSERT INTO jobs(id,subject) VALUES ('1','דלתא-שינוי החזקות נושאי משרה')")
        self.state.db.execute("INSERT INTO outbox(id,text) VALUES ('1','queued')")
        main.deliver(self.state,'fake','fake')
        self.assertEqual(self.state.db.execute('SELECT status FROM outbox').fetchone()[0],'suppressed_preference')


if __name__ == '__main__':
    unittest.main()
