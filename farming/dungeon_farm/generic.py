"""Manual-entry mode for ordinary combat rooms on the verified client."""
import copy

GENERIC='通用模式（手动进图）'


def boss_heading(route,doors):
    """Prefer an observed door toward the Boss, without inventing a corridor."""
    from dungeon_farm.minimap import STEPS
    if route.current is None or route.boss is None:return None
    x,y=route.current;bx,by=route.boss
    candidates=[d['direction'] for d in doors if d['direction'] in STEPS]
    if not candidates:return None
    return min(candidates,key=lambda d:abs(x+STEPS[d][0]-bx)+abs(y+STEPS[d][1]-by))


def combined_preset(presets):
    result={'monster_types':[], 'route_rules':[]}
    for field in ('apc_targets','friendly_apcs','friendly_monsters'):
        target=result[field]={}
        for name,preset in presets.items():
            if name==GENERIC:continue
            for kind,names in preset.get(field,{}).items():
                target.setdefault(kind,[])
                target[kind]=list(dict.fromkeys(target[kind]+copy.deepcopy(names)))
    result['friendly_apcs'].setdefault('0x16fe0e4',[])
    if '偉大的杜爾夫' not in result['friendly_apcs']['0x16fe0e4']:
        result['friendly_apcs']['0x16fe0e4'].append('偉大的杜爾夫')
    return result


class AllyGuess:
    """Generic mode attacks unlisted human-type objects. If such guesses are
    the only targets left and none of them dies for ``patience`` seconds,
    they are allies after all: stop targeting those names for this run."""
    def __init__(self,patience=25):
        self.patience=patience;self.friends=set();self.sig=None;self.since=0

    def filter(self,scene,enemies,guessed,now):
        """Return (enemies_to_target, names_newly_treated_as_allies)."""
        if not guessed:
            self.sig=None
            return tuple(enemies),()
        kept=tuple(e for e in enemies if guessed.get(e.identity) not in self.friends)
        if kept and all(e.identity in guessed for e in kept):
            sig=(scene,frozenset(e.identity for e in kept))
            if sig!=self.sig:
                self.sig=sig;self.since=now
            elif now-self.since>self.patience:
                names=tuple(sorted({guessed[e.identity] for e in kept}))
                self.friends.update(names);self.sig=None
                return (),names
        else:
            self.sig=None
        return kept,()


def room_ready(signals,sample,doors,old_scene=None):
    # A verified local actor with a non-town scene and real exit objects is
    # required. A title or a minimap-looking town panel alone is insufficient.
    return bool(sample and sample.get('scene') and sample['scene']!=old_scene and doors
                and not any(signals.get(k) for k in
                            ('selection','finished','retry','exhausted','dead','overlay','notice')))


def prepare(control,report,**unused):
    """Observe manual entry without sending movement, selection or attack keys."""
    import time
    from ctypes import wintypes as W
    from follow import Windows,C
    from coordinate_connection import CoordinateConnection
    from dungeon_farm.characters import selected_profile
    from dungeon_farm.combat_telemetry import connect_solo
    from dungeon_farm.screen_signals import ScreenSignals
    from dungeon_farm.route import read_doors
    win=Windows();screen=ScreenSignals(GENERIC)
    conn=CoordinateConnection(selected_profile(control.character),connector=connect_solo)
    win.u.GetWindowThreadProcessId.argtypes=[W.HWND,C.POINTER(W.DWORD)]
    confirmations=0;scene=None
    try:
        while not control.stop.is_set():
            hwnd=win.game()
            if control.paused.is_set() or not hwnd or not win.foreground(hwnd):
                report({'state':'paused' if control.paused.is_set() else 'waiting_foreground'})
                control.stop.wait(.1);continue
            pid=W.DWORD();win.u.GetWindowThreadProcessId(hwnd,C.byref(pid))
            sample=conn.sample(pid.value)
            if not sample:return 'waiting_dungeon'
            signals=screen.poll(win,hwnd,full=True)
            if not signals:control.stop.wait(.05);continue
            if signals.get('exhausted'):return 'fatigue_empty'
            doors=read_doors(conn.reader,sample['scene'],None)
            if not room_ready(signals,sample,doors):return 'waiting_dungeon'
            confirmations=confirmations+1 if scene==sample['scene'] else 1
            scene=sample['scene']
            if confirmations>=2:
                control.generic_title=signals.get('map_title','')
                report({'state':'entry_ready','detail':'通用接管：'+(control.generic_title or '已确认副本房间')})
                return 'ready'
        return 'stopped'
    finally:
        win.release();conn.close();screen.close()
