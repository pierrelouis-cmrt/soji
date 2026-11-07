"""Explicitly invoked routine scheduling and auto-clean eligibility policies."""
import calendar
import datetime as dt
import json
from pathlib import Path
import shutil
import time
from .util import atomic_json,read_json
from .cleanup import create_plan,Cleaner

def idle_enough(timestamp, minimum_hours, now):
    """RoutinePermit.idleEnough at 0x10044f05c: missing date refuses; >= boundary."""
    return timestamp is not None and now-timestamp >= minimum_hours*3600


class Routines:
    def __init__(self,state):self.state=Path(state).expanduser().resolve();self.path=self.state/'routines.json'
    def list(self):return read_json(self.path) or []
    def save(self,routine):
        if not routine.get('id') or not routine.get('paths'):raise ValueError('Routine requires id and paths')
        if routine.get('mode','aggressive') not in ('careful','balanced','aggressive'):raise ValueError('Invalid cleanup level')
        if routine.get('everyHours',24)<1:raise ValueError('Routine interval must be at least an hour')
        rows=[r for r in self.list() if r['id']!=routine['id']]+[routine];atomic_json(self.path,rows);return routine
    def due(self,routine,now=None):
        now=now or time.time();last=routine.get('lastRun',routine.get('createdAt',0))
        if not routine.get('enabled',False) or last>now:return False
        schedule=routine.get('schedule')
        if not schedule:return now-last>=routine.get('everyHours',24)*3600
        current=dt.datetime.fromtimestamp(now)
        repeat=schedule.get('repeats','weekly');hour=int(schedule.get('hour',10));minute=int(schedule.get('minute',0))
        if not (0<=hour<=23 and 0<=minute<=59):raise ValueError('Invalid routine time')
        for back in range(367):
            day=current.date()-dt.timedelta(days=back)
            # Foundation Calendar convention: Sunday=1 ... Saturday=7.
            weekday=(day.weekday()+1)%7+1
            if repeat=='weekly' and weekday not in schedule.get('weekdays',[]):continue
            if repeat=='monthly' and day.day!=min(max(1,int(schedule.get('day',1))),calendar.monthrange(day.year,day.month)[1]):continue
            if repeat not in ('daily','weekly','monthly'):raise ValueError('Invalid routine repeat')
            at=dt.datetime.combine(day,dt.time(hour,minute)).timestamp()
            if at<=now:return at>last
        return False
    def run(self,routine,scanner,apply=False):
        if not self.due(routine):return {'skipped':'Routine not due or disabled'}
        conditions=routine.get('conditions',{});groups=set(routine.get('groups',[]))
        if not groups and routine.get('target',{}).get('group'):groups.add(routine['target']['group'])
        idle=conditions.get('unusedForHours',routine.get('unusedForHours',168));minimum=conditions.get('minItemBytes',0)
        free=conditions.get('freeBelow')
        if free:
            usage=shutil.disk_usage(scanner.home)
            percent=free.get('freeBelowPercent',{}).get('_0') if isinstance(free,dict) else None
            byte_limit=free.get('freeBelowBytes',{}).get('_0') if isinstance(free,dict) else None
            if percent is not None and usage.free/usage.total*100>=percent:return {'skipped':'Free space above routine threshold'}
            if byte_limit is not None and usage.free>=byte_limit:return {'skipped':'Free space above routine threshold'}
        chosen=[]
        for f in scanner.decisions(routine.get('mode','aggressive')):
            if f.selected and f.size>=minimum and f.tier=='regenerable' and f.comes_back in ('downloads','rebuilds') and (not groups or f.group in groups) and idle_enough(max(f.newest,f.last_activity or 0,f.date_added or 0),idle,scanner.now):chosen.append(f.path)
        plan=create_plan(scanner,routine.get('mode','aggressive'),chosen,method='permanent')
        plan['routinePermit']={'routineID':routine['id'],'groups':sorted(groups),'minIdleHours':idle,'minItemBytes':minimum}
        from .cleanup import digest
        plan.pop('digest');plan['digest']=digest(plan)
        if not apply:return {'plan':plan,'executed':False}
        result=Cleaner(self.state).apply(plan,permanent=True)
        routine['lastRun']=time.time();self.save(routine);return result

def auto_clean_plan(scanner,settings):
    if not settings.get('enabled'):return {'skipped':'Auto mode is disabled'}
    disk=shutil.disk_usage(scanner.home)
    if disk.free/disk.total*100>=settings.get('freeBelowPercent',5):return {'skipped':'Free-space threshold not reached'}
    if time.time()-settings.get('lastRun',0)<settings.get('minHoursBetweenRuns',6)*3600:return {'skipped':'Minimum interval not reached'}
    minimum=settings.get('minItemBytes',0)
    paths=[f.path for f in scanner.decisions('careful') if f.selected and f.size>=minimum and f.tier=='regenerable' and f.comes_back in ('rebuilds','downloads') and (not settings.get('groups') or f.group in settings['groups'])]
    plan=create_plan(scanner,'careful',paths,method='permanent')
    plan['routinePermit']={'routineID':'auto','groups':settings.get('groups',[]),'minIdleHours':settings.get('minIdleHours',0),'minItemBytes':minimum}
    from .cleanup import digest
    plan.pop('digest');plan['digest']=digest(plan)
    if sum(i['size'] for i in plan['items'])<settings.get('minGainBytes',1_000_000_000):return {'skipped':'Minimum gain not reached'}
    return {'plan':plan}
