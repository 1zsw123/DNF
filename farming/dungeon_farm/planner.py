"""Pure decisions only: this module never reads the screen or sends input.

Perception must supply validated enemies, open exits and result-screen signals.
An empty enemy list alone is not evidence that a room has been cleared.
"""
from dataclasses import dataclass
from math import hypot, isfinite
ENTRY_MODES=('entry_buff','entry_helper')
VERIFIED_BUFF_COMMANDS=(('right','right','space'),('right','down','right','z'))


@dataclass(frozen=True)
class Enemy:
    identity: str
    x: float
    y: float
    alive: bool = True


@dataclass(frozen=True)
class Skill:
    key: str
    cooldown: float
    cast_seconds: float
    range_x: float
    range_y: float
    cube_cost: int | None = None  # Unknown costs are blocked, not assumed free.
    mode: str = 'attack'
    release_after: float = 0
    name: str = ''
    mp_cost: int = 0
    input_sequence: tuple[str, ...] = ()


@dataclass(frozen=True)
class Observation:
    timestamp: float
    scene: str | None = None  # Includes PID and room identity, not a screen hash.
    position: tuple[float, float] | None = None
    facing: str | None = None
    enemies: tuple[Enemy, ...] = ()
    perception_valid: bool = False
    foreground: bool = True
    manual: bool = False
    loading: bool = False
    dead: bool = False
    modal: bool = False
    room_clear: bool = False
    exit_position: tuple[float, float] | None = None
    party_ready: bool = False
    results_ready: bool = False
    retry_available: bool = False
    boss_room: bool = False
    g_confirmed: bool = False
    mp_fill: float | None = None


@dataclass(frozen=True)
class Decision:
    state: str
    move: frozenset[str] = frozenset()
    tap: str | None = None
    action: str | None = None
    reason: str = ''
    destination: tuple[float, float] | None = None
    target_id: str | None = None


class FarmPlanner:
    def __init__(self, skills=(), attack_key='x', max_runs=1,allow_all_skills=False,toggle_active=(),attack_range=(80,8),stand_off=50,
                 spam=False,spam_gap=.35,spam_repress=1.5,spam_lane=30,
                 spam_buff_repress=8,spam_awakening_repress=20,spam_basic_between=2,toggle_settle=1.0):
        if max_runs < 1:
            raise ValueError('max_runs must be positive')
        if attack_key != 'x':
            raise ValueError('普通攻击只能使用 X，不能通过此入口绕过技能消耗限制')
        for skill in skills:
            if not skill.key or min(skill.cooldown, skill.cast_seconds, skill.range_x, skill.range_y) < 0:
                raise ValueError('Invalid skill configuration')
        # Current verified berserker bindings only. Resource-cost annotations
        # alone must not accidentally enable a cube skill under an old key map.
        self.skills = tuple(sorted((s for s in skills if (allow_all_skills and (s.key in 'qwertyasdfgh' or (s.mode=='entry_helper' and s.key=='4') or (s.mode=='entry_buff' and s.input_sequence in VERIFIED_BUFF_COMMANDS))) or (s.cube_cost == 0 and s.key in {'a', 's', 'q'})),key=lambda s:(s.cooldown,s.mp_cost,s.cube_cost or 0)))
        self.entry_applied=set()
        self.toggle_active=set(toggle_active)
        self.releases={}
        self.attack_key = attack_key
        self.attack_range=attack_range
        self.stand_off=stand_off
        # Spam mode ignores estimated cooldowns: attack skills go in least
        # recently pressed order within a relaxed lane, with a few basic X
        # attacks between them; buffs are re-pressed every few seconds; the
        # awakening is retried often but keeps its press-wait-release rhythm.
        # A key still on its real cooldown simply does nothing in the client.
        # Only a toggle (H) is never spammed: a second press switches it off.
        self.spam=spam
        self.spam_gap=spam_gap
        self.spam_repress=spam_repress
        self.spam_lane=spam_lane
        self.spam_buff_repress=spam_buff_repress
        self.spam_awakening_repress=spam_awakening_repress
        self.spam_basic_between=spam_basic_between
        self.basic_owed=0
        # Room entry fades in; a toggle pressed too early is dropped by the
        # client while we would believe it is on. Wait for the room first.
        self.toggle_settle=toggle_settle
        self.scene_since=float('-inf')
        # Optional hotbar cooldown reader (dungeon_farm.hotbar.CooldownTracker).
        # Without it, or while its reading is unavailable, nothing changes.
        self.hotbar=None
        self.pressed_at={}
        self.failed={}
        self.verify_window=.7
        self.fail_backoff=2.5
        self.unconfirmed_streak=0
        self.hotbar_gave_up=False
        self.toggle_pending={}
        self.toggle_attempts={}
        self.toggle_verify=1.2
        self.toggle_max_attempts=3
        self.max_runs = max_runs
        self.completed = 0
        self.scene = None
        self.ready_at = 0.0
        self.clear_since = None
        self.pending = None
        self.last_used = {}
        self.casting_until = 0.0
        self.in_results = False
        self.retry_sent = False

    @property
    def needs_entry_buff(self):
        return any(s.mode in ENTRY_MODES and s.key not in self.entry_applied for s in self.skills)

    def cancel_attack(self):
        self.pending=None

    def revived(self):
        self.entry_applied.intersection_update(s.key for s in self.skills if s.mode=='entry_helper')
        self.pending=None;self.casting_until=0
        self.toggle_pending.clear();self.toggle_attempts.clear()

    def hotbar_live(self, now):
        return self.hotbar is not None and not self.hotbar_gave_up and self.hotbar.fresh(now)

    def usable(self, skill, now):
        """False only when the hotbar shows the slot cooling down, or a recent
        press visibly did not fire. Unknown readings never block a key."""
        if not self.hotbar_live(now):
            return True
        if self.hotbar.ready(skill.key, now) is False:
            return False
        t = self.pressed_at.get(skill.key)
        if t is not None and now-t < self.verify_window and not self.hotbar.darkened_since(skill.key, t):
            return False  # just pressed: wait to see whether it fired
        if now-self.failed.get(skill.key, float('-inf')) < self.fail_backoff:
            return False  # pressed but never went dark: skip it for a moment
        return True

    def verify(self, now):
        """Resolve recent presses against the hotbar: a slot that went dark
        fired; one that stayed bright did not."""
        if self.hotbar is None or self.hotbar_gave_up:
            return
        for key, t in list(self.toggle_pending.items()):
            if self.hotbar.darkened_since(key, t):
                self.toggle_active.add(key);del self.toggle_pending[key]
            elif now-t > self.toggle_verify:
                del self.toggle_pending[key]
                if self.toggle_attempts.get(key, 0) >= self.toggle_max_attempts:
                    self.toggle_active.add(key)  # stop retrying a toggle
        for key, t in list(self.pressed_at.items()):
            if self.hotbar.darkened_since(key, t):
                del self.pressed_at[key];self.unconfirmed_streak=0
            elif now-t > self.verify_window:
                del self.pressed_at[key]
                self.failed[key]=now
                self.unconfirmed_streak+=1
                if self.unconfirmed_streak >= 8:
                    # Nothing we press ever darkens: the reading is not the
                    # hotbar (layout/resolution differs). Fall back to spam.
                    self.hotbar_gave_up=True

    @staticmethod
    def movement(position, target, tolerance=(12, 8)):
        dx, dy = target[0]-position[0], target[1]-position[1]
        return frozenset(([('right' if dx > 0 else 'left')] if abs(dx) > tolerance[0] else []) +
                         ([('down' if dy > 0 else 'up')] if abs(dy) > tolerance[1] else []))

    def acknowledge(self, decision, now, success):
        """Only an executed input starts its cooldown; failed sends can retry."""
        if decision != self.pending:
            return
        self.pending = None
        if not success:
            return
        if decision.action == 'retry':
            self.retry_sent = True
        elif decision.tap:
            skill = next((s for s in self.skills if s.key == decision.tap), None)
            if skill and skill.mode=='awakening' and decision.action=='release':
                self.releases.pop(skill.key,None)
            else:
                self.last_used[decision.tap] = now
                if skill and skill.mode in ENTRY_MODES:self.entry_applied.add(skill.key)
                if skill and skill.mode=='toggle':
                    if self.hotbar_live(now):
                        self.toggle_pending[skill.key]=now
                        self.toggle_attempts[skill.key]=self.toggle_attempts.get(skill.key,0)+1
                    else:
                        self.toggle_active.add(skill.key)
                elif skill and self.hotbar_live(now) and skill.key in 'qwertyasdfg':
                    self.pressed_at[skill.key]=now
                if skill and skill.mode=='awakening':self.releases[skill.key]=now+skill.release_after
            cast = skill.cast_seconds if skill else .05
            if skill and self.spam and skill.mode in ('attack','buff'):
                # Do not stand idle for the whole animation estimate; the
                # next key is queued shortly after and the client decides.
                cast = min(cast, self.spam_gap)
            if self.spam:
                if skill and self.spam_skill(skill):
                    self.basic_owed = self.spam_basic_between
                elif decision.tap == self.attack_key:
                    self.basic_owed = max(0, self.basic_owed-1)
            self.casting_until = now + cast

    def blind_step(self, now):
        """Keep attacking in place while enemies briefly cannot be read.

        Used for a few seconds after a fight was seen in the same room, e.g.
        during an awakening animation. No movement and no target check."""
        self.verify(now)
        if not self.spam or now < self.casting_until:
            return None
        release = next((s for s in self.skills if s.key in self.releases and now >= self.releases[s.key]), None)
        if release:
            self.pending = Decision('blind', tap=release.key, action='release')
            return self.pending
        if self.basic_owed:
            if now-self.last_used.get(self.attack_key, float('-inf')) < .07:
                return None
            self.pending = Decision('blind', tap=self.attack_key)
            return self.pending
        ready = [s for s in self.skills if self.spam_skill(s)
                 and now-self.last_used.get(s.key, float('-inf')) >= self.spam_repress
                 and self.usable(s,now)]
        skill = min(ready, key=lambda s: self.last_used.get(s.key, float('-inf')), default=None)
        self.pending = Decision('blind', tap=skill.key if skill else self.attack_key)
        return self.pending

    def spam_skill(self, skill):
        return self.spam and skill.mode not in ('buff','toggle','awakening',*ENTRY_MODES)

    def cooldown(self, skill):
        """Scheduling interval; spam mode shortens buff and awakening waits."""
        if self.spam and skill.mode == 'buff':
            return min(skill.cooldown, self.spam_buff_repress)
        if self.spam and skill.mode == 'awakening':
            return min(skill.cooldown, max(self.spam_awakening_repress, skill.release_after+2))
        return skill.cooldown

    def skill_range(self, skill):
        lane = self.spam_lane if self.spam_skill(skill) else 0
        return skill.range_x, max(skill.range_y, lane)

    def step(self, obs, now, enabled=True):
        self.verify(now)
        if not enabled or not obs.foreground or obs.manual or obs.modal:
            self.clear_since = None
            self.pending = None
            return Decision('paused', reason='未开启、失焦、手动操作或弹窗')
        if not isfinite(obs.timestamp) or not 0 <= now-obs.timestamp <= .3:
            self.clear_since = None
            self.pending = None
            return Decision('waiting', reason='画面数据过期')
        if obs.dead:
            self.pending = None
            return Decision('dead', reason='角色死亡，等待接管')
        if obs.loading:
            self.clear_since = None
            self.pending = None
            self.ready_at = now + .25
            return Decision('loading')
        if obs.results_ready:
            if not self.in_results:
                self.completed += 1
                self.in_results = True
                self.retry_sent = False
            if self.completed >= self.max_runs:
                return Decision('finished', reason='已完成指定次数')
            if not obs.retry_available or self.retry_sent:
                return Decision('results', reason='等待再次挑战按钮或进图')
            self.pending = Decision('results', action='retry')
            return self.pending
        if not obs.perception_valid or not obs.scene or obs.position is None:
            self.clear_since = None
            self.pending = None
            return Decision('waiting', reason='人物、怪物或场景尚未确认')
        if not all(isfinite(v) for v in obs.position):
            return Decision('waiting', reason='角色坐标无效')
        self.in_results = False
        if obs.scene != self.scene:
            self.scene = obs.scene
            self.scene_since = now
            self.ready_at = now + .25
            self.clear_since = None
            self.pending = None
        if now < self.ready_at:
            return Decision('loading', reason='等待新房间稳定')
        enemies = [e for e in obs.enemies if e.alive and isfinite(e.x) and isfinite(e.y)]
        if not enemies and not self.needs_entry_buff:self.pending=None
        if now < self.casting_until and (enemies or self.needs_entry_buff):
            return Decision('casting')
        entry=next((s for s in self.skills if s.mode in ENTRY_MODES and s.key not in self.entry_applied
                    and now-self.last_used.get(s.key,float('-inf'))>=s.cooldown),None)
        if entry:
            self.pending=Decision(entry.mode,tap=entry.key,action=entry.mode,reason=entry.name)
            return self.pending
        if self.needs_entry_buff:return Decision('casting',reason='等待进图增益冷却')
        if enemies:
            self.clear_since = None
            # Finish anything already in melee range before chasing a slightly
            # closer target on another lane.
            hittable = [e for e in enemies if abs(e.x-obs.position[0])<=self.attack_range[0]
                        and abs(e.y-obs.position[1])<=self.attack_range[1]]
            enemy = min(hittable or enemies, key=lambda e: hypot(e.x-obs.position[0], 1.8*(e.y-obs.position[1])))
            dx, dy = enemy.x-obs.position[0], enemy.y-obs.position[1]
            # A toggle that is off (berserker H) goes first, on its own, once the
            # room has settled: pressed during room fade-in or another skill's
            # animation it is silently dropped by the client.
            toggle=next((s for s in self.skills if s.mode=='toggle' and s.key not in self.toggle_active),None)
            if toggle is not None and self.toggle_attempts.get(toggle.key,0) < self.toggle_max_attempts:
                if toggle.key in self.toggle_pending or now-self.scene_since<self.toggle_settle:
                    return Decision('casting',reason='进图稳定后先开双刀')
                # Wait (briefly) for H to light up: while every icon is dimmed
                # by an animation the client would drop the press.
                if (self.hotbar_live(now) and self.hotbar.ready(toggle.key,now) is False
                        and now-self.scene_since<self.toggle_settle+2.5):
                    return Decision('casting',reason='等H亮起再开双刀')
                self.pending=Decision('combat',tap=toggle.key,action='buff')
                return self.pending
            support=next((s for s in self.skills if s.mode=='buff'
                          and now-self.last_used.get(s.key,float('-inf'))>=self.cooldown(s)
                          and self.usable(s,now)),None)
            if support:
                self.pending=Decision('combat',tap=support.key,action='buff')
                return self.pending
            release=next((s for s in self.skills if s.key in self.releases and now>=self.releases[s.key]
                          and abs(dx)<=s.range_x and abs(dy)<=s.range_y),None)
            if self.spam:
                awakening = next((s for s in self.skills if s.mode=='awakening' and s.key not in self.releases
                                  and now-self.last_used.get(s.key, float('-inf')) >= self.cooldown(s)
                                  and self.usable(s,now)
                                  and abs(dx) <= s.range_x and abs(dy) <= s.range_y), None)
                ready = [s for s in self.skills if self.spam_skill(s)
                         and now-self.last_used.get(s.key, float('-inf')) >= self.spam_repress
                         and self.usable(s,now)
                         and abs(dx) <= self.skill_range(s)[0] and abs(dy) <= self.skill_range(s)[1]]
                in_basic_reach = abs(dx) <= self.attack_range[0] and abs(dy) <= self.attack_range[1]
                if awakening:
                    skill = awakening
                elif self.basic_owed and in_basic_reach:
                    skill = None  # weave X between skills when the target is in reach
                else:
                    skill = min(ready, key=lambda s: self.last_used.get(s.key, float('-inf')), default=None)
            else:
                skill = next((s for s in self.skills if now-self.last_used.get(s.key, float('-inf')) >= s.cooldown
                              and s.mode not in ('buff','toggle',*ENTRY_MODES) and s.key not in self.releases
                              and abs(dx) <= s.range_x and abs(dy) <= s.range_y), None)
            skill=release or skill
            if skill is None and (abs(dx) > self.attack_range[0] or abs(dy) > self.attack_range[1]):
                # When horizontal attack range is already satisfied, align
                # lanes without pulling the character back across an obstacle.
                stand_x=obs.position[0] if abs(dx)<=self.attack_range[0] else enemy.x+(-self.stand_off if dx>=0 else self.stand_off)
                destination=(stand_x,enemy.y)
                return Decision('approach', self.movement(obs.position,(stand_x,enemy.y),(10,5)),
                                destination=destination)
            facing = 'right' if dx >= 0 else 'left'
            if obs.facing != facing:
                return Decision('face_enemy', frozenset({facing}))
            key = skill.key if skill else self.attack_key
            if key == self.attack_key and now-self.last_used.get(key,float('-inf')) < .07:
                return Decision('casting')
            self.pending = Decision('combat', tap=key,action='release' if release else None,target_id=enemy.identity)
            return self.pending
        if not obs.room_clear:
            self.clear_since = None
            return Decision('search', reason='尚未确认清怪，不能仅因漏检而过门')
        if self.clear_since is None:
            self.clear_since = now
        if now-self.clear_since < .6:
            return Decision('confirm_clear')
        if not obs.party_ready:
            return Decision('wait_party')
        if obs.exit_position is None or not all(isfinite(v) for v in obs.exit_position):
            return Decision('find_exit', reason='等待已确认的路线出口')
        return Decision('exit', self.movement(obs.position,obs.exit_position,(4,4)))


def attack_still_valid(decision,obs,scene,skill=None,attack_range=(80,8),lane=0):
    """Recheck the selected target immediately before an attack key is sent.

    ``lane`` widens the vertical tolerance of spam-mode attack skills so the
    recheck agrees with the planner that selected them."""
    if not obs.perception_valid or obs.scene!=scene or obs.dead or obs.loading:return False
    if decision.action=='maintain_summon':
        return bool(skill and skill.key in ('q','w','e') and obs.position is not None)
    if decision.action=='awakening_enter' and not obs.g_confirmed:return False
    enemies=[e for e in obs.enemies if e.alive and (decision.target_id is None or e.identity==decision.target_id)]
    if not enemies or obs.position is None:return False
    if decision.action=='awakening_fire':return decision.tap=='c'
    if decision.action=='buff':return True
    rx,ry=(skill.range_x,max(skill.range_y,lane)) if skill else attack_range
    return any(abs(e.x-obs.position[0])<=rx and abs(e.y-obs.position[1])<=ry for e in enemies)
