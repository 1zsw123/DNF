"""Normal scan-code input for the configured hotbar and verified recovery item."""
import time
from follow import C, INPUT, KEYBDINPUT

FREE_ATTACKS = {'x': 0x2d, 'a': 0x1e, 's': 0x1f}
HOTBAR = dict(FREE_ATTACKS,q=0x10,w=0x11,e=0x12,r=0x13,t=0x14,y=0x15,d=0x20,f=0x21,g=0x22,h=0x23)


class CombatInputs:
    def __init__(self, window, all_skills=False):
        self.window = window
        self.allowed={**HOTBAR,'3':0x04} if all_skills else FREE_ATTACKS

    def tap(self, key, hwnd, cancelled=lambda: False):
        if key not in self.allowed:
            raise ValueError('禁止无色技能和未验证按键：' + key)
        if cancelled() or not self.window.foreground(hwnd):
            return False
        self.window.release()
        inp = INPUT(type=1)
        inp.ki = KEYBDINPUT(0, self.allowed[key], 0x0008, 0, 0)
        if self.window.u.SendInput(1,C.byref(inp),C.sizeof(inp)) != 1:
            raise OSError('技能输入失败')
        try:
            deadline=time.monotonic()+(.04 if key == 'x' else .08)
            while time.monotonic()<deadline and not cancelled() and self.window.foreground(hwnd):
                time.sleep(.01)
        finally:
            inp.ki.dwFlags=0x0008|0x0002
            if self.window.u.SendInput(1,C.byref(inp),C.sizeof(inp)) != 1:
                raise OSError('技能松键失败')
        return True
