"""Public boundary regressions using disposable state and explicit observations."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from soji_cli.engine import Scanner
from soji_cli.index import IndexedScanner
from soji_cli.cleanup import Cleaner
from soji_cli.routine_policy import normalize_routine
from soji_cli.plans import build_plan,resource_identity
from soji_cli.scancontrol import ScanController
from soji_cli import walker,update

class AuditBoundaries(unittest.TestCase):
    def test_processes_command_calls_registered_tool(self):
        from soji_cli.__main__ import main
        with patch('sys.argv',['soji','processes','memory']),patch('soji_cli.mcp.MCPServer.call',return_value=[]) as call,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(),0)
        call.assert_called_once_with('top_processes',{'sort':'memory'})

    def test_policy_only_catalog_change_reuses_measurement_signature(self):
        scan=IndexedScanner(['/fixture'],home='/fixture',context=False)
        before=scan.signature()
        scan.catalog.hints=[dict(h,label='renamed',rule={'minIdleDays':999}) for h in scan.catalog.hints]
        self.assertEqual(scan.signature(),before)
        scan.protected=['/fixture/private']
        self.assertNotEqual(scan.signature(),before)

    def test_install_capabilities_do_not_depend_on_group_labels(self):
        from soji_cli.installs import capable,ATOMIC
        self.assertTrue(capable({'id':'fixture','group':'renamed category','capabilities':[ATOMIC]},ATOMIC))
        self.assertFalse(capable({'group':'Editor extensions'},ATOMIC))

    def test_document_resources_and_plan_metadata(self):
        items=[{'path':'/doc','action':{'kind':'document-version','document':'/doc','version':v}} for v in ('v1','v2')]
        self.assertNotEqual(resource_identity(items[0]),resource_identity(items[1]))
        plan=build_plan(items=items,roots=['/'],home='/',mode='careful',method='permanent')
        self.assertIn('version',plan)
        from soji_cli.identity import digest
        seal=plan.pop('digest');self.assertEqual(seal,digest(plan))

    def test_nested_and_top_level_routine_decoding(self):
        for row in ({'freeBelowPercent':{'_0':5}},{'conditions':{'freeBelowPercent':5}},{'conditions':{'freeBelow':{'freeBelowPercent':{'_0':5}}}}):
            self.assertEqual(normalize_routine(row)['conditions']['freeBelow']['freeBelowPercent'],{'_0':5})

    def test_programmatic_cleanup_checks_update_eligibility_before_plan(self):
        with tempfile.TemporaryDirectory() as state,patch.object(update,'check',return_value={'status':'outdated','current':'0','latest':'99'}) as check:
            with self.assertRaisesRegex(ValueError,'Cleaning is disabled'):Cleaner(state).apply({})
            check.assert_called_once()
        with tempfile.TemporaryDirectory() as state,patch.object(update,'check',return_value={'status':'unknown'}):
            with self.assertRaisesRegex(ValueError,'Unsupported plan'):Cleaner(state).apply({})

    def test_refresh_preserves_scan_configuration_and_advances_revision(self):
        with tempfile.TemporaryDirectory() as home:
            scan=Scanner([home],home=home,context=False,tick_trash=True,walk_backend='python')
            control=ScanController(scan);control.start().join()
            before=control.revision
            new,thread=control.restart(True);thread.join()
            self.assertGreater(control.revision,before)
            self.assertTrue(new.tick_trash);self.assertEqual(new.walk_backend,'python')
            self.assertTrue(control.can_clean)

    def test_incomplete_tool_discovery_is_distinct_from_no_references(self):
        from soji_cli.apps import InstalledTools
        with tempfile.TemporaryDirectory() as home:
            path=Path(home)/'.claude/settings.json';path.parent.mkdir()
            path.symlink_to('/missing-fixture')
            tools=InstalledTools(home)
            self.assertIsNone(tools.config_json(path))
            self.assertFalse(tools.complete)
            self.assertIsNone(tools.use(home))
            self.assertIn('inspection skipped',tools.errors[0])

    def test_incomplete_tool_discovery_holds_both_cleanup_tiers(self):
        from types import SimpleNamespace as NS
        from soji_cli.models import Finding
        from soji_cli.specialized import SpecializedRules
        rules=SpecializedRules.__new__(SpecializedRules)
        rules.scanner=NS(catalog=NS(hints=[]),now=2_000_000_000,recent_activity_hours=0)
        rules.apps=NS(owner=lambda path:[])
        rules.activity=NS(errors=[],last=lambda path:None)
        rules.tools=NS(errors=[],use=lambda path:None)
        with patch.object(rules,'active_reason',return_value=None):
            for tier in ('regenerable','costly'):
                with self.subTest(tier=tier):
                    def finding():
                        return Finding('/fixture/tool',100,100,1,1,'Toolchains and SDKs','tool',
                                       tier=tier,comes_back='rebuilds',list_only=False)
                    self.assertTrue(rules.evaluate(finding()).decide('aggressive',rules.scanner.now)[0])
                    rules.tools.errors=['Launch agent unreadable']
                    held=rules.evaluate(finding())
                    selected,reason=held.decide('aggressive',rules.scanner.now)
                    self.assertFalse(selected)
                    self.assertIn('Installed tool discovery incomplete',reason)
                    rules.tools.errors=[]

    def test_launch_agent_inspection_failures_make_tool_inventory_incomplete(self):
        import plistlib
        from soji_cli.apps import InstalledTools
        with tempfile.TemporaryDirectory() as home:
            root=Path(home)/'Library/LaunchAgents';root.mkdir(parents=True)
            agent=root/'fixture.plist'
            def build():
                with patch.dict('os.environ',{'PATH':''}),patch.object(InstalledTools,'SYSTEM_AGENT_ROOTS',()):
                    return InstalledTools(home).build()
            agent.write_bytes(plistlib.dumps({'Program':'/fixture/tool'}))
            self.assertTrue(build().complete)
            self.assertIsNotNone(build().use('/fixture'))
            for kind in ('unreadable','symlink','malformed','truncated-xml','oversized'):
                with self.subTest(kind=kind):
                    if agent.is_symlink():agent.unlink()
                    agent.write_bytes(plistlib.dumps({'Program':'/fixture/tool'}))
                    if kind=='symlink':
                        agent.unlink();agent.symlink_to('/missing-fixture')
                    elif kind=='malformed':agent.write_text('invalid plist')
                    elif kind=='truncated-xml':agent.write_text('<?xml version="1.0"?><plist><dict>')
                    elif kind=='oversized':agent.write_bytes(b' '*8_000_001)
                    with patch.object(Path,'open',side_effect=PermissionError('fixture denied')) if kind=='unreadable' else contextlib.nullcontext():
                        tools=build()
                    self.assertFalse(tools.complete)
                    self.assertTrue(any('Launch agent inspection incomplete' in error for error in tools.errors))
                    self.assertIsNone(tools.use('/fixture'))

    def test_bad_native_contract_does_not_accept_partial_state(self):
        scan=Scanner(['/fixture'],home='/fixture',context=False)
        with self.assertRaises(ValueError):walker.decode(scan,b'{"protocol":999,"count":0}\n')
        self.assertEqual(scan.nodes,{})
        self.assertEqual(scan.visited,0)
