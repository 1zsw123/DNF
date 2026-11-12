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

    def test_stale_death_cannot_fail_or_retry_a_successful_revive(self):
        r=Revival();r.observe(True,1);r.sent(2)
        self.assertEqual(r.action(5),'waiting_revive')
        r.observe(True,3)
        self.assertEqual(r.action(8),'waiting_revive')
        self.assertTrue(r.observe(False,7))
        self.assertIsNone(r.action(8))
        self.assertFalse(r.observe(True,4))
        self.assertIsNone(r.action(9))

    def test_fresh_dead_frames_allow_bounded_retry(self):
        r=Revival();r.observe(True,1);r.sent(2)
        r.observe(True,5);self.assertEqual(r.action(6),'revive');r.sent(6)
        r.observe(True,9);self.assertEqual(r.action(10),'revive_failed')

    def test_missing_screen_eventually_reports_unconfirmed_not_failed(self):
        r=Revival();r.observe(True,1);r.sent(2)
        self.assertEqual(r.action(22),'revive_unconfirmed')

    def test_focus_loss_does_not_exhaust_revive_timeout(self):
        r=Revival();r.observe(True,1);r.sent(2)
        r.suspend(40)
        self.assertEqual(r.action(41),'waiting_revive')
        self.assertEqual(r.attempts,1)
        self.assertTrue(r.observe(False,41));self.assertIsNone(r.action(42))
