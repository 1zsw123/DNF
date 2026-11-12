import unittest
from dataclasses import replace
from dungeon_farm.mechanic_rotation import make_planner
from dungeon_farm.planner import Observation,Enemy,Decision,attack_still_valid

class MechanicTests(unittest.TestCase):
    def setUp(self):
        self.p=make_planner(True)
        self.o=Observation(0,scene='room',position=(100,200),facing='right',
                           perception_valid=True,enemies=(Enemy('target',350,200),),g_confirmed=True)
        self.p.step(self.o,0)

    def step(self,t,**kw):return self.p.step(replace(self.o,timestamp=t,**kw),t)
    def cast(self,key,t,success=True):
        d=Decision('combat',tap=key);self.p.pending=d;self.p.acknowledge(d,t,success)

    def shots(self,t,count=8):
        for i in range(count):self.cast('x',t+i*.1)

    def test_buffs_refresh_on_cooldown_even_between_rooms(self):
        for t,key in ((1,'4'),(2,'h'),(3,'f')):
            d=self.step(t);self.assertEqual(d.tap,key);self.p.acknowledge(d,t,True)
        d=self.step(32,enemies=());self.assertEqual(d.tap,'h');self.p.acknowledge(d,32,True)
        d=self.step(43);self.assertEqual(d.tap,'f');self.p.acknowledge(d,43,True)
        self.assertIn('h',self.p.entry_applied)
        d=self.step(62,enemies=());self.assertEqual(d.tap,'h')

    def test_transform_requires_successful_summon_and_shared_interval(self):
        self.p.entry_applied.update(('4','h','f'))
        self.p.last_used.update(h=0,f=0)
        self.p.last_used.update({s.key:0 for s in self.p.skills if s.key not in ('q','w','e','y','h','f','4')})
        self.assertEqual(self.step(1).tap,'q')
        self.cast('q',1,False)
        self.assertIsNone(self.p.g_form)
        self.cast('q',1)
        self.assertFalse(self.p.needs_summon_maintenance(10))
        self.assertTrue(self.p.needs_summon_maintenance(16))
        self.p.last_used['y']=1
        self.assertEqual(self.step(5).tap,'x')
        self.shots(5)
        self.assertEqual(self.step(6).tap,'e');self.cast('e',6)
        self.assertEqual(self.p.g_until,26)
        d=self.step(6.8);self.assertEqual(d.action,'activate_g')
        self.p.acknowledge(d,6.8,True)
        self.shots(7)
        self.assertNotIn(self.step(12).tap,('q','w','e'))
        self.assertEqual(self.step(18).tap,'w');self.cast('w',18)
        d=self.step(18.8);self.assertEqual(d.action,'activate_g')
        self.p.acknowledge(d,18.8,True)
        self.shots(19)
        self.assertNotIn(self.step(22).tap,('q','w','e'))
        self.assertEqual(self.step(23).tap,'e')
        self.p.revived();self.assertIsNone(self.p.g_form)
        self.assertIn('4',self.p.entry_applied)

    def test_clear_room_can_maintain_g_but_not_fire_damage_skills(self):
        self.p.entry_applied.update(('4','h','f'))
        self.p.last_used.update(h=200,f=200)
        d=self.step(200,enemies=());self.assertEqual(d.tap,'q')
        self.assertEqual(d.action,'maintain_summon');self.p.acknowledge(d,200,True)
        self.assertIsNone(self.step(201,enemies=()).tap)

    def test_ranged_basic_attack_and_short_cd_priority(self):
        self.p.entry_applied.update(('4','h','f'))
        self.p.last_used={s.key:0 for s in self.p.skills}
        d=self.step(2);self.assertEqual(d.tap,'x')
        self.assertTrue(attack_still_valid(d,replace(self.o,timestamp=2),'room',attack_range=self.p.attack_range))
        self.assertFalse(attack_still_valid(d,replace(self.o,timestamp=2),'room'))
        d=self.step(17);self.assertEqual(d.tap,'a')
        self.p.acknowledge(d,17,True)
        self.shots(18)
        self.p.last_used['h']=30
        d=self.step(31);self.assertEqual(d.tap,'s')

    def test_ranged_shots_align_vertically_before_firing(self):
        self.p.entry_applied.update(('4','h','f'))
        self.p.last_used={s.key:0 for s in self.p.skills}
        enemy=(Enemy('target',350,337),)
        d=self.step(2,position=(100,319),enemies=enemy)
        self.assertEqual(d.state,'approach');self.assertIn('down',d.move)
        self.assertIsNone(d.tap)
        d=self.step(3,position=(100,334),enemies=enemy)
        self.assertEqual(d.tap,'x')

    def test_close_enemy_causes_bounded_retreat_not_permanent_running(self):
        self.p.entry_applied.update(('4','h','f'));self.p.last_used.update(h=0,f=0)
        self.p.last_used['q']=0
        near=(Enemy('target',150,200),)
        d=self.step(1,enemies=near);self.assertEqual(d.state,'approach')
        self.assertEqual(d.reason,'远程角色拉开距离')
        self.assertIsNone(d.tap)
        self.assertNotEqual(self.step(2.6,enemies=near).reason,'远程角色拉开距离')
        self.assertEqual(self.step(3.6,enemies=near).reason,'远程角色拉开距离')

    def test_g_activation_then_retreat_before_other_damage_skill(self):
        self.p.entry_applied.update(('4','h','f'));self.p.last_used.update(h=0,f=0)
        self.cast('q',1);self.cast('e',6)
        d=self.step(7,position=(400,200),enemies=(Enemy('boss',550,200),))
        self.assertEqual(d.action,'activate_g');self.p.acknowledge(d,7,True)
        d=self.step(7.5,position=(400,200),enemies=(Enemy('boss',550,200),))
        self.assertEqual(d.reason,'远程角色拉开距离')
        self.assertLess(d.destination[0],400)
        self.assertIsNone(d.tap)

    def test_skill_spacing_is_bounded_even_without_basic_shots(self):
        self.p.entry_applied.update(('4','h','f'));self.p.last_used.update(h=0,f=0)
        self.p.last_used['q']=0
        d=self.step(1);self.assertEqual(d.tap,'a');self.p.acknowledge(d,1,True)
        self.assertEqual(self.step(3.6).tap,'x')
        d=self.step(3.8);self.assertEqual(d.tap,'s');self.p.acknowledge(d,3.8,True)
        self.assertEqual(self.step(6.5).tap,'x')
        self.assertEqual(self.step(6.7,mp_fill=.8,enemies=tuple(Enemy(str(i),350,200) for i in range(6))).tap,'r')
        self.assertEqual(self.p.shots_since_skill,0)

    def test_failed_skill_does_not_consume_cadence(self):
        self.p.entry_applied.update(('4','h','f'));self.p.last_used.update(h=0,f=0)
        d=self.step(1);self.p.acknowledge(d,1,False)
        self.assertEqual(self.step(1.1).tap,d.tap)

    def test_bottom_corner_retreat_stays_inside_observed_floor(self):
        self.p.entry_applied.update(('4','h','f'));self.p.last_used.update(h=0,f=0)
        self.p.last_used['q']=0
        enemies=(Enemy('near',90,355),Enemy('far',300,200))
        d=self.step(1,position=(0,366),enemies=enemies)
        self.assertEqual(d.reason,'远程角色拉开距离')
        self.assertLessEqual(d.destination[1],366)
        self.assertGreaterEqual(d.destination[1],200)

    def test_floor_memory_does_not_shrink_when_only_boss_remains(self):
        self.p.entry_applied.update(('4','h','f'));self.p.last_used.update(h=0,f=0,q=0)
        self.step(1,enemies=(Enemy('a',300,120),Enemy('b',500,360)))
        self.step(2,enemies=(Enemy('boss',400,200),))
        self.assertEqual(self.p.floor_bounds,(120,360))
        self.step(3,scene='next',enemies=(Enemy('boss',400,200),))
        self.assertEqual(self.p.floor_bounds,(200,200))

    def test_long_awakening_waits_for_ranged_clearance(self):
        self.p.entry_applied.update(('4','h','f'))
        self.p.last_used={s.key:100 for s in self.p.skills}
        self.p.last_used.update(q=60,y=-1000)
        self.p.g_form='e';self.p.g_until=120;self.p.g_changed=100
        near=(Enemy('boss',330,200),)
        self.assertEqual(self.step(101,enemies=near,boss_room=True).tap,'x')
        self.assertEqual(self.step(102,boss_room=True).tap,'y')
        self.assertEqual(self.step(102,boss_room=False).tap,'x')

    def test_urgent_g_renewal_bypasses_basic_attack_quota(self):
        self.p.entry_applied.update(('4','h','f'));self.p.last_used.update(h=0,f=0)
        self.cast('q',1)
        self.p.shots_since_skill=0
        d=self.step(16);self.assertEqual(d.action,'maintain_summon')
        self.assertEqual(self.p.shots_since_skill,0)

    def test_g_core_not_blocked_by_damage_quota_or_close_enemy(self):
        self.p.entry_applied.update(('4','h','f'));self.p.last_used.update(h=0,f=0)
        self.p.shots_since_skill=0;self.p.damage_ready=100
        near=(Enemy('boss',150,200),)
        d=self.step(1,enemies=near);self.assertEqual(d.tap,'q');self.p.acknowledge(d,1,True)
        d=self.step(6,enemies=near);self.assertEqual(d.tap,'e');self.p.acknowledge(d,6,True)
        d=self.step(6.8,enemies=near);self.assertEqual(d.action,'activate_g')
        self.assertEqual(self.p.damage_ready,100)
        self.assertEqual(self.p.shots_since_skill,0)

    def test_boss_uses_ready_skills_without_basic_attack_quota(self):
        self.p.entry_applied.update(('4','h','f'));self.p.last_used.update(h=0,f=0,q=0)
        d=self.step(1,boss_room=True);self.assertEqual(d.tap,'a');self.p.acknowledge(d,1,True)
        d=self.step(1.8,boss_room=True);self.assertEqual(d.tap,'s');self.p.acknowledge(d,1.8,True)
        self.assertEqual(self.step(2.7,boss_room=True).tap,'r')
        self.assertEqual(self.p.shots_since_skill,0)
        self.assertEqual(self.step(2.7,boss_room=False).tap,'x')

    def test_boss_allows_awakening_without_waiting_for_g1_resummon_cd(self):
        self.p.entry_applied.update(('4','h','f'))
        self.p.last_used={s.key:100 for s in self.p.skills};self.p.last_used['y']=-1000
        self.p.g_form='e';self.p.g_until=120;self.p.g_changed=100
        self.p.shots_since_skill=0;self.p.damage_ready=200
        self.assertEqual(self.step(101,boss_room=True).tap,'y')
        self.assertEqual(self.step(101,boss_room=False).tap,'x')

    def test_boss_mode_still_stops_attack_when_enemies_are_gone(self):
        self.p.entry_applied.update(('4','h','f'));self.p.last_used.update(h=0,f=0)
        self.cast('q',0)
        self.assertIsNone(self.step(1,boss_room=True,enemies=()).tap)

    def test_g_resummon_between_rooms_obeys_cooldown_and_validation(self):
        self.p.entry_applied.update(('4','h','f'));self.p.last_used.update(h=30,f=30,q=1)
        self.assertFalse(self.p.needs_summon_maintenance(40))
        self.assertTrue(self.p.needs_summon_maintenance(41))
        d=self.step(41,enemies=());self.assertEqual(d.tap,'q')
        skill=next(s for s in self.p.skills if s.key=='q')
        self.assertTrue(attack_still_valid(d,replace(self.o,enemies=()),'room',skill))
        self.assertFalse(attack_still_valid(d,replace(self.o,enemies=(),dead=True),'room',skill))

    def test_retreat_starts_before_melee_and_has_sprint_intent(self):
        self.p.entry_applied.update(('4','h','f'));self.p.last_used.update(h=0,f=0,q=0)
        d=self.step(1,position=(400,200),enemies=(Enemy('mob',600,200),))
        self.assertEqual(d.action,'retreat')
        self.assertEqual(d.destination,(220,200))

    def test_awakening_mode_fires_c_before_buffs_g_or_retreat(self):
        self.p.entry_applied.update(('4','h','f'))
        self.p.last_used={s.key:100 for s in self.p.skills};self.p.last_used['y']=-1000
        self.p.g_form='e';self.p.g_until=120;self.p.g_changed=100
        d=self.step(101,boss_room=True);self.assertEqual(d.tap,'y')
        self.p.acknowledge(d,101,True)
        near=(Enemy('boss',110,200),)
        d=self.p.immediate_awakening_fire()
        self.assertEqual((d.tap,d.action),('c','awakening_fire'))
        self.assertFalse(d.move)
        self.assertTrue(attack_still_valid(d,replace(self.o,enemies=near),'room'))
        self.p.acknowledge(d,101.1,False)
        self.assertEqual(self.step(101.2,boss_room=True).tap,'c')
        d=self.step(101.2,boss_room=True);self.p.acknowledge(d,101.2,True)
        self.assertIsNone(self.p.awakening_pending)
        self.assertIsNone(self.p.g_form)
        self.assertNotEqual(self.step(101.3,boss_room=True).tap,'c')

    def test_awakening_does_not_fire_without_g_or_after_failed_y_input(self):
        self.p.entry_applied.update(('4','h','f'));self.p.last_used={s.key:100 for s in self.p.skills}
        self.p.last_used['y']=-1000
        self.assertNotEqual(self.step(101,boss_room=True).tap,'y')
        self.p.g_form='e';self.p.g_until=120;self.p.g_changed=100
        self.assertNotEqual(self.step(101.5,boss_room=True,g_confirmed=False).tap,'y')
        d=self.step(102,boss_room=True);self.assertEqual(d.tap,'y')
        skill=next(s for s in self.p.skills if s.key=='y')
        self.assertFalse(attack_still_valid(d,replace(self.o,g_confirmed=False),'room',skill))
        self.p.acknowledge(d,102,False)
        self.assertIsNone(self.p.awakening_pending)

    def test_basic_attack_keeps_four_hundred_pixel_distance(self):
        self.p.entry_applied.update(('4','h','f'));self.p.last_used={s.key:0 for s in self.p.skills}
        self.assertEqual(self.step(2,enemies=(Enemy('target',500,200),)).tap,'x')

    def test_missing_real_g_does_not_get_infinite_fake_renewals(self):
        self.p.entry_applied.update(('4','h','f'));self.p.last_used.update(h=0,f=0)
        self.cast('q',1);self.cast('e',6)
        self.step(7.1,g_confirmed=False)
        d=self.step(7.8,g_confirmed=False)
        self.assertEqual(d.tap,'q')
        self.p.acknowledge(d,7.8,True)
        self.assertNotEqual(self.step(8.6,g_confirmed=False).tap,'q')

    def test_one_missing_frame_does_not_resummon_a_real_g(self):
        self.p.entry_applied.update(('4','h','f'));self.p.last_used.update(h=0,f=0)
        self.cast('q',1);self.cast('e',6)
        self.step(7.1,g_confirmed=False)
        self.step(7.5,g_confirmed=True)
        self.assertEqual(self.p.g_form,'e')
        self.assertIsNone(self.p.g_missing_since)

    def test_normal_rooms_reserve_mana_without_disabling_g_or_boss_damage(self):
        self.p.entry_applied.update(('4','h','f'));self.p.last_used.update(h=0,f=0,q=0)
        self.p.g_form='e';self.p.g_changed=0;self.p.g_until=30
        self.assertEqual(self.step(2,mp_fill=.2).tap,'x')
        self.assertEqual(self.step(2,mp_fill=.2,boss_room=True).tap,'a')
        self.p.g_form=None;self.p.last_used['q']=-100
        self.assertEqual(self.step(2,mp_fill=.2).tap,'q')

    def test_heavy_normal_skill_needs_dense_enemies_and_spare_mana(self):
        self.p.entry_applied.update(('4','h','f'));self.p.last_used.update(h=0,f=0,q=0,a=0,s=0)
        dense=tuple(Enemy(str(i),350,200) for i in range(6))
        self.assertEqual(self.step(2,mp_fill=.7).tap,'x')
        self.assertEqual(self.step(2,mp_fill=.6,enemies=dense).tap,'x')
        self.assertEqual(self.step(2,mp_fill=None,enemies=dense).tap,'x')
        self.assertEqual(self.step(2,mp_fill=.7,enemies=dense).tap,'r')

    def test_keep_g_alive_between_rooms_without_attacking(self):
        self.p.entry_applied.update(('4','h','f'));self.p.last_used.update(h=0,f=0)
        self.cast('q',1)
        d=self.step(16,enemies=());self.assertEqual(d.action,'maintain_summon')
        self.assertEqual(d.tap,'e')
        skill=next(s for s in self.p.skills if s.key==d.tap)
        self.assertTrue(attack_still_valid(d,replace(self.o,enemies=()),'room',skill))
        self.assertFalse(attack_still_valid(d,replace(self.o,enemies=(),scene='other'),'room',skill))
        self.p.acknowledge(d,16,False);self.assertEqual(self.p.g_until,21)
        d=self.step(16.1,enemies=());self.p.acknowledge(d,16.1,True)
        self.assertGreater(self.p.g_until,21)
        self.assertIsNone(self.step(18,enemies=()).tap)
        self.assertFalse(self.p.needs_summon_maintenance(18))

    def test_g_activation_retries_without_extending_duration_or_resetting_cd(self):
        self.p.entry_applied.update(('4','h','f'));self.p.last_used.update(h=0,f=0)
        self.cast('q',1);self.cast('e',6)
        self.assertIsNone(self.step(6.9,enemies=()).tap)
        d=self.step(7);self.assertEqual(d.action,'activate_g');self.assertEqual(d.tap,'e')
        self.p.acknowledge(d,7,False)
        d=self.step(7.1);self.assertEqual(d.action,'activate_g')
        self.p.acknowledge(d,7.1,True)
        self.assertEqual(self.p.last_used['e'],6)
        self.assertEqual(self.p.g_until,26)
        self.assertIsNone(self.p.g_activation)
        self.assertNotEqual(self.step(8).action,'activate_g')
