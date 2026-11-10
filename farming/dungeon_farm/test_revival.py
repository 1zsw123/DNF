import unittest
from dungeon_farm.revival import Revival

class RevivalTests(unittest.TestCase):
    def test_one_press_then_wait_and_bounded_retry(self):
        r=Revival();self.assertIsNone(r.action(0))
        r.observe(True);self.assertEqual(r.action(1),'revive');r.sent(1)
        self.assertEqual(r.action(3),'waiting_revive')
        self.assertEqual(r.action(4),'revive');r.sent(4)
        self.assertEqual(r.action(7),'revive_failed')

    def test_living_frame_resets_only_after_death(self):
        r=Revival();self.assertFalse(r.observe(False))
        r.observe(True);r.sent(1)
        self.assertTrue(r.observe(False));self.assertIsNone(r.action(2))
        r.observe(True);self.assertEqual(r.action(3),'revive')
