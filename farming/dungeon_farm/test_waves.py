import unittest
from dungeon_farm.waves import WaveTracker

class WaveTests(unittest.TestCase):
    def test_confirmation_budget_is_ten_seconds_and_restarts_after_new_wave(self):
        w=WaveTracker();w.update(False,20)
        self.assertFalse(w.confirmation_timed_out(29.99))
        self.assertTrue(w.confirmation_timed_out(30))
        w.update(True,31)
        self.assertFalse(w.confirmation_timed_out(40))
        w.update(False,41);w.suspend()
        self.assertFalse(w.confirmation_timed_out(60))
    def test_delayed_second_wave_cancels_ready_exit(self):
        w=WaveTracker()
        self.assertEqual(w.update(True,0),(False,False))
        self.assertFalse(w.update(False,1)[0])
        self.assertFalse(w.update(False,4.4)[0])
        self.assertTrue(w.update(False,4.5)[0])
        self.assertEqual(w.update(True,6),(False,True))
        self.assertEqual(w.number,2)
        self.assertFalse(w.update(False,7)[0])
        self.assertFalse(w.update(False,10.4)[0])
        self.assertTrue(w.update(False,10.5)[0])

    def test_pause_and_room_change_discard_empty_confirmation(self):
        w=WaveTracker();w.update(False,1)
        w.suspend()
        self.assertFalse(w.update(False,20)[0])
        w.update(True,22)
        self.assertEqual(w.number,2)
        w.reset()
        self.assertEqual(w.number,1)
        self.assertFalse(w.update(False,30)[0])


class ShortSettleTests(unittest.TestCase):
    def test_solo_settle_is_short_but_late_spawn_still_revokes(self):
        from dungeon_farm.waves import WaveTracker
        w=WaveTracker(settle_seconds=.8)
        self.assertEqual(w.update(False,0),(False,False))
        self.assertEqual(w.update(False,.8),(True,False))
        self.assertEqual(w.update(True,1.0),(False,True))
