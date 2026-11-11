import unittest
from unittest.mock import patch
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
    def test_clear_room_escape_does_not_cross_entrance_trigger(self):
        a=DoorApproach();left={'direction':'left','x':54,'y':418};right={'direction':'right','x':837,'y':174}
        self.assertEqual(a.target(right,(0,373),[left,right]),(0,328))
        self.assertEqual(a.target(right,(0,328),[left,right]),(294,328))
        self.assertEqual(a.target(right,(294,328),[left,right]),(777,174))
        self.assertEqual(a.target(right,(777,174),[left,right]),(862,174))
    def test_north_entry_moves_inward_before_crossing_its_lane(self):
        a=DoorApproach();up={'direction':'up','x':226,'y':100};right={'direction':'right','x':1051,'y':158}
        self.assertEqual(a.target(right,(214,113),[up,right]),(214,250))
        self.assertEqual(a.target(right,(214,232),[up,right]),(406,250))
        self.assertEqual(a.target(right,(214,227),[up,right]),(406,250))
        self.assertEqual(a.target(right,(406,250),[up,right]),(991,158))
    def test_left_entry_moves_well_inside_without_seeking_outside_floor(self):
        a=DoorApproach();left={'direction':'left','x':63,'y':308};down={'direction':'down','x':985,'y':366}
        self.assertEqual(a.target(down,(136,266),[left,down]),(303,266))
        self.assertEqual(a.target(down,(303,266),[left,down]),(985,321))
    def test_reaching_portal_target_keeps_pushing_until_transition(self):
        approach=DoorApproach();door={'direction':'left','x':46,'y':300}
        target=approach.target(door,(22,294))
        for _ in range(6):target=approach.target(door,target)
        self.assertLess(target[0],0)
    def test_stalled_portal_realigns_inside_nearby_lane(self):
        approach=DoorApproach();door={'direction':'left','x':46,'y':300}
        with patch('dungeon_farm.door_approach.time.monotonic',side_effect=[10,12]):
            approach.target(door,(0,294))
            self.assertEqual(approach.target(door,(0,294)),(106,335))
