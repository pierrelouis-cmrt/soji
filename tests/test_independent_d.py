"""Independent review proofs for 16c0699; disposable fixtures only."""
import sys, unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
import test_journal_refusal_safety as journal_fixture
from soji_cli.nativeplans import versions_plan

class IndependentD(unittest.TestCase):
    def fixture(self):
        f=journal_fixture.JournalSafety();f.setUp();self.addCleanup(f.doCleanups);return f
    def test_transient_checkpoint_failure_surfaces_journal_error(self):
        f=self.fixture();plan=f.plan();real=f.cleaner.append;calls=[]
        def append(e):
            if not calls:
                calls.append(1);raise OSError('injected checkpoint ENOSPC')
            real(e)
        with patch.object(f.cleaner,'append',side_effect=append):result=f.cleaner.apply(plan)
        self.assertTrue(f.target.exists());self.assertEqual(result['completed'],0)
        self.assertIn('checkpoint ENOSPC',result['entries'][0]['error'])
        self.assertIsNotNone(result['journalError'],result)
    def test_unavailable_app_inventory_blocks_native_uninstall(self):
        import plistlib
        from soji_cli.uninstall import uninstall_plan
        f=self.fixture();app=f.home/'Applications/Fixture.app'
        (app/'Contents').mkdir(parents=True)
        (app/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'org.fixture.app','CFBundleName':'Fixture'}))
        with patch('soji_cli.apps.code_identity',return_value={'team':None,'groups':[]}),patch('soji_cli.apps.user_receipts',return_value={}):
            plan=uninstall_plan(str(app),str(f.home))
            with patch('soji_cli.apps.native',return_value={'error':'fixture process source unavailable'}):
                result=f.cleaner.apply(plan)
        self.assertEqual(result['completed'],0,result)
        self.assertTrue(app.exists())
    def test_successful_uninstall_has_fresh_audit_policy(self):
        import plistlib
        from soji_cli.uninstall import uninstall_plan
        f=self.fixture();app=f.home/'Applications/Fixture.app'
        (app/'Contents').mkdir(parents=True)
        (app/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'org.fixture.app','CFBundleName':'Fixture'}))
        with patch('soji_cli.apps.code_identity',return_value={'team':None,'groups':[]}),patch('soji_cli.apps.user_receipts',return_value={}):
            result=f.cleaner.apply(uninstall_plan(str(app),str(f.home)))
        self.assertEqual(result['completed'],1,result)
        self.assertEqual(result['entries'][0]['policy']['source'],'fresh',result)
    def test_regular_document_version_remains_usable(self):
        f=self.fixture();doc=f.home/'document.txt';doc.write_text('fixture')
        catalog={'versions':[{'retained':False,'unit':'old','url':'fake-old','modified':123}]}
        with patch('soji_cli.nativeplans.document_versions',return_value=catalog),patch('soji_cli.platform.native',return_value={'removed':True}):
            result=f.cleaner.apply(versions_plan(str(doc),str(f.home)),permanent=True,execute_tools=True)
        self.assertEqual(result['completed'],1,result)
        policy=result['entries'][0]['policy']
        self.assertEqual(policy['source'],'fresh');self.assertEqual(policy['verifier'],'document-version')
        self.assertIsNone(policy['threshold']);self.assertTrue(policy['evidence']['catalogVerified'])
        self.assertEqual(result['entries'][0]['planPolicy']['source'],'plan')

    def test_unavailable_inventory_blocks_plan_creation(self):
        import plistlib
        from soji_cli.uninstall import uninstall_plan
        f=self.fixture();app=f.home/'Applications/Fixture.app';(app/'Contents').mkdir(parents=True)
        (app/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'org.fixture.app','CFBundleName':'Fixture'}))
        with patch('soji_cli.apps.native',return_value={'error':'unavailable'}):
            with self.assertRaisesRegex(ValueError,'inventory unavailable'):uninstall_plan(str(app),str(f.home))

if __name__=='__main__':unittest.main()
