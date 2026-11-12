import unittest
from dungeon_farm.town_entry import EntranceAlignment

class EntranceAlignmentTests(unittest.TestCase):
    def test_moving_right_never_triggers_vertical_probe(self):
        a=EntranceAlignment()
        for x in (100,150,200,250):self.assertEqual(a.direction((x,250,0)),'right')

    def test_edge_uses_bounded_alignment_with_right_retry_between_probes(self):
        a=EntranceAlignment()
        self.assertEqual([a.direction((849,250,0)) for _ in range(9)],
                         ['right','up','right','down','right','down','right','right','right'])

    def test_invalid_sample_cannot_create_false_stall(self):
        a=EntranceAlignment()
        self.assertEqual(a.direction(None),'right')
        self.assertEqual(a.direction((float('nan'),250,0)),'right')
        self.assertIsNone(a.previous)
