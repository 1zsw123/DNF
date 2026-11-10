import unittest
from dungeon_farm.door_approach import DoorApproach

class DoorTests(unittest.TestCase):
    def test_right_door_first_aligns_inside_wall(self):
        a=DoorApproach();d={'direction':'right','x':1340,'y':229}
        self.assertEqual(a.target(d,(1298,359)),(1280,229))
        self.assertEqual(a.target(d,(1282,232)),(1365,229))
        self.assertEqual(a.target(d,(1330,231)),(1365,229))
    def test_new_door_resets_alignment(self):
        a=DoorApproach();a.target({'direction':'right','x':500,'y':200},(490,200))
        self.assertEqual(a.target({'direction':'up','x':200,'y':100},(490,200)),(200,145))
