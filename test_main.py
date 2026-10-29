import email
from email import policy
import tempfile
import unittest
from unittest.mock import patch, Mock
import main

class MonitorTests(unittest.TestCase):
    def test_original_link_and_exact_host(self):
        msg = email.message_from_string('Content-Type: text/html; charset=utf-8\n\n<a href="https://tracking.invalid/x" data-mce-href="https://maya.tase.co.il/reports/details/1778748">report</a>', policy=policy.default)
        self.assertEqual(main.email_links(msg), ['https://maya.tase.co.il/reports/details/1778748'])
        self.assertIsNone(main.report_id('https://maya.tase.co.il.evil.test/reports/1778748'))
        self.assertFalse(main.document_url('https://mayafiles.tase.co.il.evil.test/a.pdf'))

    def test_sender_authentication(self):
        msg = email.message_from_string('From: Maya <maya@mailtase.co.il>\nAuthentication-Results: mx.google.com; dmarc=pass header.from=mailtase.co.il\n\n', policy=policy.default)
        self.assertTrue(main.authenticated(msg))
        msg.replace_header('From', 'maya@evil.test')
        self.assertFalse(main.authenticated(msg))

    def test_state_survives_restart(self):
        with tempfile.TemporaryDirectory() as d:
            s = main.State(d+'/state.db'); s.set('cursor',42); s.db.close()
            s = main.State(d+'/state.db'); self.assertEqual(s.get('cursor'),'42'); s.db.close()

    def test_failed_analysis_remains_pending(self):
        s = main.State(':memory:')
        s.db.execute("INSERT INTO jobs(id,subject,date,url) VALUES ('1','test','today','url')"); s.db.commit()
        with patch.object(main,'collect_documents',side_effect=main.Retryable('unavailable')):
            main.process(s,'model','key')
        self.assertEqual(s.db.execute('SELECT status,attempts FROM jobs').fetchone(), ('pending',1))
        self.assertEqual(s.db.execute('SELECT COUNT(*) FROM sent').fetchone()[0],0)

    def test_failed_delivery_is_retained(self):
        s = main.State(':memory:'); s.db.execute("INSERT INTO outbox(id,text) VALUES ('1','a < b & c')"); s.db.commit()
        with patch.object(main.requests,'post',return_value=Mock(status_code=400)):
            main.deliver(s,'secret','123')
        self.assertEqual(s.db.execute('SELECT status FROM outbox').fetchone()[0],'pending')
        r=Mock(status_code=200); r.json.return_value={'ok':True}
        with patch.object(main.requests,'post',return_value=r) as send:
            main.deliver(s,'secret','123')
            self.assertNotIn('parse_mode',send.call_args.kwargs['json'])
        self.assertEqual(s.db.execute('SELECT status FROM outbox').fetchone()[0],'sent')

    def test_malformed_classification_not_treated_as_nonmaterial(self):
        with self.assertRaises(ValueError): main.validate_analysis({'decision':'not_material'}, {})
        a={k:'' for k in main.FIELDS}; a.update(decision='duplicate',duplicate_of='invented')
        with self.assertRaises(ValueError): main.validate_analysis(a,{})

    def test_two_mails_same_report_only_one_job(self):
        s = main.State(':memory:')
        for _ in range(2): s.db.execute("INSERT OR IGNORE INTO jobs(id) VALUES ('1778748')")
        self.assertEqual(s.db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],1)

if __name__=='__main__': unittest.main()
