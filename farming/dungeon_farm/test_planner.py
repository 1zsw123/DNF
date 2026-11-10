import unittest
from dataclasses import replace
from dungeon_farm.planner import FarmPlanner, Observation, Enemy, Skill


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.p=FarmPlanner([Skill('a',5,.3,120,25,cube_cost=0)],max_runs=2)
        self.o=Observation(0,scene='pid1:room1',position=(100,200),facing='right',perception_valid=True)
        self.p.step(self.o,0)
    def step(self,t=1,**changes):
        return self.p.step(replace(self.o,timestamp=t,**changes),t)
    def test_old_frame_does_not_move(self):
        self.assertEqual(self.p.step(self.o,10).state,'waiting')
    def test_pause_clears_action(self):
        d=self.step(foreground=False,enemies=(Enemy('a',500,200),))
        self.assertFalse(d.move)
        self.assertIsNone(d.tap)
    def test_missing_enemies_does_not_prove_clear(self):
        self.assertEqual(self.step(exit_position=(800,200),party_ready=True).state,'search')
    def test_approach_and_face_before_attack(self):
        self.assertEqual(self.step(enemies=(Enemy('a',500,200),)).move,frozenset({'right'}))
        d=self.step(enemies=(Enemy('a',20,200),))
        self.assertEqual(d.state,'face_enemy')
        self.assertIsNone(d.tap)
    def test_cooldown_begins_only_after_successful_input(self):
        d=self.step(enemies=(Enemy('a',180,200),))
        self.assertEqual(d.tap,'a')
        self.p.acknowledge(d,1,False)
        self.assertEqual(self.step(1.1,enemies=(Enemy('a',180,200),)).tap,'a')
        self.p.acknowledge(d,1.1,True)
        self.assertEqual(self.step(1.2,enemies=(Enemy('a',180,200),)).state,'casting')
        self.assertEqual(self.step(2,enemies=(Enemy('a',180,200),)).tap,'x')
    def test_clear_requires_stability_and_party(self):
        self.assertEqual(self.step(room_clear=True).state,'confirm_clear')
        self.assertEqual(self.step(2,room_clear=True).state,'wait_party')
        self.assertEqual(self.step(2.1,room_clear=True,party_ready=True,exit_position=(800,200)).state,'exit')
    def test_room_change_clears_old_decision(self):
        self.step(room_clear=True)
        self.assertEqual(self.step(2,scene='pid1:room2',room_clear=True).state,'loading')
    def test_results_count_once_and_retry_once(self):
        d=self.step(results_ready=True,retry_available=True)
        self.assertEqual(d.action,'retry')
        self.p.acknowledge(d,1,True)
        self.assertIsNone(self.step(2,results_ready=True,retry_available=True).action)
        self.assertEqual(self.p.completed,1)
        self.step(3,scene='pid1:next_run')
        self.assertEqual(self.step(4,results_ready=True,retry_available=True).state,'finished')
    def test_death_does_not_trigger_retry_or_revive(self):
        d=self.step(dead=True,results_ready=True,retry_available=True)
        self.assertEqual(d.state,'dead')
        self.assertIsNone(d.action)

    def test_cube_and_unknown_costs_are_never_cast(self):
        for skill in (Skill('a',0,0,200,100,cube_cost=1),
                      Skill('s',0,0,200,100),
                      Skill('r',0,0,200,100,cube_cost=0),
                      Skill('h',0,0,200,100,cube_cost=0)):
            p=FarmPlanner([skill])
            p.step(self.o,0)
            d=p.step(replace(self.o,timestamp=1,enemies=(Enemy('a',150,200),)),1)
            self.assertEqual(d.tap,'x')

    def test_cannot_use_cube_key_as_basic_attack(self):
        with self.assertRaises(ValueError):
            FarmPlanner(attack_key='r')

    def test_basic_combo_resumes_without_old_extra_delay(self):
        self.p.skills=()
        enemy=(Enemy('target',150,200),)
        d=self.step(1,enemies=enemy)
        self.assertEqual(d.tap,'x')
        self.p.acknowledge(d,1,True)
        self.assertIsNone(self.step(1.04,enemies=enemy).tap)
        self.assertEqual(self.step(1.08,enemies=enemy).tap,'x')

    def test_hit_available_enemy_before_chasing_other_lane(self):
        self.p.skills=()
        d=self.step(enemies=(Enemy('near_off_lane',100,220),Enemy('hittable',170,200)))
        self.assertEqual(d.tap,'x')
        self.assertFalse(d.move)


if __name__=='__main__':unittest.main()
