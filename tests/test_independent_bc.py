"""Independent e802e92 proofs: isolated fake-home runtime moves only."""
import sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from test_version_policy_context import Fixture
from soji_cli.cleanup import Cleaner,create_plan,digest
from soji_cli.engine import Scanner
from soji_cli.specialized import ProjectPins

class IndependentBC(unittest.TestCase):
    def fixture(self):
        f=Fixture();f.setUp();self.addCleanup(f.doCleanups);return f
    def test_new_pin_in_protected_project_holds_runtime(self):
        f=self.fixture();project=f.home/'code/app'
        s=Scanner([str(f.home)],home=str(f.home),protected=[str(project)],min_bytes=1);s.run()
        plan=create_plan(s,'aggressive',paths={f.path('v18.20.0')})
        self.assertEqual(len(plan['items']),0)
        # Construct the historical plan before its scope became protected.
        s=Scanner([str(f.home)],home=str(f.home),min_bytes=1);s.run()
        plan=create_plan(s,'aggressive',paths={f.path('v18.20.0')});self.assertEqual(len(plan['items']),1)
        plan['protected']=[str(project)];plan.pop('digest',None);plan['digest']=digest(plan)
        f.write('code/app/.nvmrc','18.20.0\n')
        result=Cleaner(f.state,trash_directory=f.trash).apply(plan)
        self.assertEqual(result['completed'],0,result)
        self.assertTrue(Path(f.path('v18.20.0')).exists())
    def test_depth_bound_is_unknown(self):
        f=self.fixture();p=f.home
        for _ in range(129):p=p/'d'
        p.mkdir(parents=True);(p/'.nvmrc').write_text('18.20.0\n')
        pins=ProjectPins().discover([str(f.home)],lambda p:'')
        self.assertIsNotNone(pins.hold(f.path('v18.20.0'),'node'),pins.incomplete)

if __name__=='__main__':unittest.main()
