import unittest
from types import SimpleNamespace
from dungeon_farm.cycle_inputs import CycleInputs
from follow import C,INPUT
from ctypes import wintypes as W

class InputTests(unittest.TestCase):
    def test_mouse_click_checks_arrival_before_pressing_button(self):
        for actual,should_click in [((300,350),True),((600,500),False)]:
            sent=[]
            def send(n,ptr,size):
                sent.append(C.cast(ptr,C.POINTER(INPUT)).contents.mi.dwFlags);return 1
            def cursor(ptr):
                p=C.cast(ptr,C.POINTER(W.POINT));p.contents.x,p.contents.y=actual;return 1
            u=SimpleNamespace(SendInput=send,GetCursorPos=cursor,GetSystemMetrics=lambda i:{76:0,77:0,78:1920,79:1080}[i])
            w=SimpleNamespace(u=u,foreground=lambda _:True,rect=lambda _:{'left':100,'top':200,'width':640,'height':480})
            keys=CycleInputs(w);keys._hold=lambda *a:True
            if should_click:
                self.assertTrue(keys.click((200,150),1,lambda:False))
                self.assertEqual(sent[-2:],[2,4])
            else:
                self.assertFalse(keys.click((200,150),1,lambda:False))
                self.assertEqual(len(sent),1)

    def make(self,fail=None):
        sent=[]
        def send(n,ptr,size):
            inp=C.cast(ptr,C.POINTER(INPUT)).contents
            sent.append((inp.ki.wScan,inp.ki.dwFlags))
            return 0 if fail==len(sent) else 1
        win=SimpleNamespace(u=SimpleNamespace(SendInput=send),foreground=lambda _:True,release=lambda:None)
        return CycleInputs(win),sent
    def test_alt_d_and_alt_f_release_letters_before_alt(self):
        keys,sent=self.make()
        self.assertTrue(keys.chord('disassemble',1,lambda:False))
        self.assertEqual(sent,[(0x38,8),(0x20,8),(0x20,10),(0x38,10)])
        sent.clear();keys.chord('sell',1,lambda:False)
        self.assertEqual(sent,[(0x38,8),(0x1f,8),(0x1f,10),(0x38,10)])
        sent.clear();keys.chord('repair',1,lambda:False)
        self.assertEqual(sent,[(0x38,8),(0x21,8),(0x21,10),(0x38,10)])
    def test_failed_letter_down_still_releases_alt(self):
        keys,sent=self.make(fail=2)
        with self.assertRaises(OSError):keys.chord('disassemble',1,lambda:False)
        self.assertEqual(sent[-1],(0x38,10))
    def test_cancelled_action_sends_nothing(self):
        keys,sent=self.make()
        self.assertFalse(keys.chord('sell',1,lambda:True))
        self.assertEqual(sent,[])
    def test_replay_is_f10_key_down_and_up(self):
        keys,sent=self.make();keys.key('retry',1,lambda:False)
        self.assertEqual(sent,[(0x44,8),(0x44,10)])
    def test_panel_focus_change_does_not_resend_a_completed_chord(self):
        keys,sent=self.make()
        keys.win.foreground=lambda _:len(sent)<2
        self.assertTrue(keys.chord('disassemble',1,lambda:False))
        self.assertEqual(sent,[(0x38,8),(0x20,8),(0x20,10),(0x38,10)])
