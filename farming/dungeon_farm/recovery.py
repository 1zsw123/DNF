"""Leave the current dungeon to town with normal input, so a run can re-enter.

Only text read on screen is ever clicked: the 返回城镇 option of the game
menu (Esc) or of the result menu, then 确定/确认 on a dialog that mentions
城镇. Nothing else (in particular never 退出游戏 / 选择角色) is clicked.
"""
import json
import time
from pathlib import Path

EXIT_WORDS = ('返回城镇', '回到城镇', '返回城市')
CONFIRM_WORDS = ('确定', '确认')
FORBIDDEN = ('退出游戏', '选择角色', '结束游戏')
RECOVERABLE = {'error', 'no_path', 'minimap_timeout', 'time_limit', 'revive_failed', 'revive_unconfirmed',
               'returned_town', 'stuck', 'unknown_monsters', 'replay_failed', 'replay_timeout',
               'wrong_dungeon', 'entry_failed', 'difficulty_unconfirmed'}


def pick(found, words, min_conf=.7):
    """Centre of the first confident OCR item that is exactly one of ``words``
    (or starts with it), excluding anything that names a forbidden action."""
    for point, text, conf in found or []:
        if conf < min_conf or any(f in text for f in FORBIDDEN):
            continue
        if any(text == w or text.startswith(w) for w in words):
            return point
    return None


def plan(found, clicked_exit):
    """Pure decision from one OCR reading: ('click', point) | ('confirm', point) | ('escape', None)."""
    joined = ''.join(t for _, t, c in found or [] if c >= .7)
    if clicked_exit and '城镇' in joined:
        confirm = pick(found, CONFIRM_WORDS)
        if confirm:
            return 'confirm', confirm
    target = pick(found, EXIT_WORDS)
    if target:
        return 'click', target
    return 'escape', None


def leave_dungeon(control, report, timeout=40):
    from ctypes import wintypes as W
    from follow import Windows, C
    from coordinate_connection import CoordinateConnection
    from dungeon_farm.characters import selected_profile
    from dungeon_farm.combat_telemetry import connect_solo
    from dungeon_farm.cycle_inputs import CycleInputs
    from dungeon_farm.screen_signals import ScreenSignals
    win = Windows();keys = CycleInputs(win);screen = ScreenSignals()
    win.u.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]
    conn = CoordinateConnection(selected_profile(control.character), connector=connect_solo)
    escapes = 0;clicked = 0;started = time.monotonic();seen = []
    note = Path(__file__).with_name('recovery-observation.json')
    try:
        win.release()
        while not control.stop.is_set() and time.monotonic()-started < timeout:
            if control.paused.is_set():
                report({'state':'paused'});control.stop.wait(.2);continue
            hwnd = win.game()
            if not hwnd or not win.foreground(hwnd):
                report({'state':'waiting_foreground'});control.stop.wait(.2);continue
            pid = W.DWORD();win.u.GetWindowThreadProcessId(hwnd, C.byref(pid))
            conn.sample(pid.value)
            reader = conn.reader
            base = reader.uint(reader.local_root) if reader else 0
            if base and reader.uint(base+0xb8) == 0:
                report({'state':'left_dungeon','detail':'已回到城镇'})
                return 'town'
            found = screen.read_texts(win, hwnd)
            if found is None:
                control.stop.wait(.2);continue
            seen = [t for _, t, c in found if c >= .7][:40]
            action, point = plan(found, clicked)
            note.write_text(json.dumps({'time':time.time(),'action':action,'point':point,'texts':seen,
                                        'escapes':escapes,'clicked':clicked},ensure_ascii=False,indent=2),encoding='utf8')
            if action == 'confirm':
                report({'state':'leaving_dungeon','detail':'确认返回城镇'})
                keys.click(point, hwnd, control.cancelled);control.stop.wait(1.5);continue
            if action == 'click':
                report({'state':'leaving_dungeon','detail':'点击返回城镇'})
                if keys.click(point, hwnd, control.cancelled):clicked += 1
                control.stop.wait(1.2);continue
            if escapes >= 4:
                break
            report({'state':'leaving_dungeon','detail':'打开游戏菜单'})
            keys.close_overlay(hwnd, control.cancelled)  # Esc
            escapes += 1
            control.stop.wait(1.0)
        if control.stop.is_set():
            return 'stopped'
        report({'state':'exit_failed','detail':'没找到“返回城镇”，屏幕文字：'+'、'.join(seen[:12])})
        return 'exit_failed'
    finally:
        win.release();conn.close();screen.close()
