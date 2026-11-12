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
from dungeon_farm.planner import FarmPlanner, Skill, Decision,attack_still_valid
from dungeon_farm.navigation import Navigator
from dungeon_farm.route import read_doors, onward_door, infer_entry, configured_door, OPPOSITE
from dungeon_farm.screen_signals import ScreenSignals
from dungeon_farm.waves import WaveTracker
from dungeon_farm.exploration import RoomExplorer
from dungeon_farm.berserker_rotation import make_planner
from dungeon_farm.resources import need_recovery, RecoveryBudget
from dungeon_farm.background_signals import BackgroundSignals
from dungeon_farm.revival import Revival
from dungeon_farm.door_approach import DoorApproach
from dungeon_farm.characters import selected_profile, character_planner
from dungeon_farm.minimap import MinimapRoute,MinimapSignals

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'dungeon_farm'
SUPPORTED_DUNGEONS=('根特东门','追击歼灭战','阿登高地')

class Control:
    def __init__(self):
        self.stop=threading.Event()
        self.paused=threading.Event()
        self.exit_choice=None
        self.dual_blades_active=True
        self.next_recovery=0
        self.inventory=None
        self.round_cube_upper=0
        self.round_start_cubes=None
        self.character=None
        self.auto_potion=True
        self.team_config={'mode':'solo'}
        self.team_link=None
        self.team_round=None
        self.skill_last_used={}
    def cancelled(self): return self.stop.is_set() or self.paused.is_set()

def run_round(control,dungeon,report,solo=True,limit=1800):
    control.round_cube_upper=0
    recovery_budget=RecoveryBudget(limit=1)
    presets=json.loads((DATA/'presets.json').read_text(encoding='utf-8'))
    team_mode=control.team_config.get('mode','solo')
    from dungeon_farm.team import follower_scene_preset
    actual_dungeon=None if team_mode=='follower' else dungeon
    preset=follower_scene_preset(presets,'')[1] if team_mode=='follower' else presets[dungeon]
    allowed={int(v,16) for v in preset['monster_types']}
    apcs={int(v,16):names for v,names in preset.get('apc_targets',{}).items()}
    friends={int(v,16):names for v,names in preset.get('friendly_apcs',{}).items()}
    summons={int(v,16):names for v,names in preset.get('friendly_monsters',{}).items()}
    profile=selected_profile(control.character)
    potion_key=(control.character or {}).get('potion_key','3')
    team_mode=control.team_config.get('mode','solo')
    link=control.team_link
    from dungeon_farm.team import connect_party,gate_ready,follower_decision,follower_scene_preset,follower_link_ready
    if team_mode!='solo':profile['party_name']=control.team_config['partner']
    win=Windows()
    win.u.GetWindowThreadProcessId.argtypes=[W.HWND,C.POINTER(W.DWORD)]
    win.u.GetWindowThreadProcessId.restype=W.DWORD
    connection=CoordinateConnection(profile,connector=connect_party if team_mode!='solo' else connect_solo) if solo else CoordinateConnection(profile)
    keys=CombatInputs(win,all_skills=True);planner=character_planner(control.character,control.dual_blades_active)
    planner.last_used.update(control.skill_last_used)
    nav=Navigator(entry_grace=3);screen=None;room=None;rooms=0;facing=None;waves=WaveTracker();explorer=RoomExplorer()
    doors=[];next_exit=None;exiting=None;destination=None;last_status=0;door_approach=DoorApproach()
    started=time.monotonic();manual_until=0;screen_checks=0;outcome='stopped'
    last_sample=None;last_obs=None;battle_started=None;resources=None;resources_time=0
    minimap_route=MinimapRoute();minimap=None;minimap_time=0
    map_screen=None;map_signals={}
    lost_since=None;screen_epoch=time.monotonic();last_screen=0;revival=Revival()
    ignored_objects=set();was_retreat=False;resource_overlay=False
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
        if dungeon=='阿登高地' and team_mode!='follower':
            map_screen=BackgroundSignals(win,control,factory=lambda:MinimapSignals(dungeon))
        win.u.GetAsyncKeyState(0x1b);win.u.GetAsyncKeyState(0x0d)
        while not control.stop.is_set() and (battle_started is None or time.monotonic()-battle_started<limit):
            now=time.monotonic()
            if control.paused.is_set():
                revival.suspend(now)
                if link:link.update(active=False)
                screen_epoch=now
                win.release();nav.pause();waves.suspend()
                emit('paused');control.stop.wait(.05);continue
            hwnd=win.game()
            if not hwnd or not win.foreground(hwnd):
                revival.suspend(now)
                if link:link.update(active=False)
                screen_epoch=now
                win.release();nav.pause();waves.suspend()
                emit('waiting_game' if not hwnd else 'waiting_foreground')
                control.stop.wait(.08);continue
            if any(win.u.GetAsyncKeyState(vk)&0x8000 for vk in (0x1b,0x0d)):
                control.paused.set();win.release();continue
            if win.manual_arrows(): manual_until=now+.6
            if now<manual_until:
                revival.suspend(now)
                if link:link.update(active=False)
                win.release();nav.pause();emit('manual');control.stop.wait(.04);continue
            if link:link.update(active=True,phase='combat')
            screen_value=screen.read(after=screen_epoch)
            if screen_value and screen_value[0]>last_screen:
                last_screen,_,signals=screen_value
                resource_overlay=bool(signals.get('overlay'))
                if team_mode=='follower' and signals.get('map_title'):
                    detected,current=follower_scene_preset(presets,signals['map_title'])
                    if detected!=actual_dungeon:
                        actual_dungeon=detected
                        allowed={int(v,16) for v in current.get('monster_types',[])}
                        apcs={int(v,16):names for v,names in current.get('apc_targets',{}).items()}
                        friends={int(v,16):names for v,names in current.get('friendly_apcs',{}).items()}
                        summons={int(v,16):names for v,names in current.get('friendly_monsters',{}).items()}
                        waves.suspend()
                if signals and not signals.get('overlay'):
                    resources=signals;resources_time=last_screen
                if revival.observe(bool(signals.get('dead')),last_screen):
                    planner.revived()
                    planner.toggle_active.discard('h');planner.last_used.pop('h',None)
                    control.dual_blades_active=False;planner.casting_until=0
                    emit('revived',True)
                if signals and signals['finished']:
                    outcome='finished';emit('finished',True);break
            revive_action=revival.action(time.monotonic())
            if revive_action:
                win.release();nav.pause();emit(revive_action)
                if revive_action in ('revive_failed','revive_unconfirmed'):
                    outcome=revive_action;break
                if revive_action=='revive' and keys.tap('x',hwnd,control.cancelled):
                    revival.sent(time.monotonic())
                    log.write(json.dumps({'time':time.time(),'state':'revive','tap':'x'})+'\n');log.flush()
                control.stop.wait(.05);continue
            if control.cancelled(): continue
            map_value=map_screen.read(after=screen_epoch) if map_screen else None
            if map_value and map_value[0]>minimap_time:
                minimap_time,_,map_signals=map_value
                minimap=map_signals.get('minimap')
                # Orb colors are cheap; do not wait for full-frame text OCR
                # before deciding whether a potion or mana reserve is needed.
                if not resource_overlay and map_signals.get('resources'):
                    resources=map_signals['resources'];resources_time=minimap_time
            pid=W.DWORD();win.u.GetWindowThreadProcessId(hwnd,C.byref(pid))
            value=observe(connection,pid.value,facing,allowed_types=allowed,allowed_apcs=apcs,friendly_apcs=friends,friendly_monsters=summons,ignore_unknown=team_mode!='follower')
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
            previous_obs=last_obs
            obs,sample=value;last_sample=sample;last_obs=obs
            if '偉大的杜爾夫' in sample.get('friendly_apcs',()):
                planner.entry_applied.add('4')
            lost_since=None
            if battle_started is None:battle_started=time.monotonic()
            if sample['unverified_monsters'] and team_mode!='follower':
                # User-selected policy: skip unclassified objects, keep the
                # known targets usable, and record each type/name once/room.
                unseen=[x for x in sample['unverified_details']
                        if (obs.scene,x['type'],x.get('name','')) not in ignored_objects]
                if unseen:
                    ignored_objects.update((obs.scene,x['type'],x.get('name','')) for x in unseen)
                    (DATA/'unverified-monsters.json').write_text(json.dumps(sample['unverified_details'],ensure_ascii=False,indent=2),encoding='utf-8')
                    log.write(json.dumps({'time':time.time(),'scene':obs.scene,'state':'unknown_ignored','objects':unseen},ensure_ascii=False)+'\n');log.flush()
                    names=list(dict.fromkeys(x.get('name') or '未命名角色' for x in unseen))
                    emit('unknown_ignored',True,detail='、'.join(names))
            if obs.scene!=room:
                win.release()
                resources=None;resources_time=0;screen_epoch=time.monotonic()
                minimap=None;minimap_time=0
                new_doors=read_doors(connection.reader,sample['scene'],dungeon)
                if previous_obs and doors and explorer.pending:
                    import math
                    crossed=min(doors,key=lambda d:math.dist(previous_obs.position,(d['x'],d['y'])))
                    if math.dist(previous_obs.position,(crossed['x'],crossed['y']))<125:
                        explorer.pending=(explorer.pending[0],crossed['direction'])
                entry=OPPOSITE[exiting['direction']] if exiting else infer_entry(new_doors,obs.position)
                if explorer.pending:entry=OPPOSITE[explorer.pending[1]]
                minimap_route.enter(obs.scene,OPPOSITE.get(entry) if room is not None else None)
                # Starting/restarting in the middle of a room does not prove
                # the nearest door was our entrance. Only transitions prove it.
                explorer.enter(obs.scene,entry if explorer.current is not None else None)
                next_exit=None if dungeon in SUPPORTED_DUNGEONS else onward_door(new_doors,entry)
                room=obs.scene;rooms+=1;doors=new_doors;exiting=None;destination=None
                door_approach=DoorApproach()
                waves.reset();facing=None;nav.reset(room)
                emit('room_entered',True,doors=[d['direction'] for d in doors])
            if dungeon=='阿登高地' and team_mode!='follower':
                reading=minimap if time.monotonic()-minimap_time<3 else None
                planned=minimap_route.choose(room,doors,reading,minimap_time,validate_doors=False)
                if planned!=next_exit:
                    next_exit=planned
                    if planned:emit('boss_route',True,detail='已记住本房出口：'+planned['direction'],path=minimap_route.path)
            obs=replace(obs,boss_room=(dungeon=='阿登高地' and team_mode!='follower'
                                     and minimap_route.status=='at_boss'),
                        mp_fill=resources.get('mp_fill') if resources and time.monotonic()-resources_time<2 else None)
            if control.auto_potion and time.monotonic()>=control.next_recovery and recovery_budget.available(resources,time.monotonic()-resources_time):
                win.release();nav.pause();emit('recovering',True)
                if keys.tap(potion_key,hwnd,control.cancelled):
                    recovery_budget.sent()
                    control.next_recovery=time.monotonic()+10.5
                    log.write(json.dumps({'time':time.time(),'scene':room,'position':obs.position,'enemies':len(obs.enemies),'state':'recovering','tap':potion_key,'hp_fill':resources['hp_fill'],'mp_fill':resources['mp_fill'],'move':[]})+'\n');log.flush()
                continue
            # Unclassified actors cannot prove a clear room on a follower's
            # arbitrary dungeon. A new wave immediately revokes rendezvous.
            has_enemies=bool(obs.enemies) or (team_mode=='follower' and bool(sample['unverified_monsters']))
            exit_ready,new_wave=waves.update(has_enemies,now)
            remote=link.remote() if link else None
            linked=bool(remote and remote['active'] and remote['phase']=='combat')
            partner=sample.get('party')
            if team_mode=='follower':
                linked=follower_link_ready(remote,partner)
                if linked:control.team_round=[remote['session'],remote['round']]
                # Refresh exit geometry while waiting: doors may initialize
                # only after combat. Do not reuse entry-time door snapshots.
                doors=read_doors(connection.reader,sample['scene'],None)
                decision=follower_decision(obs.position,partner,linked,room_clear=exit_ready,doors=doors,door_approach=door_approach)
                if decision.destination is None:
                    # Combat, lost peers or ambiguous exits revoke pending
                    # portal pushes; a later clear must align afresh.
                    door_approach=DoorApproach()
                if not partner:
                    decision=replace(decision,reason='同房间未找到指定大号：'+control.team_config['partner'])
                elif not linked:
                    reason=('双机连接未就绪：'+link.error if link and link.error else
                            ('大号当前阶段：'+str(remote.get('phase')) if remote else '尚未收到大号有效心跳'))
                    decision=replace(decision,reason=reason)
                if decision.state=='waiting_room_clear':
                    names=list(dict.fromkeys(v.get('name') or v.get('type','未知对象') for v in sample['unverified_details']))
                    reason=('尚有未分类对象：'+'、'.join(names)) if names else ('尚有怪物，原地等清场' if obs.enemies else '怪物已清，等待3.5秒补刷确认')
                    decision=replace(decision,reason=reason)
            elif planner.needs_entry_buff:
                decision=planner.step(obs,time.monotonic())
            elif getattr(planner,'needs_maintenance',getattr(planner,'needs_summon_maintenance',lambda t:False))(time.monotonic()):
                # Clearing/door navigation normally bypasses the combat
                # planner. Let verified G transforms keep the summon alive.
                decision=planner.step(obs,time.monotonic())
            elif obs.enemies:
                if new_wave:
                    nav.reset(room)
                    emit('new_wave',True)
                exiting=None;destination=None
                decision=planner.step(obs,time.monotonic())
            else:
                planner.cancel_attack()
                if not exit_ready:
                    decision=Decision('confirm_clear')
                else:
                    if dungeon=='阿登高地':
                        doors=read_doors(connection.reader,sample['scene'],dungeon)
                        next_exit=minimap_route.choose(room,doors)
                    if next_exit is None:
                        # Door objects may still be initializing on scene entry.
                        doors=read_doors(connection.reader,sample['scene'],dungeon)
                        if dungeon=='阿登高地':
                            reading=minimap if time.monotonic()-minimap_time<3 else None
                            next_exit=minimap_route.choose(room,doors,reading,minimap_time)
                            if next_exit:
                                emit('boss_route',True,detail='小地图路线：'+next_exit['direction'],path=minimap_route.path)
                        else:
                            preferred=configured_door(doors,entry,preset.get('route_rules',[]))
                            priority=preferred['direction'] if preferred else ('right' if dungeon=='追击歼灭战' else None)
                            next_exit=explorer.choose(doors,priority) if dungeon in SUPPORTED_DUNGEONS else onward_door(doors,entry)
                    if control.exit_choice:
                        matches=[d for d in doors if d['direction']==control.exit_choice]
                        control.exit_choice=None
                        if len(matches)==1: next_exit=matches[0];destination=None
                    if next_exit is None:
                        win.release();nav.pause()
                        log.write(json.dumps({'time':time.time(),'scene':room,'position':obs.position,'enemies':len(obs.enemies),'state':'waiting_minimap','minimap':minimap,'map_diagnostic':map_signals.get('diagnostic'),'map_age':time.monotonic()-minimap_time,'confirmations':minimap_route.confirmations,'remembered_route':minimap_route.path},ensure_ascii=False)+'\n');log.flush()
                        if dungeon=='阿登高地' and minimap_route.status!='at_boss' and waves.confirmation_timed_out(now):
                            control.paused.set()
                            emit('minimap_timeout',True,detail='清场确认已达10秒，小地图位置或连线仍未确认；已暂停')
                            continue
                        if dungeon=='阿登高地':emit('waiting_boss_result' if minimap_route.status=='at_boss' else 'waiting_minimap',detail=minimap_route.status,doors=[d['direction'] for d in doors])
                        else:emit('choose_exit',doors=[d['direction'] for d in doors])
                        control.stop.wait(.05);continue
                    exiting=next_exit
                    if team_mode=='leader' and not gate_ready(obs.position,partner,next_exit,linked):
                        win.release();nav.pause();emit('waiting_partner',detail='清场后等待小号靠近，再一起过门')
                        control.stop.wait(.05);continue
                    explorer.departing(exiting['direction'])
                    destination=door_approach.target(exiting,obs.position,doors)
                    decision=Decision('exit',destination=destination)
            if decision.destination is not None:
                retreat_options=({'avoid':[(e.x,e.y) for e in obs.enemies if e.alive],
                                  'floor_bounds':getattr(planner,'floor_bounds',None),'urgent':True}
                                 if decision.action=='retreat' else {})
                portal_move=door_approach.portal_push(obs.position,decision.destination) if decision.state=='exit' else None
                if portal_move is not None:
                    # The trigger extends beyond the walkable edge. Learning
                    # that edge as terrain sends A* around the whole room.
                    nav.pause();move=portal_move
                else:move=nav.steer(room,obs.position,decision.destination,time.monotonic(),**retreat_options)
                decision=replace(decision,move=move)
                if portal_move is None and nav.no_path:
                    (DATA/'navigation-failure.json').write_text(json.dumps({'time':time.time(),'scene':room,'position':obs.position,'destination':decision.destination,'reason':nav.failure_reason,'blocked':sorted(nav.blocked),'contacts':sorted(nav.contacts),'free':sorted(nav.free),'enemies':[{'x':e.x,'y':e.y,'id':e.identity} for e in obs.enemies]},ensure_ascii=False,indent=2),encoding='utf8')
                    win.release();control.paused.set();emit('no_path',True,detail=nav.failure_reason or '未找到可通行路线');continue
            else: nav.pause()
            emit(decision.state,detail=decision.reason,doors=[d['direction'] for d in doors])
            log.write(json.dumps({'time':time.time(),'scene':room,'position':obs.position,
                      'enemies':len(obs.enemies),'unverified':len(sample['unverified_monsters']),
                      'state':decision.state,'reason':decision.reason,'tap':decision.tap,
                      'actual_dungeon':actual_dungeon,'peer_phase':remote.get('phase') if remote else None,
                      'peer_active':remote.get('active') if remote else None,
                      'wave':waves.number,'doors':doors,'boss_room':obs.boss_room,'g_confirmed':obs.g_confirmed,'mp_fill':obs.mp_fill,
                      'minimap':minimap,'destination':decision.destination,
                      'remembered_route':minimap_route.path,'planned_exit':next_exit['direction'] if next_exit else None,
                      'move':sorted(decision.move),'collisions':nav.collisions},ensure_ascii=False)+'\n')
            log.flush()
            if control.cancelled(): win.release();continue
            if decision.tap:
                was_retreat=False
                skill=next((s for s in planner.skills if s.key==decision.tap),None)
                if decision.action not in ('entry_buff','entry_helper'):
                    fresh=observe(connection,pid.value,facing,allowed_types=allowed,allowed_apcs=apcs,friendly_apcs=friends,friendly_monsters=summons,ignore_unknown=team_mode!='follower')
                    if fresh is None or not attack_still_valid(decision,fresh[0],room,skill,planner.attack_range):
                        planner.cancel_attack();win.release();continue
                success=keys.cast(skill,hwnd,control.cancelled) if skill else keys.tap(decision.tap,hwnd,control.cancelled)
                planner.acknowledge(decision,time.monotonic(),success)
                if success and skill:
                    log.write(json.dumps({'time':time.time(),'scene':room,'position':obs.position,'enemies':len(obs.enemies),'state':'skill_cast','tap':skill.key,'skill':skill.name or skill.key,'cooldown':skill.cooldown,'action':decision.action},ensure_ascii=False)+'\n');log.flush()
                if success and decision.action=='awakening_enter':
                    # This client's explicit immediate-fire sequence: do not
                    # wait for another coordinate sample or animation timer.
                    fire=planner.immediate_awakening_fire()
                    fired=keys.tap('c',hwnd,control.cancelled)
                    planner.acknowledge(fire,time.monotonic(),fired)
                    log.write(json.dumps({'time':time.time(),'scene':room,'state':'awakening_fire_input','tap':'c','sent':fired,'immediate':True})+'\n');log.flush()
                if decision.action=='awakening_fire':
                    log.write(json.dumps({'time':time.time(),'scene':room,'state':'awakening_fire_input','tap':'c','sent':success})+'\n');log.flush()
                if success and decision.tap=='h':control.dual_blades_active=True
                if success and decision.action!='release':
                    skill=next((s for s in planner.skills if s.key==decision.tap),None)
                    if skill:control.round_cube_upper+=2*(skill.cube_cost or 0)
            else:
                running=decision.state in ('approach','exit','following') and decision.destination is not None and abs(decision.destination[0]-obs.position[0])>(40 if decision.action=='retreat' else 180)
                retreat_sprint=decision.action=='retreat' and running
                if retreat_sprint and not was_retreat:win.release()
                win.apply(set(decision.move),hwnd,run=bool(running))
                was_retreat=retreat_sprint
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
        control.skill_last_used=dict(planner.last_used)
        win.release();connection.close();log.close()
        if screen is not None:screen.close()
        if map_screen is not None:map_screen.close()
        (DATA/'gui-status.json').write_text(json.dumps({'result':outcome,'finished':time.time(),
            'dungeon':dungeon,'rooms':rooms,'elapsed':time.monotonic()-started,
            'unverified':last_sample.get('unverified_details',[]) if last_sample else []},ensure_ascii=False,indent=2),encoding='utf-8')
    return {'result':outcome,'scene':last_sample['scene'] if last_sample else None,'profile':profile}

def run(control,dungeon,report,solo=True,limit=1800,repeat=False,difficulty='普通级',allow_town_entry=False,max_runs=None):
    from dungeon_farm.cycle import replay
    from dungeon_farm.town_entry import prepare
    completed=0;outcome='stopped';control.difficulty=difficulty
    def emit(update):
        report({'completed':completed,'repeat':repeat,**update})
        if update['state'] in ('initializing','waiting_rewards','disassemble','sell','repair','retrying','reentered','round_finished'):
            (DATA/'cycle-status.json').write_text(json.dumps({'result':'running','phase':update['state'],
                'completed':completed,'repeat':repeat,'updated':time.time()},ensure_ascii=False,indent=2),encoding='utf-8')
    try:
        if difficulty not in ('普通级','冒险级','勇士级'):
            raise ValueError('当前开放普通、冒险、勇士级；不自动提高所选难度')
        if repeat and (dungeon not in SUPPORTED_DUNGEONS or not solo):
            raise ValueError('循环模式仅支持已配置的单人副本')
        if control.character:
            # Verify identity before inventory/maintenance can send any input.
            from dungeon_farm.characters import discover_current
            current=discover_current()
            if any(current[key]!=control.character[key] for key in ('name','role_type')):
                outcome='wrong_character'
                emit({'state':outcome,'detail':f"游戏：{current['name']}；所选：{control.character['name']}。请读取当前角色后再开始。"})
                return
        team_mode=control.team_config.get('mode','solo')
        if team_mode!='solo':
            from dungeon_farm.team_link import TeamLink
            if not solo:raise ValueError('组队联动需要本机角色读取模式')
            control.team_link=TeamLink(control.team_config,selected_profile(control.character)['self_name'])
            emit({'state':'team_connecting'})
            if team_mode=='follower':allow_town_entry=False
        if allow_town_entry:
            from dungeon_farm.utilities import maintenance
            control.inventory=maintenance(control,lambda u:emit(u) if u['state']!='worker_ended' else None,'inspect_inventory')
        while not control.stop.is_set():
            before=control.inventory;round_start=time.time()
            control.round_start_cubes=before.get('cubes') if before else None
            if control.team_link:
                control.team_link.update(round=completed+1,phase='idle',active=False,ready_for=None)
                control.team_round=None
            if dungeon in SUPPORTED_DUNGEONS and team_mode!='follower':
                outcome=prepare(control,emit,allow_town_entry=allow_town_entry,dungeon=dungeon,difficulty=difficulty)
                while outcome=='waiting_dungeon' and not control.stop.is_set():
                    emit({'state':'waiting_dungeon'})
                    control.stop.wait(1)
                    if not control.stop.is_set():
                        outcome=prepare(control,emit,allow_town_entry=False,dungeon=dungeon,difficulty=difficulty)
                if control.stop.is_set():outcome='stopped'
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
            if outcome=='town_reentry' and team_mode=='solo':
                allow_town_entry=True;control.exit_choice=None
                continue
            if outcome!='reentered':break
            control.exit_choice=None
        else:outcome='stopped'
    except Exception as exc:
        import traceback
        (DATA/'gui-error.log').write_text(traceback.format_exc(),encoding='utf-8')
        outcome='error';emit({'state':'error','detail':str(exc)})
    finally:
        if control.team_link:control.team_link.close();control.team_link=None
        (DATA/'cycle-status.json').write_text(json.dumps({'result':outcome,'completed':completed,'repeat':repeat,'finished':time.time()},ensure_ascii=False,indent=2),encoding='utf-8')
        emit({'state':'worker_ended','result':outcome})
