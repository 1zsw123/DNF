"""User-visible maintenance checks; same cancellable input path as farming."""
import json,time
from pathlib import Path
from follow import Windows
from dungeon_farm.cycle_inputs import CycleInputs
from dungeon_farm.screen_signals import ScreenSignals

def maintenance(control,report,action):
    if action=='entry':
        from dungeon_farm.town_entry import prepare
        try:result=prepare(control,report,allow_town_entry=True)
        except Exception as exc:
            result='error';report({'state':'error','detail':str(exc)})
        report({'state':'worker_ended','result':'entry_ready' if result=='ready' else result})
        return
    win=Windows();keys=CycleInputs(win);screen=None;result='stopped'
    try:
        while not control.stop.is_set():
            hwnd=win.game()
            if control.paused.is_set() or not win.foreground(hwnd):
                report({'state':'waiting_foreground'});control.stop.wait(.1);continue
            report({'state':action})
            if action=='inspect_inventory':
                from dungeon_farm.inventory import inspect_inventory
                screen=ScreenSignals()
                snapshot=inspect_inventory(win,keys,screen,hwnd,control)
                report({'state':'inventory_checked','detail':f"无色：{snapshot['cubes']} · 金币：{snapshot['gold']}（None 表示未读到）"})
                result='inventory_checked';return snapshot
            ok=keys.key('inventory',hwnd,control.cancelled) if action=='inventory' else keys.chord(action,hwnd,control.cancelled)
            if not ok:continue
            control.stop.wait(.8)
            screen=ScreenSignals();signals=screen.poll(win,hwnd,full=True)
            (Path(__file__).parent/'maintenance-check.json').write_text(json.dumps({'action':action,'time':time.time(),'input':keys.last_chord_state,'signals':signals},ensure_ascii=False,indent=2),encoding='utf8')
            result='maintenance_sent';break
    except Exception as exc:
        result='error';report({'state':'error','detail':str(exc)})
    finally:
        win.release()
        if screen:screen.close()
        report({'state':'worker_ended','result':result})
