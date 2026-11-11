import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch
from dungeon_farm.blade_rotation import make_planner
from dungeon_farm.planner import Observation,Enemy,Decision,attack_still_valid
from dungeon_farm.combat_inputs import CombatInputs
from follow import C,INPUT

class BladeTests(unittest.TestCase):
    def test_helper_once_per_run_not_per_room_or_revive(self):
        p=make_planner(entry_helper=True)
        o=Observation(0,scene='a',position=(100,200),perception_valid=True)
        p.step(o,0)
        d=p.step(replace(o,timestamp=1),1);self.assertEqual(d.tap,'4')
        p.acknowledge(d,1,False)
        d=p.step(replace(o,timestamp=1.1),1.1);self.assertEqual(d.tap,'4')
        p.acknowledge(d,1.1,True)
        d=p.step(replace(o,timestamp=2),2);self.assertEqual(d.tap,'tracking_buff')
        p.acknowledge(d,2,True)
        p.revived()
        self.assertIn('4',p.entry_applied)
        p.step(replace(o,timestamp=8,scene='b'),8)
        self.assertEqual(p.step(replace(o,timestamp=9,scene='b'),9).tap,'tracking_buff')
        fresh=make_planner(entry_helper=True);fresh.step(o,0)
        self.assertEqual(fresh.step(replace(o,timestamp=1),1).tap,'4')
    def setUp(self):
        self.p=make_planner()
        self.o=Observation(0,scene='a',position=(100,200),facing='right',perception_valid=True)
        self.p.step(self.o,0)

    def step(self,t,**kw):return self.p.step(replace(self.o,timestamp=t,**kw),t)

    def test_entry_buff_without_enemies_once_per_run_and_again_after_revive(self):
        d=self.step(1);self.assertEqual(d.tap,'tracking_buff')
        self.p.acknowledge(d,1,True)
        self.assertFalse(self.p.needs_entry_buff)
        self.assertIsNone(self.step(6,scene='b').tap)
        self.assertIsNone(self.step(7,scene='b').tap)
        self.p.revived()
        self.assertEqual(self.step(8,scene='b').tap,'tracking_buff')

    def test_shortest_ready_cd_then_low_mp_and_basic_attacks_during_cooldown(self):
        self.p.entry_applied.add('tracking_buff')
        enemies=(Enemy('target',150,200),)
        d=self.step(1,enemies=enemies);self.assertEqual(d.tap,'s')
        self.p.acknowledge(d,1,True)
        d=self.step(2,enemies=enemies);self.assertEqual(d.tap,'a')
        self.p.acknowledge(d,2,True)
        d=self.step(3,enemies=enemies);self.assertEqual(d.tap,'d')
        self.p.last_used={s.key:3 for s in self.p.skills}
        self.assertEqual(self.step(4,enemies=enemies).tap,'x')
        self.assertEqual(self.step(9.01,enemies=enemies).tap,'s')

    def test_dead_target_cancels_pending_input_without_starting_cooldown(self):
        self.p.entry_applied.add('tracking_buff')
        d=self.step(1,enemies=(Enemy('target',150,200),))
        self.assertFalse(attack_still_valid(d,replace(self.o,enemies=()),'a',self.p.skills[1]))
        self.step(1.1,enemies=())
        self.p.acknowledge(d,1.2,True)
        self.assertNotIn(d.tap,self.p.last_used)

    def test_pre_send_check_rejects_changed_scene_dead_or_out_of_range_target(self):
        d=Decision('combat',tap='s',target_id='target')
        skill=next(s for s in self.p.skills if s.key=='s')
        o=replace(self.o,enemies=(Enemy('target',150,200),))
        self.assertTrue(attack_still_valid(d,o,'a',skill))
        for bad in (replace(o,scene='b'),replace(o,dead=True),replace(o,enemies=(Enemy('target',500,400),)),replace(o,enemies=(Enemy('other',150,200),))):
            self.assertFalse(attack_still_valid(d,bad,'a',skill))

    def test_buff_command_sends_and_releases_right_right_space(self):
        sent=[]
        def send(n,ptr,size):
            k=C.cast(ptr,C.POINTER(INPUT)).contents.ki
            sent.append((k.wScan,k.dwFlags));return 1
        win=SimpleNamespace(u=SimpleNamespace(SendInput=send),foreground=lambda _:True,release=lambda:None)
        keys=CombatInputs(win,all_skills=True)
        buff=next(s for s in self.p.skills if s.mode=='entry_buff')
        self.assertTrue(keys.cast(buff,1))
        self.assertEqual(sent,[(0x4d,9),(0x4d,11),(0x4d,9),(0x4d,11),(0x39,8),(0x39,10)])
        sent.clear()
        self.assertFalse(keys.cast(buff,1,lambda:True));self.assertEqual(sent,[])
