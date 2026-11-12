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
    def __init__(self, skills=(), attack_key='x', max_runs=1,allow_all_skills=False,toggle_active=(),attack_range=(80,8),stand_off=50):
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
                if skill and skill.mode=='toggle':self.toggle_active.add(skill.key)
                if skill and skill.mode=='awakening':self.releases[skill.key]=now+skill.release_after
            self.casting_until = now + (skill.cast_seconds if skill else .05)

    def step(self, obs, now, enabled=True):
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
            support=next((s for s in self.skills if s.mode in ('buff','toggle')
                          and (s.mode!='toggle' or s.key not in self.toggle_active)
                          and now-self.last_used.get(s.key,float('-inf'))>=s.cooldown),None)
            if support:
                self.pending=Decision('combat',tap=support.key,action='buff')
                return self.pending
            release=next((s for s in self.skills if s.key in self.releases and now>=self.releases[s.key]
                          and abs(dx)<=s.range_x and abs(dy)<=s.range_y),None)
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


def attack_still_valid(decision,obs,scene,skill=None,attack_range=(80,8)):
    """Recheck the selected target immediately before an attack key is sent."""
    if not obs.perception_valid or obs.scene!=scene or obs.dead or obs.loading:return False
    if decision.action=='maintain_summon':
        return bool(skill and skill.key in ('q','w','e') and obs.position is not None)
    if decision.action=='awakening_enter' and not obs.g_confirmed:return False
    enemies=[e for e in obs.enemies if e.alive and (decision.target_id is None or e.identity==decision.target_id)]
    if not enemies or obs.position is None:return False
    if decision.action=='awakening_fire':return decision.tap=='c'
    if decision.action=='buff':return True
    rx,ry=(skill.range_x,skill.range_y) if skill else attack_range
    return any(abs(e.x-obs.position[0])<=rx and abs(e.y-obs.position[1])<=ry for e in enemies)
