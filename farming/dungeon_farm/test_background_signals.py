import threading
import time
import unittest
from types import SimpleNamespace
from dungeon_farm.background_signals import BackgroundSignals

class BackgroundTests(unittest.TestCase):
    def test_slow_ocr_does_not_block_combat_and_stale_focus_is_rejected(self):
        entered=threading.Event();finish=threading.Event();closed=threading.Event()
        class FakeScreen:
            def poll(self,*args,**kwargs):
                entered.set();finish.wait(2);return {'dead':False}
            def close(self):closed.set()
        win=SimpleNamespace(game=lambda:1,foreground=lambda _:True)
        control=SimpleNamespace(stop=threading.Event(),paused=threading.Event())
        screen=BackgroundSignals(win,control,FakeScreen)
        try:
            self.assertTrue(entered.wait(1));start=time.monotonic()
            self.assertIsNone(screen.read());self.assertLess(time.monotonic()-start,.1)
            time.sleep(.02)
            resume=time.monotonic();finish.set()
            for _ in range(100):
                if screen.latest:break
                time.sleep(.001)
            self.assertIsNotNone(screen.read())
            self.assertIsNone(screen.read(after=resume))
        finally:finish.set();screen.close()
        self.assertTrue(closed.is_set())
