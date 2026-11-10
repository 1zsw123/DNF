"""GUI-controlled single-dungeon worker; all input is released on exit."""
import json
import threading
import time
from pathlib import Path
from ctypes import wintypes as W
from dataclasses import replace

from follow import Windows, C
from coordinate_connection import CoordinateConnection
from dungeon_farm.combat_inputs import CombatInputs
from dungeon_farm.combat_telemetry import observe, connect_solo
from dungeon_farm.planner import FarmPlanner, Skill, Decision
from dungeon_farm.navigation import Navigator
from dungeon_farm.route import read_doors, onward_door, infer_entry, configured_door, OPPOSITE
from dungeon_farm.screen_signals import ScreenSignals
from dungeon_farm.waves import WaveTracker
from dungeon_farm.exploration import RoomExplorer
from dungeon_farm.berserker_rotation import make_planner
from dungeon_farm.resources import need_recovery
from dungeon_farm.background_signals import BackgroundSignals
from dungeon_farm.revival import Revival
from dungeon_farm.door_approach import DoorApproach

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'dungeon_farm'

class Control:
    def __init__(self):
        self.stop=threading.Event()
        self.paused=threading.Event()
        self.exit_choice=None
        self.dual_blades_active=True
        self.next_recovery=0
        self.inventory=None
        self.round_cube_upper=0
    def cancelled(self): return self.stop.is_set() or self.paused.is_set()

def run_round(control,dungeon,report,solo=True,limit=1800):
    control.round_cube_upper=0
    preset=json.loads((DATA/'presets.json').read_text(encoding='utf-8'))[dungeon]
    allowed={int(v,16) for v in preset['monster_types']}
    apcs={int(v,16):names for v,names in preset.get('apc_targets',{}).items()}
    friends={int(v,16):names for v,names in preset.get('friendly_apcs',{}).items()}
    summons={int(v,16):names for v,names in preset.get('friendly_monsters',{}).items()}
    profile=json.loads((ROOT/'coordinate-session.json').read_text(encoding='utf-8'))
    profile.update(self_name='上头狂战',leader_name='上头召唤师',
                   role_types={'上头狂战':0x016F972C,'上头召唤师':0x016FC11C})
    win=Windows()
    win.u.GetWindowThreadProcessId.argtypes=[W.HWND,C.POINTER(W.DWORD)]
    win.u.GetWindowThreadProcessId.restype=W.DWORD
    connection=CoordinateConnection(profile,connector=connect_solo) if solo else CoordinateConnection(profile)
    keys=CombatInputs(win,all_skills=True);planner=make_planner(control.dual_blades_active)
    nav=Navigator();screen=None;room=None;rooms=0;facing=None;waves=WaveTracker();explorer=RoomExplorer()
    doors=[];next_exit=None;exiting=None;destination=None;last_status=0;door_approach=DoorApproach()
    started=time.monotonic();manual_until=0;screen_checks=0;outcome='stopped'
    last_sample=None;last_obs=None;battle_started=None;resources=None;resources_time=0
    lost_since=None;screen_epoch=time.monotonic();last_screen=0;revival=Revival()
    log=(DATA/'gui-run.jsonl').open('w',encoding='utf-8')
    def emit(state,force=False,**more):
        nonlocal last_status
        now=time.monotonic()
        if force or now-last_status>.25:
            value={'state':state,'rooms':rooms,'elapsed':round(now-started,1),
                   'enemies':len(last_obs.enemies) if last_obs else None,
                   'collisions':nav.collisions,'wave':waves.number,**more}
            report(value);last_status=now
    try:
        emit('initializing',True)
        screen=BackgroundSignals(win,control,factory=lambda:ScreenSignals(dungeon))
        win.u.GetAsyncKeyState(0x1b);win.u.GetAsyncKeyState(0x0d)
        while not control.stop.is_set() and (battle_started is None or time.monotonic()-battle_started<limit):
            now=time.monotonic()
            if control.paused.is_set():
                screen_epoch=now
                win.release();nav.pause();waves.suspend()
                emit('paused');control.stop.wait(.05);continue
            hwnd=win.game()
            if not hwnd or not win.foreground(hwnd):
                screen_epoch=now
                win.release();nav.pause();waves.suspend()
                emit('waiting_game' if not hwnd else 'waiting_foreground')
                control.stop.wait(.08);continue
            if any(win.u.GetAsyncKeyState(vk)&0x8000 for vk in (0x1b,0x0d)):
                control.paused.set();win.release();continue
            if win.manual_arrows(): manual_until=now+.6
            if now<manual_until:
                win.release();nav.pause();emit('manual');control.stop.wait(.04);continue
            screen_value=screen.read(after=screen_epoch)
            if screen_value and screen_value[0]>last_screen:
                last_screen,_,signals=screen_value
                if signals and not signals.get('overlay'):
                    resources=signals;resources_time=last_screen
                if revival.observe(bool(signals.get('dead'))):
                    planner.toggle_active.discard('h');planner.last_used.pop('h',None)
                    control.dual_blades_active=False;planner.casting_until=0
                    emit('revived',True)
                if signals and signals['finished']:
                    outcome='finished';emit('finished',True);break
            revive_action=revival.action(time.monotonic())
            if revive_action:
                win.release();nav.pause();emit(revive_action)
                if revive_action=='revive_failed':outcome='revive_failed';break
                if revive_action=='revive' and keys.tap('x',hwnd,control.cancelled):
                    revival.sent(time.monotonic())
                    log.write(json.dumps({'time':time.time(),'state':'revive','tap':'x'})+'\n');log.flush()
                control.stop.wait(.05);continue
            if control.cancelled(): continue
            pid=W.DWORD();win.u.GetWindowThreadProcessId(hwnd,C.byref(pid))
            value=observe(connection,pid.value,facing,allowed_types=allowed,allowed_apcs=apcs,friendly_apcs=friends,friendly_monsters=summons)
            if value is None:
                if last_sample and connection.reader:
                    reader=connection.reader;base=reader.uint(reader.local_root)
                    if base and reader.uint(base+0xb8)==0:
                        lost_since=lost_since or time.monotonic()
                        if time.monotonic()-lost_since>5:
                            outcome='returned_town';emit('returned_town',True);break
                    else:lost_since=None
                win.release();nav.pause();waves.suspend();emit('waiting_coordinates',detail=connection.status)
                control.stop.wait(.08);continue
            obs,sample=value;last_sample=sample;last_obs=obs
            lost_since=None
            if battle_started is None:battle_started=time.monotonic()
            if sample['unverified_monsters']:
                win.release();outcome='unknown_monsters'
                (DATA/'unverified-monsters.json').write_text(json.dumps(sample['unverified_details'],ensure_ascii=False,indent=2),encoding='utf-8')
                names=list(dict.fromkeys(x.get('name') or '未命名角色' for x in sample['unverified_details']))
                emit('unknown_monsters',True,detail='、'.join(names));break
            if obs.scene!=room:
                win.release()
                resources=None;resources_time=0;screen_epoch=time.monotonic()
                new_doors=read_doors(connection.reader,sample['scene'])
                entry=OPPOSITE[exiting['direction']] if exiting else infer_entry(new_doors,obs.position)
                if explorer.pending:entry=OPPOSITE[explorer.pending[1]]
                # Starting/restarting in the middle of a room does not prove
                # the nearest door was our entrance. Only transitions prove it.
                explorer.enter(obs.scene,entry if explorer.current is not None else None)
                next_exit=None if dungeon in ('根特东门','追击歼灭战') else onward_door(new_doors,entry)
                room=obs.scene;rooms+=1;doors=new_doors;exiting=None;destination=None
                door_approach=DoorApproach()
                waves.reset();facing=None;nav.reset(room)
                emit('room_entered',True,doors=[d['direction'] for d in doors])
            if obs.enemies and time.monotonic()>=control.next_recovery and need_recovery(resources,time.monotonic()-resources_time):
                win.release();nav.pause();emit('recovering',True)
                if keys.tap('3',hwnd,control.cancelled):
                    control.next_recovery=time.monotonic()+10.5
                    log.write(json.dumps({'time':time.time(),'scene':room,'position':obs.position,'enemies':len(obs.enemies),'state':'recovering','tap':'3','hp_fill':resources['hp_fill'],'mp_fill':resources['mp_fill'],'move':[]})+'\n');log.flush()
                continue
            exit_ready,new_wave=waves.update(bool(obs.enemies),now)
            if obs.enemies:
                if new_wave:
                    nav.reset(room)
                    emit('new_wave',True)
                exiting=None;destination=None
                decision=planner.step(obs,time.monotonic())
            else:
                if not exit_ready:
                    decision=Decision('confirm_clear')
                else:
                    if next_exit is None:
                        # Door objects may still be initializing on scene entry.
                        doors=read_doors(connection.reader,sample['scene'])
                        preferred=configured_door(doors,entry,preset.get('route_rules',[]))
                        priority=preferred['direction'] if preferred else ('right' if dungeon=='追击歼灭战' else None)
                        next_exit=explorer.choose(doors,priority) if dungeon in ('根特东门','追击歼灭战') else onward_door(doors,entry)
                    if control.exit_choice:
                        matches=[d for d in doors if d['direction']==control.exit_choice]
                        control.exit_choice=None
                        if len(matches)==1: next_exit=matches[0];destination=None
                    if next_exit is None:
                        win.release();nav.pause()
                        emit('choose_exit',doors=[d['direction'] for d in doors])
                        control.stop.wait(.05);continue
                    exiting=next_exit
                    explorer.departing(exiting['direction'])
                    destination=door_approach.target(exiting,obs.position)
                    decision=Decision('exit',destination=destination)
            if decision.destination is not None:
                move=nav.steer(room,obs.position,decision.destination,time.monotonic())
                decision=replace(decision,move=move)
                if nav.no_path:
                    (DATA/'navigation-failure.json').write_text(json.dumps({'time':time.time(),'scene':room,'position':obs.position,'destination':decision.destination,'reason':nav.failure_reason,'blocked':sorted(nav.blocked),'contacts':sorted(nav.contacts),'free':sorted(nav.free),'enemies':[{'x':e.x,'y':e.y,'id':e.identity} for e in obs.enemies]},ensure_ascii=False,indent=2),encoding='utf8')
                    win.release();control.paused.set();emit('no_path',True,detail=nav.failure_reason or '未找到可通行路线');continue
            else: nav.pause()
            emit(decision.state,detail=decision.reason,doors=[d['direction'] for d in doors])
            log.write(json.dumps({'time':time.time(),'scene':room,'position':obs.position,
                      'enemies':len(obs.enemies),'state':decision.state,'tap':decision.tap,
                      'wave':waves.number,'doors':doors,
                      'move':sorted(decision.move),'collisions':nav.collisions},ensure_ascii=False)+'\n')
            log.flush()
            if control.cancelled(): win.release();continue
            if decision.tap:
                success=keys.tap(decision.tap,hwnd,control.cancelled)
                planner.acknowledge(decision,time.monotonic(),success)
                if success and decision.tap=='h':control.dual_blades_active=True
                if success and decision.action!='release':
                    skill=next((s for s in planner.skills if s.key==decision.tap),None)
                    if skill:control.round_cube_upper+=2*(skill.cube_cost or 0)
            else:
                running=decision.state in ('approach','exit') and decision.destination is not None and abs(decision.destination[0]-obs.position[0])>180
                win.apply(set(decision.move),hwnd,run=bool(running))
                if 'left' in decision.move:facing='left'
                elif 'right' in decision.move:facing='right'
            control.stop.wait(.02)
        else:
            outcome='stopped' if control.stop.is_set() else 'time_limit'
    except Exception as exc:
        import traceback
        (DATA/'gui-error.log').write_text(traceback.format_exc(),encoding='utf-8')
        outcome='error';emit('error',True,detail=str(exc))
    finally:
        win.release();connection.close();log.close()
        if screen is not None:screen.close()
        (DATA/'gui-status.json').write_text(json.dumps({'result':outcome,'finished':time.time(),
            'dungeon':dungeon,'rooms':rooms,'elapsed':time.monotonic()-started,
            'unverified':last_sample.get('unverified_details',[]) if last_sample else []},ensure_ascii=False,indent=2),encoding='utf-8')
    return {'result':outcome,'scene':last_sample['scene'] if last_sample else None,'profile':profile}

def run(control,dungeon,report,solo=True,limit=1800,repeat=False,difficulty='普通级',allow_town_entry=False,max_runs=None):
    from dungeon_farm.cycle import replay
    from dungeon_farm.town_entry import prepare
    completed=0;outcome='stopped'
    def emit(update):
        report({'completed':completed,'repeat':repeat,**update})
        if update['state'] in ('initializing','waiting_rewards','disassemble','sell','repair','retrying','reentered','round_finished'):
            (DATA/'cycle-status.json').write_text(json.dumps({'result':'running','phase':update['state'],
                'completed':completed,'repeat':repeat,'updated':time.time()},ensure_ascii=False,indent=2),encoding='utf-8')
    try:
        if difficulty not in ('普通级','冒险级'):
            raise ValueError('当前仅开放普通、冒险级；按用户要求不自动挑战高难度')
        if repeat and (dungeon not in ('根特东门','追击歼灭战') or not solo):
            raise ValueError('循环模式仅支持已适配的根特单人副本')
        if allow_town_entry:
            from dungeon_farm.utilities import maintenance
            control.inventory=maintenance(control,lambda u:emit(u) if u['state']!='worker_ended' else None,'inspect_inventory')
        while not control.stop.is_set():
            before=control.inventory;round_start=time.time()
            if dungeon in ('根特东门','追击歼灭战'):
                outcome=prepare(control,emit,allow_town_entry=allow_town_entry,dungeon=dungeon,difficulty=difficulty)
                allow_town_entry=False
                if outcome!='ready':break
            result=run_round(control,dungeon,emit,solo,limit)
            outcome=result['result']
            if outcome!='finished':break
            completed+=1
            again=repeat and (max_runs is None or completed<max_runs)
            emit({'state':'round_finished'})
            outcome=replay(control,emit,result['scene'],result['profile'],dungeon=dungeon,reenter=again)
            after=control.inventory
            net=after['gold']-before['gold'] if before and after and before.get('gold') is not None and after.get('gold') is not None else None
            record={'time':time.time(),'dungeon':dungeon,'difficulty':difficulty,'elapsed_with_maintenance':time.time()-round_start,'gold_before':before.get('gold') if before else None,'gold_after':after.get('gold') if after else None,'net_gold':net,'result':outcome,'cube_consumption_upper_estimate':control.round_cube_upper}
            with (DATA/'farming-results.jsonl').open('a',encoding='utf8') as f:f.write(json.dumps(record,ensure_ascii=False)+'\n')
            emit({'state':'round_statistics','net_gold':net,'seconds':record['elapsed_with_maintenance']})
            archive=DATA/'runs';archive.mkdir(exist_ok=True)
            import shutil
            if (DATA/'gui-run.jsonl').exists():shutil.copyfile(DATA/'gui-run.jsonl',archive/f'{int(round_start)}.jsonl')
            if not again:break
            if outcome!='reentered':break
            control.exit_choice=None
        else:outcome='stopped'
    except Exception as exc:
        import traceback
        (DATA/'gui-error.log').write_text(traceback.format_exc(),encoding='utf-8')
        outcome='error';emit({'state':'error','detail':str(exc)})
    finally:
        (DATA/'cycle-status.json').write_text(json.dumps({'result':outcome,'completed':completed,'repeat':repeat,'finished':time.time()},ensure_ascii=False,indent=2),encoding='utf-8')
        emit({'state':'worker_ended','result':outcome})
