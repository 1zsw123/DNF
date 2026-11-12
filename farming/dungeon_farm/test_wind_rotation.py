import unittest
from dataclasses import replace
from types import SimpleNamespace
from dungeon_farm.characters import character_planner
from dungeon_farm.planner import Observation, Enemy
from dungeon_farm.combat_inputs import CombatInputs
from follow import C, INPUT

class WindTests(unittest.TestCase):
    def test_entry_then_short_cd_and_basic_attack(self):
        p=character_planner({'rotation':'风神冷却优先','entry_helper':True})
        o=Observation(0,scene='a',position=(100,200),facing='right',perception_valid=True)
        p.step(o,0)
        d=p.step(replace(o,timestamp=1),1);self.assertEqual(d.tap,'4');p.acknowledge(d,1,True)
        d=p.step(replace(o,timestamp=2),2);self.assertEqual(d.tap,'wind_buff');p.acknowledge(d,2,True)
        combat=replace(o,enemies=(Enemy('target',150,200),))
        d=p.step(replace(combat,timestamp=3),3);self.assertEqual(d.tap,'a');p.acknowledge(d,3,True)
        d=p.step(replace(combat,timestamp=4),4);self.assertEqual(d.tap,'s')
        p.last_used={s.key:4 for s in p.skills}
        self.assertEqual(p.step(replace(combat,timestamp=5),5).tap,'x')
        self.assertIsNone(p.step(replace(o,timestamp=6),6).tap)
        p.revived();self.assertIn('4',p.entry_applied);self.assertNotIn('wind_buff',p.entry_applied)

    def test_buff_uses_extended_down_and_releases_every_key(self):
        sent=[]
        def send(n,ptr,size):
            k=C.cast(ptr,C.POINTER(INPUT)).contents.ki
            sent.append((k.wScan,k.dwFlags));return 1
        win=SimpleNamespace(u=SimpleNamespace(SendInput=send),foreground=lambda _:True,release=lambda:None)
        p=character_planner({'rotation':'风神冷却优先'})
        buff=next(s for s in p.skills if s.mode=='entry_buff')
        self.assertTrue(CombatInputs(win,True).cast(buff,1))
        self.assertEqual(sent,[(0x4d,9),(0x4d,11),(0x50,9),(0x50,11),(0x4d,9),(0x4d,11),(0x2c,8),(0x2c,10)])
        sent.clear()
        self.assertFalse(CombatInputs(win,True).cast(buff,1,lambda:True))
        self.assertEqual(sent,[])
