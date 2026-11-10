import unittest
from dungeon_farm.waves import WaveTracker

class WaveTests(unittest.TestCase):
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
