"""Dependency-free curses UI. All disk operations are read-only."""
import collections
import curses
import json
import os
from pathlib import Path
import threading
import time
import textwrap
from .engine import MODES, MODE_TEXT, human


def clean(text):
    # Paths are untrusted terminal text; never emit escape/control sequences.
    return ''.join(c if c.isprintable() else '?' for c in str(text))


def run_tui(scanner, mode='balanced', export_path=None):
    def main(scr):
        try:curses.curs_set(0)
        except curses.error:pass
        curses.use_default_colors()
        for i,fg in [(1,curses.COLOR_CYAN),(2,curses.COLOR_GREEN),(3,curses.COLOR_YELLOW),(4,curses.COLOR_WHITE),(5,curses.COLOR_RED)]:curses.init_pair(i,fg,-1)
        scr.keypad(True);scr.timeout(100)
        thread=threading.Thread(target=scanner.run,daemon=True);thread.start()
        state={'mode':mode,'group':'All categories','cursor':0,'offset':0,'query':'','eligible':False,'details':False,'help':False,'message':'','sort':'size','detailOffset':0}
        def put(y,x,text,attr=0,width=None):
            h,w=scr.getmaxyx()
            if y<0 or y>=h or x<0 or x>=w:return
            text=clean(text)
            try:scr.addnstr(y,x,text,max(0,min(w-x-1,width or w-x-1)),attr)
            except curses.error:pass
        def prompt(label):
            h,w=scr.getmaxyx();scr.timeout(-1)
            curses.echo()
            try:
                curses.curs_set(1);scr.move(h-2,0);scr.clrtoeol();put(h-2,0,label)
                raw=scr.getstr(h-2,min(len(label),w-3),max(1,w-len(label)-2));return raw.decode('utf-8','replace')
            finally:
                curses.noecho();scr.timeout(100)
                try:curses.curs_set(0)
                except curses.error:pass
        while True:
            h,w=scr.getmaxyx();scr.erase()
            if h<18 or w<82:
                put(0,0,'Resize Terminal to at least 82 columns x 18 rows. Q exits.');scr.refresh()
                if scr.getch() in (ord('q'),ord('Q')):scanner.cancel.set();break
                continue
            left=min(29,max(22,w//5));right=left+2
            put(1,2,'SOJI / TERMINAL',curses.A_BOLD|curses.color_pair(1))
            put(1,right,'DISK ANALYSIS',curses.A_BOLD)
            put(1,w-28,'LOCAL  ·  READ ONLY',curses.color_pair(2))
            x=right
            for i,name in enumerate(MODES,1):
                label=f' {i} {name.capitalize()} '
                attr=curses.A_REVERSE|curses.A_BOLD if state['mode']==name else curses.A_DIM
                put(3,x,label,attr);x+=len(label)+2
            put(4,right,MODE_TEXT[state['mode']],curses.A_DIM)
            findings=scanner.decisions(state['mode'])
            groups=collections.defaultdict(lambda:[0,0])
            for f in findings:
                groups[f.group][0]+=f.size
                if f.selected:groups[f.group][1]+=f.size
            group_names=['All categories']+sorted(groups,key=lambda k:groups[k][0],reverse=True)
            total=sum(f.size for f in findings);eligible=sum(f.size for f in findings if f.selected)
            put(3,2,'CATEGORIES',curses.A_DIM)
            group_index=group_names.index(state['group']) if state['group'] in group_names else 0
            group_offset=max(0,group_index-(h-12))
            for i,g in enumerate(group_names[group_offset:group_offset+h-10]):
                y=5+i;active=g==state['group'];size=total if g=='All categories' else groups[g][0]
                put(y,2,('› ' if active else '  ')+g,curses.A_BOLD|curses.color_pair(1) if active else 0,width=left-3)
                if active and y+1<h-5:pass
            put(h-5,2,human(scanner.bytes)+' measured',curses.A_BOLD)
            put(h-4,2,human(eligible)+' eligible',curses.color_pair(2))
            for y in range(2,h-2):put(y,left,'│',curses.A_DIM)
            status='Scanning' if not scanner.done else 'Partial scan' if scanner.limited or scanner.cancel.is_set() else 'Scan complete'
            put(6,right,f'{status}  ·  {scanner.visited:,} entries  ·  {scanner.unreadable} unreadable  ·  {scanner.skipped} excluded',curses.color_pair(3) if not scanner.done else curses.A_DIM)
            put(7,right,scanner.error or (scanner.current if not scanner.done else 'Scope: '+', '.join(scanner.roots)),curses.A_DIM)
            rows=[f for f in findings if (state['group']=='All categories' or f.group==state['group']) and (not state['eligible'] or f.selected) and (not state['query'] or state['query'].casefold() in (f.path+' '+f.group+' '+f.label).casefold())]
            if state['sort']=='name':rows.sort(key=lambda f:f.path.casefold())
            elif state['sort']=='age':rows.sort(key=lambda f:f.newest)
            state['cursor']=min(state['cursor'],max(0,len(rows)-1))
            page=max(1,h-16)
            state['offset']=min(state['offset'],state['cursor'])
            if state['cursor']>=state['offset']+page:state['offset']=state['cursor']-page+1
            put(9,right,f'{"SIZE":>10}   {"STATE":<7}  ITEM / CATEGORY',curses.A_DIM)
            for i,f in enumerate(rows[state['offset']:state['offset']+page]):
                y=10+i;chosen=state['offset']+i==state['cursor'];attr=curses.A_REVERSE if chosen else 0
                if chosen:put(y,right,' '*(w-right-1),attr)
                status='READY' if f.selected else 'HELD' if f.holds else 'REVIEW'
                put(y,right,f'{human(f.size):>10}',attr|curses.A_BOLD)
                put(y,right+13,f'{status:<7}',attr|curses.color_pair(2 if f.selected else 3 if f.holds else 4))
                text=f.label+'  ·  '+f.path.replace(scanner.home,'~',1)
                put(y,right+22,text,attr)
            if not rows:put(12,right,'Measuring folders…' if not scanner.done else 'No items match this view.',curses.A_DIM)
            selected=rows[state['cursor']] if rows else None
            put(h-5,right,f'{len(rows)} items  ·  sort: {state["sort"]}'+('  ·  filter: '+state['query'] if state['query'] else '')+('  ·  eligible only' if state['eligible'] else ''),curses.A_DIM)
            if selected:put(h-4,right,selected.decision,curses.color_pair(2 if selected.selected else 3))
            put(h-2,2,'↑↓ items  ←→ category  1–3 mode  Enter details  / search  A eligible  S sort  E export  ? help  Q quit',curses.A_DIM)
            if state['message']:put(h-3,right,state['message'],curses.color_pair(1))
            if state['help'] or (state['details'] and selected):
                boxw=min(w-8,108);boxh=min(h-4,30);ox=(w-boxw)//2;oy=(h-boxh)//2
                for y in range(oy,oy+boxh):put(y,ox,' '*boxw,curses.A_REVERSE,width=boxw)
                if state['help']:
                    lines=['KEYS / RECONSTRUCTION NOTES','','1 Careful — only clearly disposable items.','2 Balanced — stale items, with per-item judgments.','3 Aggressive — unused recoverable items.','','All modes respect holds, retained versions, activity, and identity.','375 exact hints; independently reconstructed rules and index.','AI runs, plans, cleanup and undo are explicit terminal commands.','','↑/↓ or J/K: items     ←/→ or H/L: categories','Enter: evidence       /: search       A: eligible only','S: cycle size/name/age   E: export JSON   R: rescan','C: cancel scan          Q: exit         Esc: close','','Use soji analyse for AI; soji plan then soji clean for cleanup.']

                else:
                    f=selected
                    age=max(0,(scanner.now-f.newest)/3600)
                    lines=[f.label, f.path,'',f'{human(f.size)} allocated · {human(f.apparent)} logical · {f.files:,} files · idle {age:.1f} h',f'Category: {f.group}',f'Hint: {f.hint_id or "unmatched"} · tier: {f.tier} · returns: {f.comes_back}',f'Pattern: {f.matched_pattern or "none"}','','DECISION: '+f.decision,'','SHIPPED RULE: '+(f.smart_rule or 'No explanatory rule text'),json.dumps(f.rule,ensure_ascii=False),'']
                    about=scanner.catalog.groups.get(f.group,{})
                    lines += [about[k] for k in ('whatItIs','howItComesBack') if about.get(k)]
                    lines+=['','MODE COMPARISON']
                    for m in MODES:
                        yes,why=f.decide(m,scanner.now);lines.append(f'{m:9} {"READY" if yes else "KEEP":5} {why}')
                wrapped_lines=[]
                for line in lines: wrapped_lines.extend(textwrap.wrap(clean(line),boxw-5) or [''])
                visible=boxh-3
                state['detailOffset']=min(state['detailOffset'],max(0,len(wrapped_lines)-visible))
                for i,line in enumerate(wrapped_lines[state['detailOffset']:state['detailOffset']+visible]):
                    put(oy+1+i,ox+2,line,curses.A_REVERSE)
                put(oy+boxh-2,ox+2,'↑↓ scroll · Esc / Enter close',curses.A_REVERSE|curses.A_BOLD)
            scr.refresh();key=scr.getch()
            if key==-1:continue
            if state['help'] or state['details']:
                if key in (curses.KEY_DOWN,ord('j')):state['detailOffset']+=1
                elif key in (curses.KEY_UP,ord('k')):state['detailOffset']=max(0,state['detailOffset']-1)
                elif key in (curses.KEY_NPAGE,):state['detailOffset']+=10
                elif key in (curses.KEY_PPAGE,):state['detailOffset']=max(0,state['detailOffset']-10)
                elif key in (27,10,13,ord('q'),ord('?')):state['help']=False;state['details']=False
                continue
            if key in (ord('q'),ord('Q')):scanner.cancel.set();break
            if key in (curses.KEY_DOWN,ord('j')):state['cursor']=min(len(rows)-1,state['cursor']+1)
            elif key in (curses.KEY_UP,ord('k')):state['cursor']=max(0,state['cursor']-1)
            elif key in (curses.KEY_NPAGE,):state['cursor']=min(len(rows)-1,state['cursor']+page)
            elif key in (curses.KEY_PPAGE,):state['cursor']=max(0,state['cursor']-page)
            elif key in (curses.KEY_LEFT,ord('h'),curses.KEY_RIGHT,ord('l')):
                i=group_names.index(state['group']) if state['group'] in group_names else 0
                i=(i+(-1 if key in (curses.KEY_LEFT,ord('h')) else 1))%len(group_names)
                state['group']=group_names[i];state['cursor']=0;state['offset']=0
            elif key in (ord('1'),ord('2'),ord('3')):state['mode']=MODES[key-ord('1')]
            elif key in (10,13):state['details']=bool(selected);state['detailOffset']=0
            elif key==ord('?'):state['help']=True;state['detailOffset']=0
            elif key==ord('/'):state['query']=prompt('Search: ');state['cursor']=0;state['offset']=0
            elif key==27:state['query']='';state['eligible']=False
            elif key in (ord('a'),ord('A')):state['eligible']=not state['eligible'];state['cursor']=0;state['offset']=0
            elif key in (ord('s'),ord('S')):state['sort']={'size':'name','name':'age','age':'size'}[state['sort']]
            elif key in (ord('c'),ord('C')):scanner.cancel.set();state['message']='Stopping after the current filesystem operation…'
            elif key in (ord('r'),ord('R')) and scanner.done:
                options=dict(home=scanner.home,protected=scanner.protected,max_files=scanner.max_files,max_seconds=scanner.max_seconds,min_bytes=scanner.min_bytes,context=scanner.context)
                if hasattr(scanner,'database'):options.update(database=scanner.database,refresh=True)
                from .demo import DemoScanner
                if isinstance(scanner,DemoScanner):scanner.__init__()
                else:scanner.__init__(scanner.roots,**options)
                thread=threading.Thread(target=scanner.run,daemon=True);thread.start();state['message']=''
            elif key in (ord('e'),ord('E')):
                target=Path(export_path or Path.home()/f'soji-{time.strftime("%Y%m%d-%H%M%S")}.json')
                try:target.write_text(json.dumps(scanner.report(state['mode']),indent=2));state['message']='Exported '+str(target)
                except OSError as e:state['message']='Export failed: '+str(e)
        thread.join(timeout=1)
    curses.wrapper(main)
