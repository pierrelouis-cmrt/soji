"""Synthetic rows for UI exploration, never substituted into a real scan."""
import threading
import time
from .engine import Scanner, Finding

class DemoScanner(Scanner):
    def __init__(self):
        super().__init__(['/demo'],home='/demo');self.database=None
        self.current='Synthetic demo — press Q and run without --demo to scan your disk'
    def run(self):
        self.started=time.monotonic();self.now=time.time()
        examples=[('Library/Developer/Xcode/DerivedData/OldProject','xcode-derived-data',18_600_000_000,32),('.npm/_cacache','npm-cache',5_400_000_000,21),('Projects/site/node_modules','node-modules',3_100_000_000,23),('Library/Caches/pip','pip-cache',1_750_000_000,2),('Library/Logs/DiagnosticReports','diagnostic-reports',920_000_000,18),('Movies/recording.mov','',8_200_000_000,60),('.cache/huggingface','huggingface-cache',12_900_000_000,40),('Library/Application Support/Claude/Cache','electron-http-cache',420_000_000,0.01)]
        for rel,hid,size,days in examples:
            h=next((h for h in self.catalog.hints if h['id']==hid),None)
            f=Finding('/demo/'+rel,size,size,int(size/17000),self.now-days*86400,h['group'] if h else 'Large media files',h['label'] if h else 'Personal recording',hid,h['tier'] if h else 'userData',h['comesBack'] if h else 'gone',h.get('rule',{}) if h else {},h.get('ruleSummary','') if h else '',h.get('reviewOnly',False) if h else True,project_idle_hours=days*24)
            if days<1:f.holds=['Running: Claude']
            if hid=='xcode-derived-data':f.special_min_hours=14*24;f.evidence=[{'check':'workspaceMissing','status':'demo project exists'}]
            self.findings.append(f)
        self.findings.sort(key=lambda f:f.size,reverse=True)
        self.bytes=sum(f.size for f in self.findings);self.visited=82490;self.done=True;self.finished=time.monotonic()
