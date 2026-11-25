import unittest
from unittest.mock import patch
import main

class PolicyEfficiencyTests(unittest.TestCase):
    def test_ambiguous_offering_results_reach_source_analysis(self):
        for title in ['פז אנרגיה-תוצאות הנפקה', 'השלמת ההנפקה', 'Results of offering', 'Closing of the issuance', "תוצאות הנפקת אג''ח", 'תוצאות הנפקת אג׳׳ח']:
            self.assertFalse(main.excluded_notice(title), title)
        for title in ['תוצאות הנפקת מניות', 'תוצאות גיוס הון', 'Results of equity offering', 'מועד פרסום דוחות']:
            self.assertTrue(main.excluded_notice(title), title)

    def test_bond_results_require_economic_analysis(self):
        for title in ['חברה - תוצאות הנפקת אג״ח', 'הרחבת סדרת אגרות חוב', 'Results of bond offering']:
            self.assertFalse(main.excluded_notice(title), title)
        for title in ['תשלום ריבית אג״ח', 'דירוג אגרות חוב', 'תוצאות גיוס הון', 'מועד פרסום דוחות כספיים']:
            self.assertTrue(main.excluded_notice(title), title)

    def test_mixed_earnings_not_lost(self):
        self.assertFalse(main.excluded_notice('תוצאות כספיות ועדכון דירוג אג״ח'))

    def test_english_paragraph_with_hebrew_token_rejected(self):
        a = dict(title='כותרת', summary='א This is a long English paragraph', importance='חשיבות מהותית לחברה', missing='')
        self.assertFalse(main.hebrew_analysis(a))
        a['summary'] = 'הרווח עלה וצפויה תוספת מהותית לתזרים EBITDA'
        self.assertTrue(main.hebrew_analysis(a))
        a['missing'] = 'Not available'
        self.assertFalse(main.hebrew_analysis(a))

    def test_bounded_history_keeps_recent_priority(self):
        history = {str(i): {'company':'חברה', 'summary':'א'*1000, 'importance':'ב'*5000} for i in range(30)}
        compact = main.compact_previous(history)
        self.assertIn('0', compact)
        self.assertLessEqual(len(compact), 12)
        self.assertLess(sum(len(__import__('json').dumps(x, ensure_ascii=False)) for x in compact.values()), 12001)
        self.assertTrue(all('importance' not in x for x in compact.values()))

    def test_source_documents_unchanged(self):
        s=main.State(':memory:')
        parts=[{'text':'מקור מלא '*20000}]
        with patch.object(main,'route_analysis',return_value={'decision':'not_material'}) as analyze:
            main.analyze_with_backup(s,parts,{},'model','key')
        self.assertIs(analyze.call_args.args[1],parts)
        self.assertEqual(len(parts[0]['text']),len('מקור מלא '*20000))
        s.db.close()

if __name__ == '__main__': unittest.main()
