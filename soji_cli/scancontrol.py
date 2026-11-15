"""Scan configuration, capabilities and lifecycle for interactive clients."""
import dataclasses
import threading

@dataclasses.dataclass(frozen=True)
class ScanConfiguration:
    roots: tuple
    options: dict

    @classmethod
    def of(cls,scanner):
        names=('home','protected','max_files','max_seconds','min_bytes','context','recent_activity_hours','tick_trash','walk_backend')
        options={k:getattr(scanner,k) for k in names if hasattr(scanner,k)}
        return cls(tuple(scanner.roots),options)

class ScanController:
    def __init__(self,scanner):
        self.scanner=scanner;self.thread=None;self.revision=0
        self.configuration=ScanConfiguration.of(scanner)

    @property
    def can_clean(self):return getattr(self.scanner,'can_clean',True)

    def start(self):
        if self.thread and self.thread.is_alive():raise RuntimeError('Scan already running')
        def run():
            try:self.scanner.run()
            finally:self.revision+=1
        self.thread=threading.Thread(target=run,daemon=True);self.thread.start()
        return self.thread

    def restart(self,refresh=False):
        if self.thread and self.thread.is_alive():
            self.scanner.cancel.set();self.thread.join()
        factory=getattr(self.scanner,'new_scan',None)
        self.scanner=factory(refresh) if factory else type(self.scanner)(list(self.configuration.roots),**self.configuration.options)
        self.revision+=1
        self.start()
        return self.scanner,self.thread
