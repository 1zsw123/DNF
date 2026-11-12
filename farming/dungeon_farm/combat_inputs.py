"""Normal scan-code input for the configured hotbar and verified recovery item."""
import time
from follow import C, INPUT, KEYBDINPUT
from dungeon_farm.planner import VERIFIED_BUFF_COMMANDS

FREE_ATTACKS = {'x': 0x2d, 'a': 0x1e, 's': 0x1f}
HOTBAR = dict(FREE_ATTACKS,q=0x10,w=0x11,e=0x12,r=0x13,t=0x14,y=0x15,d=0x20,f=0x21,g=0x22,h=0x23)


class CombatInputs:
    def __init__(self, window, all_skills=False):
        self.window = window
        self.all_skills=all_skills
        self.allowed={**HOTBAR,'1':0x02,'2':0x03,'3':0x04,'4':0x05,'c':0x2e} if all_skills else FREE_ATTACKS

    def tap(self, key, hwnd, cancelled=lambda: False):
        if key not in self.allowed:
            raise ValueError('禁止无色技能和未验证按键：' + key)
        return self._tap_scan(self.allowed[key],key,hwnd,cancelled)

    def cast(self,skill,hwnd,cancelled=lambda:False):
        if not skill.input_sequence:return self.tap(skill.key,hwnd,cancelled)
        if not self.all_skills or skill.mode!='entry_buff' or skill.input_sequence not in VERIFIED_BUFF_COMMANDS:
            raise ValueError('未验证的技能指令')
        scans={'right':0x4d,'down':0x50,'space':0x39,'z':0x2c}
        for key in skill.input_sequence:
            scan=scans[key]
            if not self._tap_scan(scan,key,hwnd,cancelled):return False
            time.sleep(.055)
        return True

    def _tap_scan(self,scan,key,hwnd,cancelled):
        if cancelled() or not self.window.foreground(hwnd):
            return False
        self.window.release()
        inp = INPUT(type=1)
        flags=0x0008|(0x0001 if key in ('right','down') else 0)
        inp.ki = KEYBDINPUT(0, scan, flags, 0, 0)
        if self.window.u.SendInput(1,C.byref(inp),C.sizeof(inp)) != 1:
            raise OSError('技能输入失败')
        try:
            deadline=time.monotonic()+(.04 if key == 'x' else .18 if key in ('q','w','e','y','c','h','f') else .12)
            while time.monotonic()<deadline and not cancelled() and self.window.foreground(hwnd):
                time.sleep(.01)
        finally:
            inp.ki.dwFlags=flags|0x0002
            if self.window.u.SendInput(1,C.byref(inp),C.sizeof(inp)) != 1:
                raise OSError('技能松键失败')
        return True
