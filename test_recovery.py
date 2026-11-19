import sys
import unittest
from types import ModuleType
from unittest.mock import MagicMock, patch
import main

class Regression(unittest.TestCase):
    def test_metadata_never_uses_browser_as_dictionary(self):
        api=MagicMock()
        browser=api.sync_playwright.return_value.__enter__.return_value.chromium.launch.return_value
        page=browser.new_context.return_value.new_page.return_value
        page.get_by_role.return_value.count.return_value=1
        page.get_by_role.return_value.get_attribute.return_value="/he/companies/1894"
        page.get_by_role.return_value.inner_text.return_value="title"
        url="https://maya.tase.co.il/he/reports/1780748"
        doc="https://mayafiles.tase.co.il/file.pdf"
        with patch.dict(sys.modules,{"playwright":ModuleType("playwright"),"playwright.sync_api":api}), patch.object(main,"discover_attachments",return_value={doc}), patch.object(main,"linked_results",return_value=None), patch.object(main,"latest_financial_report",return_value=None), patch.object(main,"download",return_value={"text":"text"}):
            meta={}
            self.assertEqual(main.collect_documents(url,meta)[0],[doc])
            self.assertEqual(meta["issuer"],"1894")
            self.assertEqual(main.collect_documents(url)[0],[doc])
    def test_targeted_recovery_only_once(self):
        s=main.State(":memory:")
        for rid,status in [("1781038","unverified"),("1781039","done"),("unrelated","unverified")]:
            s.db.execute("INSERT INTO jobs(id,status,attempts) VALUES (?,?,3)",(rid,status))
        main.recover_document_jobs(s)
        self.assertEqual(s.db.execute("select id from jobs where status='pending'").fetchall(),[("1781038",)])
        s.db.execute("update jobs set attempts=1 where id='1781038'")
        main.recover_document_jobs(s)
        self.assertEqual(s.db.execute("select attempts from jobs where id='1781038'").fetchone(),(1,))
