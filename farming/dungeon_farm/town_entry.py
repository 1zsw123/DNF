"""Enter Ghent East from the observed Ghent town entrance with normal input."""
import json,time
from pathlib import Path
from ctypes import wintypes as W
from follow import Windows,C
from coordinate_connection import CoordinateConnection
from dungeon_farm.combat_telemetry import connect_solo
from dungeon_farm.cycle_inputs import CycleInputs
from dungeon_farm.screen_signals import ScreenSignals
from dungeon_farm.cycle import fresh_dungeon_room,dungeon_difficulty
from dungeon_farm.route import read_doors
from dungeon_farm.revival import Revival

class EntranceAlignment:
    """Bounded vertical probes only after a rightward town step did not move."""
    def __init__(self):
        self.previous=None;self.last='right';self.probes=0

    def direction(self,position):
        import math
        if not position or not all(math.isfinite(v) for v in position[:2]):
            return 'right'
        stalled=(self.previous is not None and self.last=='right'
                 and abs(position[0]-self.previous[0])<4)
        direction='right'
        if stalled and self.probes<3:
            direction='up' if self.probes==0 else 'down'
            self.probes+=1
        self.previous=tuple(position);self.last=direction
        return direction

def prepare(control,report,allow_town_entry=False,dungeon='根特东门',difficulty='普通级'):
    root=Path(__file__).resolve().parents[1]
    from dungeon_farm.characters import selected_profile
    profile=selected_profile(control.character)
    win=Windows();keys=CycleInputs(win);screen=ScreenSignals(dungeon)
    win.u.GetWindowThreadProcessId.argtypes=[W.HWND,C.POINTER(W.DWORD)]
    conn=CoordinateConnection(profile,connector=connect_solo)
    selected=False;selection_seen=False;normal_steps=0;normal_confirmations=0;select_attempts=0;enter_sent=False;moves=0;active=0;last=time.monotonic();unconfirmed=0;revival=Revival();selection_requested=False
    alignment=EntranceAlignment()
    overlay_closes=0
    try:
        while not control.stop.is_set():
            now=time.monotonic();dt=now-last;last=now;hwnd=win.game()
            if control.paused.is_set() or not win.foreground(hwnd):
                report({'state':'paused' if control.paused.is_set() else 'waiting_foreground'});control.stop.wait(.1);continue
            active+=dt
            if active>90:return 'entry_failed'
            pid=W.DWORD();win.u.GetWindowThreadProcessId(hwnd,C.byref(pid))
            sample=conn.sample(pid.value)
            if not sample and not allow_town_entry and conn.reader:
                base=conn.reader.uint(conn.reader.local_root)
                if base and conn.reader.uint(base+0xb8)==0:
                    return 'waiting_dungeon'
            signals=screen.poll(win,hwnd,full=True)
            if not signals:control.stop.wait(.06);continue
            (Path(__file__).parent/'entry-observation.json').write_text(json.dumps({'time':time.time(),'signals':signals,'selected':selected,'enter_sent':enter_sent},ensure_ascii=False,indent=2),encoding='utf8')
            if signals['exhausted']:return 'fatigue_empty'
            if signals.get('overlay') and not sample and not signals['selection']:
                # Inventory inspection can leave its panel open when the
                # client's input poll misses the closing I key. Confirm its
                # presence before each bounded retry; never move underneath it.
                if overlay_closes>=2:return 'entry_failed'
                if keys.key('inventory',hwnd,control.cancelled):overlay_closes+=1
                control.stop.wait(.6)
                continue
            if signals.get('finished'):
                if not allow_town_entry:return 'waiting_dungeon'
                if not selection_requested and signals.get('retry'):
                    report({'state':'selecting_dungeon'})
                    if keys.key('select_other',hwnd,control.cancelled):
                        selection_requested=True;selection_seen=True
                continue
            if selection_requested and sample and not enter_sent:
                continue
            if revival.observe(signals['dead']):control.dual_blades_active=False
            revive_action=revival.action(time.monotonic())
            if revive_action:
                report({'state':revive_action})
                if revive_action=='revive_failed':return revive_action
                if revive_action=='revive' and keys.key('revive',hwnd,control.cancelled):revival.sent(time.monotonic())
                continue
            if sample and not enter_sent:
                observed=dungeon_difficulty(signals,dungeon)
                from dungeon_farm.screen_signals import normalize
                # A manual entry supplies the selected difficulty. This client
                # clips Arden's long HUD title before the difficulty suffix.
                # Require the exact map and valid room; reject a visible mismatch.
                manual_arden=(dungeon=='阿登高地' and observed is None and
                              normalize(dungeon) in ''.join(normalize(t) for t in signals.get('texts',[])))
                if (observed==difficulty or manual_arden) and (signals.get('finished') or read_doors(conn.reader,sample['scene'],dungeon)):
                    report({'state':'entry_ready','detail':difficulty+('（沿用手动入场选择）' if manual_arden else '')});return 'ready'
                unconfirmed+=1
                if unconfirmed>=5:return 'wrong_dungeon'
                continue
            if sample and fresh_dungeon_room(signals,sample,None,read_doors(conn.reader,sample['scene'],dungeon),difficulty,dungeon,allow_hidden_difficulty=enter_sent):
                report({'state':'entry_ready'});return 'ready'
            if sample:
                unconfirmed+=1
                if unconfirmed>=5:return 'wrong_dungeon'
                continue
            if (selection_seen or enter_sent) and not signals['selection']:
                # Loading or a user-cancelled selection is not a town-move cue.
                control.stop.wait(.05)
                continue
            if signals['selection']:
                if enter_sent:continue
                selection_seen=True
                selected=bool(signals.get('target_selected'))
                if signals['dungeon_option'] and not selected:
                    normal_confirmations=0
                    # A second click on a selected card can enter immediately.
                    # Missing the tiny difficulty badge is not permission to
                    # click the same map again; wait for a stable observation.
                    if select_attempts:
                        unconfirmed+=1
                        if unconfirmed>=12:return 'difficulty_unconfirmed'
                        continue
                    report({'state':'selecting_dungeon'})
                    if keys.click(signals['dungeon_option'],hwnd,control.cancelled):select_attempts+=1
                    control.stop.wait(.8)
                elif selected and signals.get('difficulty')==difficulty.replace('级',''):
                    unconfirmed=0
                    normal_confirmations+=1
                    if normal_confirmations>=2:
                        report({'state':'entering_dungeon'})
                        if keys.key('enter',hwnd,control.cancelled):enter_sent=True
                elif selected and normal_steps<5:
                    unconfirmed=0
                    normal_confirmations=0
                    levels=['普通','冒险','勇士','王者','地狱']
                    current=signals.get('difficulty')
                    if current=='英雄':current='地狱'
                    if current not in levels:return 'difficulty_unconfirmed'
                    target=difficulty.replace('级','').replace('英雄','地狱')
                    direction='difficulty_right' if levels.index(current)<levels.index(target) else 'difficulty_left'
                    report({'state':'selecting_normal','detail':difficulty})
                    if keys.key(direction,hwnd,control.cancelled):normal_steps+=1
                    control.stop.wait(.6)
                elif selected:return 'difficulty_unconfirmed'
                continue
            if enter_sent:continue
            if dungeon=='阿登高地' and not allow_town_entry:
                return 'waiting_dungeon'
            reader=conn.reader
            base=reader.uint(reader.local_root) if reader else 0
            scene=reader.uint(base+0xb8) if base else None
            actor=reader.actor(base,0) if base and scene==0 else None
            if not actor or actor['name']!=profile['self_name']:
                report({'state':'waiting_coordinates'});continue
            if moves>=8:return 'entry_failed'
            report({'state':'entering_town'})
            direction='right'
            if dungeon=='阿登高地' and any(t in signals.get('map_title','') for t in ('悬空的海港','时空海港')):
                direction=alignment.direction(reader.process.xyz(reader.local_xyz))
            win.apply({direction},hwnd)
            try:
                until=time.monotonic()+.4
                while time.monotonic()<until and not control.cancelled() and win.foreground(hwnd):control.stop.wait(.02)
            finally:win.release()
            moves+=1
        return 'stopped'
    finally:win.release();conn.close();screen.close()
