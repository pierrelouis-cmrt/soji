"""Regression cases derived from the installed ARM64 executable; all data is disposable."""
import datetime as dt
import os
from pathlib import Path
import plistlib
import tempfile
from types import SimpleNamespace as NS
import unittest
from soji_cli.engine import Finding
from soji_cli.specialized import (SpecializedRules,DeviceCatalog,version_match,
    workspace_missing,archive_uploads,rule_threshold_days,retention_count,device_build_prepared)

class RecoveredRules(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='soji-rules-')
        self.addCleanup(self.temp.cleanup)
        self.home=Path(self.temp.name)
        self.rules=SpecializedRules.__new__(SpecializedRules)
        self.rules.home=self.home;self.rules.archive_cache={};self.rules.siblings={'fixture':[]}
        self.rules.scanner=NS(nodes={},now=2000000000,catalog=NS(hints=[]))
        self.rules.apps=NS(owner=lambda p:[])
        self.rules.activity=NS(errors=[],last=lambda p:None)
        self.rules.tools=NS(use=lambda p:None)
    def plist(self,path,value):
        p=self.home/path;p.parent.mkdir(parents=True,exist_ok=True)
        p.write_bytes(plistlib.dumps(value));return p
    def node(self,name,stamp):
        path=str(self.home/name)
        self.rules.scanner.nodes[path]=NS(newest=stamp,reason='')
        self.rules.siblings['fixture'].append(path)
        return path
    def finding(self,path,rule):
        return Finding(path,100,100,1,self.rules.scanner.nodes[path].newest,
                       'Tool versions','Fixture',hint_id='fixture',rule=rule)
    def test_rank_counts_dates_not_numeric_version(self):
        old=self.node('v99.0',100);new=self.node('v1.0',200)
        self.assertEqual(self.rules.retained(self.finding(old,{'keepNewest':1}))[1],1)
        self.assertEqual(self.rules.retained(self.finding(new,{'keepNewest':1}))[1],0)
    def test_highest_version_kept_even_when_touched_earlier(self):
        # Seen in a real run: chromium-1248 older mtime than chromium-1234.
        high=self.node('chromium-1248',100);low=self.node('chromium-1234',200)
        rule={'keepNewest':1,'keepBy':'product'}
        retained,rank,_,version_rank=self.rules.retained(self.finding(high,rule))
        self.assertEqual((retained,rank,version_rank),(True,1,0))
        for mode in ('careful','balanced','aggressive'):
            self.assertIn(mode,self.rules.evaluate(self.finding(high,rule)).mode_holds)
            self.assertIn(mode,self.rules.evaluate(self.finding(low,rule)).mode_holds)
    def test_version_rank_never_releases_timestamp_newest(self):
        old=self.node('tool-2.0',100);self.node('tool-10.0',50);self.node('tool-1.0',300)
        f=self.rules.evaluate(self.finding(old,{'keepNewest':1,'keepBy':'product'}))
        self.assertNotIn('balanced',f.mode_holds)
        self.assertEqual(next(e for e in f.evidence if e['check']=='retention')['versionRank'],1)
    def test_equal_timestamps_share_rank(self):
        a=self.node('v1',100);self.node('v2',100)
        self.assertEqual(self.rules.retained(self.finding(a,{'keepNewest':1}))[1],0)
    def test_generic_rank_scoped_to_parent(self):
        a=self.node('one/v1',100);self.node('two/v2',200)
        self.assertEqual(self.rules.retained(self.finding(a,{'keepNewest':1}))[1],0)
    def test_device_group_is_name_token_not_info_plist(self):
        self.assertEqual(self.rules.grouping('/x/iPhone15,2 18.0 (22A1)','device'),'iPhone15,2')
        self.assertEqual(self.rules.grouping('/x/18.0 (22A1)','device'),'')
    def test_product_and_major_tokenization(self):
        g=self.rules.grouping
        self.assertEqual(g('/x/Android Studio_2026.1','product'),'android-studio')
        self.assertEqual(g('/y/Android-Studio-v2026.2','major'),'android-studio@2026')
        self.assertEqual(g('/x/35.0.0','major'),'@35')
        self.assertEqual(g('/x/Chrome120','product'),'chrome120')
    def test_retention_counts_change_per_mode(self):
        self.assertEqual([retention_count(2,m) for m in ('careful','balanced','aggressive')],[3,2,1])
        self.assertEqual(retention_count(1,'aggressive'),1)
    def test_evaluate_applies_per_mode_retention(self):
        a=self.node('v1',100);self.node('v2',200)
        f=self.rules.evaluate(self.finding(a,{'keepNewest':1}))
        self.assertIn('careful',f.mode_holds)
        self.assertNotIn('balanced',f.mode_holds)
        self.assertNotIn('aggressive',f.mode_holds)
    def test_rule_age_clocks_have_different_scaling_and_day_floor(self):
        r={'untouchedDays':14,'projectUntouchedDays':8}
        self.assertEqual(rule_threshold_days(r,'careful'),{'untouchedDays':28,'projectUntouchedDays':32})
        self.assertEqual(rule_threshold_days(r,'aggressive'),{'untouchedDays':7,'projectUntouchedDays':2})
        self.assertEqual(rule_threshold_days({'untouchedDays':.1},'aggressive'),{'untouchedDays':1})
        self.assertEqual(rule_threshold_days({},'balanced'),{})
    def test_pin_matching_is_literal_not_semver_range(self):
        self.assertTrue(version_match('NODE-v22.1.0','22'))
        self.assertTrue(version_match('ruby-3.3.1','RUBY-3.3'))
        for pin in ('^22','22.x','22.*','>=22',''):
            self.assertFalse(version_match('22.1',pin),pin)
    def test_active_text_dash_prefix_suffix_and_size_limit(self):
        marker=self.home/'active';marker.write_text('release')
        self.assertEqual(self.rules.active('/x/release-123',[str(marker)]),str(marker))
        self.assertEqual(self.rules.active('/x/123-release',[str(marker)]),str(marker))
        marker.write_text('22')
        self.assertIsNone(self.rules.active('/x/v220.0',[str(marker)]))
        marker.write_text('22'+' '*4094)
        self.assertIsNone(self.rules.active('/x/v22.0',[str(marker)]))
    def test_active_markers_are_literal_and_strict_utf8(self):
        marker=self.home/'active';marker.write_bytes(b'22\xff')
        self.assertIsNone(self.rules.active('/x/v22.0',[str(marker)]))
        marker.write_text('22')
        self.assertIsNone(self.rules.active('/x/v22.0',[str(self.home/'act*')]))
    def test_active_relative_symlink_descendant(self):
        target=self.home/'versions/v1/bin';target.mkdir(parents=True)
        marker=self.home/'current';marker.symlink_to('versions/v1/bin')
        self.assertEqual(self.rules.active(str(target.parent),[str(marker)]),str(marker))
        self.assertIsNone(self.rules.active(str(self.home/'versions/v10'),[str(marker)]))
    def test_workspace_missing_includes_bad_metadata_and_empty_path(self):
        folder=self.home/'Derived';folder.mkdir()
        self.assertTrue(workspace_missing(folder))
        for value in ({},{'WorkspacePath':''},{'WorkspacePath':7}):
            self.plist('Derived/info.plist',value);self.assertTrue(workspace_missing(folder))
        self.plist('Derived/info.plist',{'WorkspacePath':str(self.home)})
        self.assertFalse(workspace_missing(folder))
        self.plist('Derived/info.plist',{'WorkspacePath':self.home.as_uri()})
        self.assertTrue(workspace_missing(folder)) # original does not decode URLs
    def test_prepared_build_requires_marker_and_visible_payload(self):
        folder=self.home/'device';folder.mkdir()
        self.assertFalse(device_build_prepared(folder))
        (folder/'.processed_dyld_shared_cache_arm64').touch()
        self.assertFalse(device_build_prepared(folder))
        (folder/'Symbols').mkdir()
        self.assertTrue(device_build_prepared(folder))
    def test_archive_platform_separates_bundle_groups(self):
        archive=self.home/'app.xcarchive'
        self.plist('app.xcarchive/Info.plist',{'ApplicationProperties':{
            'CFBundleIdentifier':'Example.App','ApplicationPath':'Applications/App.app'}})
        self.plist('app.xcarchive/Products/Applications/App.app/Info.plist',{'DTPlatformName':'iPhoneOS'})
        self.assertEqual(self.rules.grouping(str(archive),'bundle'),'id:example.app|iphoneos')
    def test_upload_success_task_and_destination_identity(self):
        rows=[{'task':'Upload','uploadEvent':{'state':'SUCCESS'},'uploadDestination':'Apple'},
              {'task':'validate','uploadEvent':{'state':'success'},'destination':'Apple'},
              {'task':'upload','uploadEvent':{'state':'failed'},'destination':'Other'},
              {'task':'Export','uploadEvent':{'state':'success'},'destination':'Other'}]
        self.assertEqual(archive_uploads({'Distributions':rows}),{'apple|upload','other|export'})
        self.assertEqual(archive_uploads({'Uploaded':True,'uploadDestination':'Apple'}),set())
    def test_newest_upload_is_per_identity_and_creation_date(self):
        old=self.node('old.xcarchive',999);new=self.node('new.xcarchive',100)
        for path,day,destination in ((old,1,'Apple'),(new,2,'Other')):
            self.plist(Path(path).name+'/Info.plist',{'CreationDate':dt.datetime(2020,1,day),
                'ApplicationProperties':{'CFBundleIdentifier':'EXAMPLE.App'},
                'Distributions':[{'task':'upload','uploadEvent':{'state':'success'},'destination':destination}]})
        self.assertTrue(self.rules.newest_uploaded(old,[old,new]))
        self.assertEqual(self.rules.retained(self.finding(old,{'keepNewest':1,'keepBy':'bundle'}))[1],1)
        self.assertEqual(self.rules.grouping(old,'bundle'),'id:example.app|')
        self.rules.archive_cache[new]=(self.rules.archive(new)[0],{'apple|upload'},self.rules.archive(new)[2])
        self.assertFalse(self.rules.newest_uploaded(old,[old,new]))

if __name__=='__main__':unittest.main()
