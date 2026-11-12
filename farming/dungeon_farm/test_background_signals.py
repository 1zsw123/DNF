import threading
import time
import unittest
from types import SimpleNamespace
from dungeon_farm.background_signals import BackgroundSignals

class BackgroundTests(unittest.TestCase):
    def test_paused_worker_does_not_query_game_and_resumes(self):
        initialized=threading.Event();polled=threading.Event();queries=[]
        class FakeScreen:
            def __init__(self):initialized.set()
            def poll(self,*args,**kwargs):polled.set();return {'dead':False}
            def close(self):pass
        control=SimpleNamespace(stop=threading.Event(),paused=threading.Event())
        control.paused.set()
        win=SimpleNamespace(game=lambda:queries.append(1) or 1,foreground=lambda _:True)
        screen=BackgroundSignals(win,control,FakeScreen)
        try:
            self.assertTrue(initialized.wait(1))
            self.assertFalse(polled.wait(.2));self.assertEqual(queries,[])
            control.paused.clear()
            self.assertTrue(polled.wait(1));self.assertTrue(queries)
        finally:screen.close()

    def test_result_finishing_after_pause_is_not_published(self):
        entered=threading.Event();finish=threading.Event();returned=threading.Event()
        class FakeScreen:
            def poll(self,*args,**kwargs):
                entered.set();finish.wait(2);returned.set();return {'dead':True}
            def close(self):pass
        control=SimpleNamespace(stop=threading.Event(),paused=threading.Event())
        screen=BackgroundSignals(SimpleNamespace(game=lambda:1,foreground=lambda _:True),control,FakeScreen)
        try:
            self.assertTrue(entered.wait(1));control.paused.set();finish.set()
            self.assertTrue(returned.wait(1))
            screen.close()
            self.assertIsNone(screen.read())
        finally:finish.set();screen.close()

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
