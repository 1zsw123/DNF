import unittest
from dataclasses import replace
from dungeon_farm.berserker_rotation import make_planner
from dungeon_farm.planner import Observation,Enemy

class RotationTests(unittest.TestCase):
    def simulate(self,active):
        p=make_planner(active)
        obs=Observation(0,scene='room',position=(100,200),facing='right',enemies=(Enemy('enemy',150,200),),perception_valid=True)
        sent=[]
        for i in range(1600):
            now=i*.1;d=p.step(replace(obs,timestamp=now),now)
            if d.tap:
                sent.append((now,d.tap,d.action));p.acknowledge(d,now,True)
        return sent
    def test_all_hotbar_keys_are_used_and_toggle_is_not_spammed(self):
        sent=self.simulate(False)
        self.assertEqual(set(k for _,k,_ in sent),set('qwertyasdfghx'))
        self.assertEqual(sum(k=='h' for _,k,_ in sent),1)
    def test_already_active_dual_blades_are_preserved(self):
        self.assertFalse(any(k=='h' for _,k,_ in self.simulate(True)))
    def test_awakening_is_released_after_charge_then_waits_cooldown(self):
        awaken=[(t,action) for t,key,action in self.simulate(True) if key=='y']
        self.assertEqual(awaken[1][1],'release')
        self.assertGreaterEqual(awaken[1][0]-awaken[0][0],12)
        self.assertGreaterEqual(awaken[2][0]-awaken[0][0],130)
