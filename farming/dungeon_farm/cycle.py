"""Post-clear lifecycle: maintain once, request replay once, verify fresh room."""
import json
import time
from pathlib import Path
from ctypes import wintypes as W
from follow import Windows,C
from coordinate_connection import CoordinateConnection
from dungeon_farm.combat_telemetry import connect_solo
from dungeon_farm.route import read_doors
from dungeon_farm.screen_signals import ScreenSignals
from dungeon_farm.cycle_inputs import CycleInputs

DATA=Path(__file__).resolve().parent

def dungeon_difficulty(signals,dungeon='根特东门'):
    from dungeon_farm.screen_signals import normalize
    joined=''.join(normalize(t) for t in signals.get('texts',[]))
    if normalize(dungeon) not in joined:return None
    return next((v for v in ('普通级','冒险级','勇士级','王者级','英雄级','地狱级') if v in joined),None)

def fresh_dungeon_room(signals,sample,old_scene,doors,difficulty='普通级',dungeon='根特东门'):
    """Ghent's start side varies; verify the dungeon, not one doorway layout."""
    from dungeon_farm.screen_signals import normalize
    text=''.join(normalize(t) for t in signals.get('texts',[]))
    return bool(sample and sample['scene']!=old_scene and doors
                and normalize(dungeon) in text and difficulty in text
                and not signals.get('retry') and not signals.get('finished')
                and not signals.get('exhausted') and not signals.get('dead'))

class ReplayPlan:
    def __init__(self):self.stage='wait_result';self.due=0;self.sent_at=None;self.closed=0;self.needs_disassembly=True
    def action(self,signals,now):
        if signals.get('exhausted'):return 'fatigue_empty'
        if signals.get('dead'):return 'character_dead'
        if now<self.due:return None
        if signals.get('notice'):
            return 'confirm_notice' if signals.get('notice_confirm') else None
        if signals.get('overlay') and self.stage!='wait_entry':
            return 'close_overlay' if self.closed<4 else 'overlay_blocked'
        if self.stage=='wait_result' and signals.get('retry'):return 'disassemble' if self.needs_disassembly else 'sell'
        if self.stage=='repair':return 'repair'
        if self.stage=='retry' and signals.get('retry'):return 'retry'
        return None
    def acknowledge(self,action,now):
        if action=='confirm_notice':self.due=now+1
        elif action=='close_overlay':self.closed+=1;self.due=now+1
        elif action in ('disassemble','sell'):self.stage='repair';self.due=now+1.5
        elif action=='repair':self.stage='retry';self.due=now+1.5
        elif action=='retry':self.stage='wait_entry';self.sent_at=now

def replay(control,report,old_scene,profile,dungeon='根特东门',reenter=True):
    win=Windows();keys=CycleInputs(win);screen=ScreenSignals(dungeon);plan=ReplayPlan()
    win.u.GetWindowThreadProcessId.argtypes=[W.HWND,C.POINTER(W.DWORD)]
    connection=CoordinateConnection(profile,connector=connect_solo)
    active=0;last=time.monotonic();fresh=0;expected_difficulty=None;inventory_checked=False;after_checked=False
    log=(DATA/'cycle-events.jsonl').open('a',encoding='utf-8')
    def event(state,**kw):
        report({'state':state,**kw})
        log.write(json.dumps({'time':time.time(),'state':state,**kw},ensure_ascii=False)+'\n');log.flush()
    try:
        event('waiting_rewards')
        while not control.stop.is_set():
            now=time.monotonic();dt=now-last;last=now
            hwnd=win.game()
            if control.paused.is_set() or not hwnd or not win.foreground(hwnd):
                if plan.sent_at is not None:plan.sent_at+=dt
                win.release();report({'state':'paused' if control.paused.is_set() else 'waiting_foreground'})
                control.stop.wait(.1);continue
            if any(win.u.GetAsyncKeyState(v)&0x8000 for v in (0x1b,0x0d)):
                control.paused.set();continue
            active+=dt
            if active>120:return 'replay_timeout'
            signals=screen.poll(win,hwnd,full=True)
            if not signals:control.stop.wait(.05);continue
            if plan.stage!='wait_entry':
                expected_difficulty=dungeon_difficulty(signals,dungeon) or expected_difficulty
            if plan.stage=='wait_result' and signals.get('retry') and not inventory_checked:
                from dungeon_farm.inventory import inspect_inventory,disassemble_needed
                inventory=inspect_inventory(win,keys,screen,hwnd,control)
                if control.cancelled():continue
                control.inventory=inventory
                reserve=max(100,control.round_cube_upper*2+30)
                plan.needs_disassembly=disassemble_needed(inventory['cubes'],reserve)
                event('inventory_checked',inventory=inventory,reserve=reserve,disassemble=plan.needs_disassembly)
                inventory_checked=True
                continue
            action=plan.action(signals,now)
            if action=='confirm_notice':
                event('maintenance_confirmed',maintenance=signals['notice'],texts=signals['texts'])
                if keys.click(signals['notice_confirm'],hwnd,control.cancelled):plan.acknowledge(action,time.monotonic())
                continue
            if action in ('fatigue_empty','character_dead','overlay_blocked'):
                event(action,texts=signals['texts']);return action
            if action=='close_overlay':
                event(action)
                if keys.close_overlay(hwnd,control.cancelled):plan.acknowledge(action,time.monotonic())
                continue
            if action in ('disassemble','sell','repair'):
                event(action)
                if keys.chord(action,hwnd,control.cancelled):
                    event('maintenance_input_sent',maintenance=action,input=keys.last_chord_state)
                    plan.acknowledge(action,time.monotonic())
                continue
            if action=='retry':
                if not after_checked:
                    from dungeon_farm.inventory import inspect_inventory
                    control.inventory=inspect_inventory(win,keys,screen,hwnd,control)
                    if control.cancelled():continue
                    event('inventory_after_maintenance',inventory=control.inventory)
                    after_checked=True
                    continue
                if not reenter:return 'finished'
                event('retrying',key='F10',difficulty=expected_difficulty or '普通级')
                if keys.key('retry',hwnd,control.cancelled):plan.acknowledge(action,time.monotonic())
                continue
            if plan.stage=='wait_entry':
                pid=W.DWORD();win.u.GetWindowThreadProcessId(hwnd,C.byref(pid))
                sample=connection.sample(pid.value)
                doors=read_doors(connection.reader,sample['scene']) if sample else []
                valid=fresh_dungeon_room(signals,sample,old_scene,doors,expected_difficulty or '普通级',dungeon)
                fresh=fresh+1 if valid else 0
                if fresh>=2:event('reentered');return 'reentered'
                if now-plan.sent_at>35:
                    event('replay_failed',texts=signals['texts']);return 'replay_failed'
        return 'stopped'
    finally:win.release();connection.close();screen.close();log.close()
