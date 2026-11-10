"""Input for the explicitly configured post-clear maintenance sequence."""
import time
from ctypes import wintypes as W
from follow import C, INPUT, KEYBDINPUT, MOUSEINPUT

class CycleInputs:
    def __init__(self,win):self.win=win;self.last_chord_state={};self.last_click_state={}
    def _key(self,scan,up=False):
        inp=INPUT(type=1);inp.ki=KEYBDINPUT(0,scan,8|(2 if up else 0),0,0)
        if self.win.u.SendInput(1,C.byref(inp),C.sizeof(inp))!=1:raise OSError('维护按键发送失败')
    def _hold(self,seconds,hwnd,cancelled):
        until=time.monotonic()+seconds
        while time.monotonic()<until:
            if cancelled() or not self.win.foreground(hwnd):return False
            time.sleep(.02)
        return True
    def chord(self,name,hwnd,cancelled):
        scan={'disassemble':0x20,'sell':0x1f,'repair':0x21}[name]
        if cancelled() or not self.win.foreground(hwnd):return False
        self.win.release();modifier_down=False;letter_down=False
        self.last_chord_state={'name':name,'transport':'scan_code','modifier':'Alt'}
        # Let the DirectInput device reacquire after switching from the GUI.
        if not self._hold(.5,hwnd,cancelled):return False
        try:
            self._key(0x38);modifier_down=True
            self.last_chord_state['modifier_down_at']=time.monotonic()
            if not self._hold(.45,hwnd,cancelled):return False
            self._key(scan);letter_down=True
            self.last_chord_state['letter_down_at']=time.monotonic()
            self._hold(.25,hwnd,cancelled)
            # An opened utility panel can legitimately change foreground focus.
            # Once the chord was sent, never resend it just because that happened.
            self.last_chord_state['foreground_after']=bool(self.win.foreground(hwnd))
            return True
        finally:
            try:
                if letter_down:
                    self._key(scan,True)
                    # The game must observe letter-up while Alt is still held.
                    if not cancelled():time.sleep(.2)
            finally:
                if modifier_down:self._key(0x38,True)
    def key(self,name,hwnd,cancelled):
        if name in ('difficulty_left','difficulty_right'):
            if cancelled() or not self.win.foreground(hwnd):return False
            self.win.release();self.win.apply({'left' if name=='difficulty_left' else 'right'},hwnd)
            try:return self._hold(.12,hwnd,cancelled)
            finally:self.win.release()
        scan={'retry':0x44,'select_other':0x57,'enter':0x39,'inventory':0x17,'revive':0x2d}[name]
        if cancelled() or not self.win.foreground(hwnd):return False
        self.win.release();self._key(scan)
        try:time.sleep(.12)
        finally:self._key(scan,True)
        return True
    def close_overlay(self,hwnd,cancelled):
        if cancelled() or not self.win.foreground(hwnd):return False
        self.win.release();self._key(0x01)
        try:time.sleep(.06)
        finally:self._key(0x01,True)
        return True
    def move(self,point,hwnd,cancelled):
        if cancelled() or not self.win.foreground(hwnd):return False
        rect=self.win.rect(hwnd)
        if not rect:return False
        x,y=point
        if not(0<=x<640 and 0<=y<480):raise ValueError('重进按钮坐标超出游戏画面')
        # Convert the OCR's normalized client coordinates to virtual desktop.
        u=self.win.u
        left,top,width,height=(u.GetSystemMetrics(v) for v in (76,77,78,79))
        sx=rect['left']+x*rect['width']/640
        sy=rect['top']+y*rect['height']/480
        move=INPUT(type=0);move.mi=MOUSEINPUT(round((sx-left)*65535/max(1,width-1)),round((sy-top)*65535/max(1,height-1)),0,0x8000|0x4000|1,0,0)
        if u.SendInput(1,C.byref(move),C.sizeof(move))!=1:raise OSError('重进按钮定位失败')
        if not self._hold(.18,hwnd,cancelled):return False
        cursor=W.POINT()
        if not u.GetCursorPos(C.byref(cursor)):raise OSError('无法核对游戏鼠标位置')
        self.last_click_state={'target':[sx,sy],'actual':[cursor.x,cursor.y]}
        if abs(cursor.x-sx)>3 or abs(cursor.y-sy)>3:
            # Re-observe the popup on the next cycle; never press at the wrong
            # location and never terminate the worker for a transient move.
            self.last_click_state['cancelled']='cursor_mismatch'
            return False
        return True
    def click(self,point,hwnd,cancelled):
        if not self.move(point,hwnd,cancelled):return False
        if cancelled() or not self.win.foreground(hwnd):return False
        u=self.win.u
        click=INPUT(type=0);click.mi=MOUSEINPUT(0,0,0,2,0,0)
        if u.SendInput(1,C.byref(click),C.sizeof(click))!=1:raise OSError('重进按钮点击失败')
        try:time.sleep(.04)
        finally:
            click.mi.dwFlags=4
            if u.SendInput(1,C.byref(click),C.sizeof(click))!=1:raise OSError('鼠标松开失败')
        return True
