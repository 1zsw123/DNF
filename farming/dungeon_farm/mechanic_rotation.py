"""上头枪 hotbar, verified from the local client on 2026-11-12.

Timing tracks sent inputs, not server buff state. G transformations require a
prior summon and a shared 5 s interval. Their +10 s extension is panel data.
Animation locks and attack ranges remain controller estimates.
"""
from dungeon_farm.planner import FarmPlanner, Skill, Decision
from dataclasses import replace
from math import isfinite, hypot

VERIFIED=(
    ('a','Ex-S毒蛇炮',16.1,767,0,.7,320,35),
    ('s','空战机械·狂风',30,650,1,.8,350,100),
    ('d','Ex-S Zero毒蛇炮',50,918,1,.9,320,35),
    ('q','G-1柯洛纳',40,1119,0,.7,350,100),
    ('w','改装G-2旋雷',5,415,0,.6,350,100),
    ('e','改装G-3猛禽',5,380,0,.6,350,100),
    ('r','空投支援',40,966,2,.9,320,45),
    ('t','拦截机工厂',55,1344,2,1,300,70),
    ('y','G-0战争领主',145,2096,5,4,350,100),
)

class MechanicPlanner(FarmPlanner):
    def __init__(self,entry_helper=False):
        # Range estimates are deliberately separate from verified tooltip CDs.
        # The player's ranged setup can attack before the old 300 px approach.
        skills=[Skill(k,cd,lock,max(rx,480),ry,cubes,name=name,mp_cost=mp)
                for k,name,cd,mp,cubes,lock,rx,ry in VERIFIED]
        skills += [Skill('h',30,.7,0,0,0,'entry_buff',name='机械改良',mp_cost=500),
                   Skill('f',40,.7,0,0,0,'entry_buff',name='远古记忆',mp_cost=100)]
        # G is camouflage: attacks break it and it consumes a cube. Keep it
        # available to the player, but do not waste it in the damage rotation.
        if entry_helper:skills.append(Skill('4',0,.6,0,0,0,'entry_helper',name='召唤帮手'))
        super().__init__(skills,allow_all_skills=True,attack_range=(420,8),stand_off=380)
        self.g_form=None;self.g_until=0;self.g_changed=float('-inf')
        self.g_activation=None
        self.retreat_until=0;self.retreat_ready=0;self.retreat_target=None
        self.damage_ready=0;self.shots_since_skill=8
        self.floor_scene=None;self.floor_bounds=None
        self.awakening_pending=None
        self.g_missing_since=None

    def retreat(self,obs,now,enemies):
        """Retreat before melee contact; reject routes cutting through enemies."""
        x,y=obs.position
        close=[e for e in enemies if abs(e.x-x)<220 and abs(e.y-y)<80]
        if not close:
            self.retreat_until=0
            return None
        if now>=self.retreat_ready:
            nearest=min(close,key=lambda e:(e.x-x)**2+2*(e.y-y)**2)
            # Do not choose a destination across the nearest enemy. If the
            # left edge leaves no room, evade vertically before realigning.
            away=-1 if nearest.x>=x else 1
            floor_min,floor_max=self.floor_bounds or (y,y)
            candidates=[(max(35,nearest.x+away*380),y),(max(35,nearest.x-away*380),y)]
            for side_y in (max(floor_min,y-100),min(floor_max,y+100)):
                if abs(side_y-y)>40:
                    candidates.extend(((max(35,x+away*140),side_y),(x,side_y)))
            candidates=[p for p in candidates if abs(p[0]-x)+abs(p[1]-y)>40]
            clear=[p for p in candidates if min(hypot(e.x-p[0],1.6*(e.y-p[1])) for e in enemies)>=220]
            if clear:candidates=clear
            if candidates:
                def safety(p):
                    end=min(hypot(e.x-p[0],1.6*(e.y-p[1])) for e in enemies)
                    path=min(hypot(e.x-(x+(p[0]-x)*t),1.6*(e.y-(y+(p[1]-y)*t)))
                             for e in enemies for t in (.25,.5,.75,1))
                    return end+2*path-.1*hypot(p[0]-x,p[1]-y)-(30 if p[0]<60 else 0)
                self.retreat_target=max(candidates,key=safety)
                self.retreat_until=now+1.5;self.retreat_ready=now+2.5
        if now<self.retreat_until and self.retreat_target:
            self.pending=None
            return Decision('approach',self.movement(obs.position,self.retreat_target),
                            destination=self.retreat_target,action='retreat',reason='远程角色拉开距离')
        return None

    def needs_summon_maintenance(self,now):
        if now<self.casting_until:return False
        if self.g_form is None or now>=self.g_until:
            return now-self.last_used.get('q',float('-inf'))>=40
        return 0<self.g_until-now<=6 and now-self.g_changed>=5

    def needs_maintenance(self,now):
        return self.needs_summon_maintenance(now) or any(
            now-self.last_used.get(k,float('-inf'))>=cd for k,cd in (('h',30),('f',40)))

    def step(self,obs,now,enabled=True):
        if self.awakening_pending is not None:
            valid=(enabled and obs.foreground and not (obs.manual or obs.modal or obs.dead or obs.loading)
                   and obs.perception_valid and 0<=now-obs.timestamp<=.3)
            if not valid:return Decision('waiting')
            if obs.results_ready:
                self.awakening_pending=None
                return Decision('results')
            if now<self.awakening_pending:return Decision('awakening_wait',reason='等待觉醒模式展开')
            if any(e.alive for e in obs.enemies):
                self.pending=Decision('combat',tap='c',action='awakening_fire',reason='觉醒模式：C 立即发动攻击')
                return self.pending
            return Decision('awakening_wait',reason='觉醒模式等待有效目标')
        if (enabled and obs.foreground and not (obs.manual or obs.modal or obs.dead or obs.loading)
                and obs.perception_valid and 0<=now-obs.timestamp<=.3):
            if obs.g_confirmed:
                self.g_missing_since=None
            elif self.g_form in ('w','e') and now-self.g_changed>=1:
                if self.g_missing_since is None:self.g_missing_since=now
                elif now-self.g_missing_since>=.6:
                    # An input acknowledgement is not a successful summon.
                    # Do not perpetually renew a robot that never appeared.
                    # Reattempt Q only after a whole Q->transform cycle; an
                    # actual client cooldown will reject it without item use.
                    self.g_form=None;self.g_until=0;self.g_activation=None
                    self.last_used['q']=min(self.last_used.get('q',float('-inf')),now-40)
                    self.g_missing_since=None
            if obs.position is not None and all(isfinite(v) for v in obs.position):
                ys=[obs.position[1],*(e.y for e in obs.enemies if e.alive and isfinite(e.y))]
                if self.floor_scene!=obs.scene:
                    self.floor_scene=obs.scene;self.floor_bounds=(min(ys),max(ys))
                else:self.floor_bounds=(min(self.floor_bounds[0],*ys),max(self.floor_bounds[1],*ys))
            for key,interval in (('h',30),('f',40)):
                if now-self.last_used.get(key,float('-inf'))>=interval:
                    self.entry_applied.discard(key)
        active=self.g_form is not None and now<self.g_until
        elapsed=now-self.g_changed
        # Stay in tracking form for most of the cycle. A brief G2 interval
        # renews the summon, then G3 resumes; never spam zero-CD transforms.
        # Awakening replaces the G robots. Avoid a long gap waiting for G1's
        # 40 s summon cooldown after awakening finishes.
        allowed_g={'q'} if not active else set()
        if active and obs.boss_room and obs.g_confirmed and (obs.mp_fill is None or obs.mp_fill>=.08):allowed_g.add('y')
        if active and elapsed>=5:
            if self.g_form in ('q','w'):allowed_g.add('e')
            elif self.g_form=='e' and elapsed>=12:allowed_g.add('w')
        original=self.skills
        # Cooldown readiness is not a command to empty the whole hotbar.
        # A bounded interval allows basic shots without ever requiring a shot
        # quota that can starve skills while aligning or being hit.
        can_damage=obs.boss_room or now>=self.damage_ready
        reserve_ok=obs.mp_fill is None or obs.mp_fill>.25
        heavy_ok=len([e for e in obs.enemies if e.alive])>=6 and obs.mp_fill is not None and obs.mp_fill>.65
        channel_safe=obs.position is not None and not any(
            e.alive and abs(e.x-obs.position[0])<240 and abs(e.y-obs.position[1])<100
            for e in obs.enemies)
        self.skills=tuple(s for s in original
                          if (s.mode!='attack' or s.key in ('q','w','e') or can_damage)
                          and (obs.boss_room or s.mode!='attack' or s.key in ('q','w','e')
                               or (reserve_ok and (s.key not in ('d','r','t') or heavy_ok)))
                          and (s.mode!='attack' or s.cast_seconds<=1 or channel_safe)
                          and (s.key not in ('q','w','e','y') or s.key in allowed_g))
        try:decision=super().step(obs,now,enabled)
        finally:self.skills=original
        controllable=decision.state not in ('paused','waiting','dead','loading','results','finished','casting','entry_buff','entry_helper')
        if not controllable:return decision
        enemies=[e for e in obs.enemies if e.alive and isfinite(e.x) and isfinite(e.y)]
        # G is continuous support, including between rooms. Re-summon as soon
        # as its real configured cooldown permits; normal damage still stops
        # when enemies are gone.
        if self.needs_summon_maintenance(now):
            key=('w' if self.g_form=='e' else 'e') if active else 'q'
            self.pending=Decision('combat',tap=key,action='maintain_summon',reason='维持 G 系列常驻')
            return self.pending
        if active and self.g_activation and self.g_activation[0]==self.g_form:
            key,due=self.g_activation
            candidates=[e for e in enemies if abs(e.x-obs.position[0])<=480 and abs(e.y-obs.position[1])<=100]
            if now>=due and candidates:
                # This client requires another press after transformation to
                # engage the robot. It is part of that cast, not a new form.
                self.pending=Decision('combat',tap=key,action='activate_g',
                                      target_id=candidates[0].identity,reason='变形后再次按键激活攻击')
                return self.pending
        candidates=[e for e in enemies if abs(e.x-obs.position[0])<=480 and abs(e.y-obs.position[1])<=100]
        core=next((s for s in original if s.key in ('q','w','e') and s.key in allowed_g
                   and now-self.last_used.get(s.key,float('-inf'))>=s.cooldown),None)
        if core and candidates:
            self.pending=Decision('combat',tap=core.key,target_id=candidates[0].identity,
                                  reason='G 系列核心输出优先')
            return self.pending
        if enemies and decision.state in ('combat','approach','face_enemy'):
            escape=self.retreat(obs,now,enemies)
            if escape:return escape
        if decision.tap=='y':
            decision=replace(decision,action='awakening_enter',reason='G 系列活动期间进入觉醒模式')
            self.pending=decision
        return decision

    def acknowledge(self,decision,now,success):
        accepted=success and decision==self.pending
        if decision.action=='awakening_fire':
            if decision!=self.pending:return
            self.pending=None
            if accepted:
                self.awakening_pending=None
                self.g_form=None;self.g_until=0;self.g_activation=None
                self.casting_until=now+2
            return
        if decision.action=='activate_g':
            if decision!=self.pending:return
            self.pending=None
            if accepted:
                self.g_activation=None
                self.casting_until=now+.3
            return
        super().acknowledge(decision,now,success)
        if not accepted:return
        skill=next((s for s in self.skills if s.key==decision.tap),None)
        if decision.tap==self.attack_key:
            self.shots_since_skill+=1
        elif skill and skill.mode=='attack' and skill.key not in ('q','w','e'):
            self.shots_since_skill=0
            self.damage_ready=now+skill.cast_seconds+(3 if skill.mp_cost>=900 else 2)
        if decision.tap=='q':
            self.g_form='q';self.g_until=now+20;self.g_changed=now
            self.g_activation=None
        elif decision.tap in ('w','e'):
            self.g_form=decision.tap;self.g_until=min(self.g_until+10,now+20);self.g_changed=now
            self.g_activation=(decision.tap,now+.7)
        elif decision.tap=='y':
            # Y only enters the targeting mode; C actually fires it in this
            # client. Preserve exclusive control until that second input.
            self.awakening_pending=now

    def immediate_awakening_fire(self):
        if self.awakening_pending is None:return None
        self.pending=Decision('combat',tap='c',action='awakening_fire',reason='Y 后立即按 C 发动觉醒')
        return self.pending

    def revived(self):
        super().revived()
        self.g_form=None;self.g_until=0;self.g_changed=float('-inf')
        self.g_activation=None
        self.retreat_until=0;self.retreat_ready=0;self.retreat_target=None
        self.damage_ready=0;self.shots_since_skill=8
        self.awakening_pending=None
        self.g_missing_since=None

def make_planner(entry_helper=False):return MechanicPlanner(entry_helper)
