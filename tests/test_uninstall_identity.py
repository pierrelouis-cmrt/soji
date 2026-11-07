"""Signing-identity uninstall attribution with fake codesign output and temp homes.
Nothing real is uninstalled: AppCatalog.build is pinned and codesign is mocked."""
import plistlib
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from soji_cli import apps as appmod
from soji_cli.apps import AppCatalog,code_identity,apple_group
from soji_cli.cleanup import validate_plan
from soji_cli.uninstall import uninstall_plan,verify_uninstall

TEAM='ABCDE12345'
REAL_USER_RECEIPTS=appmod.user_receipts


def fake_codesign(table):
    """table: app path -> (team or None, [groups]) ; missing path = unsigned."""
    def command(argv,timeout=8,env=None):
        if argv[0]==appmod.PKGUTIL:return 0,'vendor\nvendor/lib.dylib\n../escape\n',''
        path=argv[-1]
        if path not in table:return 1,'',path+': code object is not signed at all'
        team,groups=table[path]
        if '-dv' in argv:
            return 0,'','Executable='+path+'\nTeamIdentifier='+(team or 'not set')+'\n'
        ent={'com.apple.security.application-groups':groups} if groups else {}
        return 0,plistlib.dumps(ent).decode(),''
    return command


class UninstallIdentityTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(prefix='soji-uninstall-');self.addCleanup(tmp.cleanup)
        self.home=Path(tmp.name).resolve();self.apps=[];self.signing={}
        self.pkgs={}
        def build(cat):cat.apps=[dict(a) for a in self.apps];cat.running=[];return cat
        patches=[patch.object(AppCatalog,'build',build),
                 patch.object(appmod,'command',side_effect=lambda *a,**k:fake_codesign(self.signing)(*a,**k)),
                 patch.object(appmod,'user_receipts',side_effect=lambda home:self.pkgs)]
        for p in patches:p.start();self.addCleanup(p.stop)
    def app(self,name,bundle,team=None,groups=(),signed=True):
        p=self.home/'Applications'/(name+'.app');(p/'Contents').mkdir(parents=True)
        a={'path':str(p),'bundle':bundle,'name':name,'version':'1'};self.apps.append(a)
        if signed:self.signing[str(p)]=(team,list(groups))
        return a
    def container(self,name):
        p=self.home/'Library/Group Containers'/name;p.mkdir(parents=True);(p/'data').write_text('x');return str(p)
    def paths(self,plan):return {i['path'] for i in plan['items']}
    def shared(self,plan):return {s['path']:s for s in plan['shared']}

    def test_parse_real_shaped_codesign_output(self):
        self.signing['/A.app']=(TEAM,[TEAM+'.co.example.shared','group.co.example'])
        self.assertEqual(code_identity('/A.app'),{'team':TEAM,'groups':sorted([TEAM+'.co.example.shared','group.co.example'])})
        self.signing['/adhoc.app']=(None,['group.x'])
        self.assertEqual(code_identity('/adhoc.app'),{'team':None,'groups':[]})
        self.assertEqual(code_identity('/unsigned.app'),{'team':None,'groups':[]})

    def test_group_container_attributed_via_entitlements_and_team_prefix(self):
        self.app('Example','co.example.App',TEAM,['group.co.example.App'])
        g=self.container('group.co.example.App');t=self.container(TEAM+'.co.example.helper')
        unrelated=self.container('group.org.other')
        plan=uninstall_plan('co.example.App',str(self.home));validate_plan(plan)
        self.assertIn(g,self.paths(plan));self.assertIn(t,self.paths(plan));self.assertNotIn(unrelated,self.paths(plan))
        reasons={i['path']:i['action']['attribution'] for i in plan['items']}
        self.assertEqual(reasons[g],'group-entitlement');self.assertEqual(reasons[t],'team-prefix')
        for path in (g,t):verify_uninstall(next(i for i in plan['items'] if i['path']==path),str(self.home))

    def test_group_shared_by_two_apps_is_excluded(self):
        self.app('Example','co.example.App',TEAM,['group.co.example.shared'])
        self.app('Other','org.other.App','ZZZZZ99999',['group.co.example.shared'])
        g=self.container('group.co.example.shared')
        plan=uninstall_plan('co.example.App',str(self.home))
        self.assertNotIn(g,self.paths(plan))
        self.assertEqual(self.shared(plan)[g]['reason'],'shared-app-owner');self.assertIn('org.other.App',self.shared(plan)[g]['owners'])

    def test_same_team_sibling_makes_team_prefixed_container_shared(self):
        self.app('Example','co.example.App',TEAM);self.app('Sibling','co.example.Sibling',TEAM)
        t=self.container(TEAM+'.co.example.common')
        plan=uninstall_plan('co.example.App',str(self.home))
        self.assertNotIn(t,self.paths(plan));self.assertIn(t,self.shared(plan))

    def test_unsigned_app_unchanged(self):
        self.app('Example','co.example.App',signed=False)
        cache=self.home/'Library/Caches/co.example.App';cache.mkdir(parents=True)
        g=self.container(TEAM+'.co.example.App.group')
        plan=uninstall_plan('co.example.App',str(self.home))
        self.assertEqual(self.paths(plan),{str(cache),self.apps[0]['path']});self.assertEqual(plan['shared'],[])

    def test_apple_groups_never_removable(self):
        self.app('Example','co.example.App',TEAM,['group.com.apple.notes',TEAM+'.com.apple.thing'])
        a=self.container('group.com.apple.notes');b=self.container(TEAM+'.com.apple.thing')
        plan=uninstall_plan('co.example.App',str(self.home))
        self.assertFalse({a,b}&self.paths(plan))
        self.assertEqual({self.shared(plan)[a]['reason'],self.shared(plan)[b]['reason']},{'apple-group'})
        self.assertTrue(apple_group('com.apple.x') and apple_group('group.com.apple.x') and not apple_group('group.co.example'))
        with self.assertRaises(ValueError):
            self.apps.append({'path':'/Applications/Mail.app','bundle':'com.apple.mail','name':'Mail','version':'1'})
            uninstall_plan('com.apple.mail',str(self.home))

    def test_pkg_receipt_from_other_package_marks_shared(self):
        self.app('Example','co.example.App',TEAM)
        support=self.home/'Library/Application Support/Example';support.mkdir(parents=True)
        self.pkgs={'org.vendor.pkg':[str(support/'shared.dylib')],'co.example.App.pkg':[str(support/'own')]}
        plan=uninstall_plan('co.example.App',str(self.home))
        self.assertNotIn(str(support),self.paths(plan));self.assertEqual(self.shared(plan)[str(support)]['owners'],['org.vendor.pkg'])

    def test_user_receipts_reads_user_domain_plists(self):
        r=self.home/'Library/Receipts';r.mkdir(parents=True)
        (r/'org.vendor.pkg.plist').write_bytes(plistlib.dumps({'PackageIdentifier':'org.vendor.pkg','InstallPrefixPath':'Library'}))
        lib=self.home/'Library'
        self.assertEqual(REAL_USER_RECEIPTS(self.home),{'org.vendor.pkg':[str(lib/'vendor'),str(lib/'vendor/lib.dylib')]})
    def test_execution_refuses_when_group_becomes_shared(self):
        self.app('Example','co.example.App',TEAM,['group.co.example.shared'])
        g=self.container('group.co.example.shared')
        plan=uninstall_plan('co.example.App',str(self.home))
        item=next(i for i in plan['items'] if i['path']==g)
        verify_uninstall(item,str(self.home))
        self.app('Other','org.other.App','ZZZZZ99999',['group.co.example.shared'])
        with self.assertRaisesRegex(ValueError,'shared with another owner'):verify_uninstall(item,str(self.home))

    def test_execution_refuses_when_signing_identity_changes(self):
        a=self.app('Example','co.example.App',TEAM,['group.co.example.App'])
        g=self.container('group.co.example.App')
        item=next(i for i in uninstall_plan('co.example.App',str(self.home))['items'] if i['path']==g)
        self.signing[a['path']]=('QQQQQ11111',['group.co.example.App'])
        with self.assertRaisesRegex(ValueError,'Signing identity changed'):verify_uninstall(item,str(self.home))
        self.signing.pop(a['path'])
        with self.assertRaisesRegex(ValueError,'Signing identity changed'):verify_uninstall(item,str(self.home))


if __name__=='__main__':unittest.main()
