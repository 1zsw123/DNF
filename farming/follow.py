"""Local visual follower for a visible DNF client. No game memory/network access."""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
import json
import logging
import queue
import re
from pathlib import Path
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox

import cv2
import mss
import numpy as np
from PIL import Image, ImageTk
from tracking import VerifiedFlow

BASE = Path(__file__).resolve().parent
CONFIG = BASE / 'config.json'
ARROWS = {'left': 0x4B, 'right': 0x4D, 'up': 0x48, 'down': 0x50}
VIEW_SIZE = (819, 614)


def enhance_scene(frame):
    """Lift dungeon darkness without changing the HUD or image coordinates."""
    h = frame.shape[0]
    top, bottom = int(h*.16), int(h*.89)
    scene = frame[top:bottom]
    gray = cv2.cvtColor(scene, cv2.COLOR_BGR2GRAY)
    exposure = float(np.percentile(gray, 90))
    transition = float(np.percentile(gray, 99)) < 10
    if exposure >= 90 or transition:
        return frame, False, transition
    gain = min(4.0, 135.0/max(exposure, 35.0))
    result = frame.copy()
    result[top:bottom] = cv2.convertScaleAbs(scene, alpha=gain)
    return result, True, False


def vertical_gate_hint(frame, target):
    if target is None:
        return None
    h,w=frame.shape[:2]
    hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV)
    mask=((hsv[:,:,0]>=80)&(hsv[:,:,0]<=108)&(hsv[:,:,1]>110)&(hsv[:,:,2]>145)).astype(np.uint8)*255
    mask[:int(h*.45)]=0;mask[int(h*.88):]=0
    _,_,stats,centers=cv2.connectedComponentsWithStats(mask)
    crystals=[]
    for (_,_,cw,ch,area),center in zip(stats[1:],centers[1:]):
        if 15<=cw<=45 and 28<=ch<=65 and area>=350 and area/(cw*ch)>.45:
            crystals.append(center)
    candidates=[]
    for i,a in enumerate(crystals):
        for b in crystals[i+1:]:
            left,right=sorted((a[0],b[0]));y=(a[1]+b[1])/2
            if not(70<right-left<230 and abs(a[1]-b[1])<24 and left-20<target[0]<right+20):
                continue
            if y>h*.72 and target[1]>y+12:
                candidates.append((abs(target[0]-(left+right)/2),'down'))
            elif y<h*.68 and y+8<target[1]<y+105:
                candidates.append((abs(target[0]-(left+right)/2),'up'))
    return min(candidates)[1] if candidates else None


def glyphs(bgr):
    """White name lettering with dark outlines, independent of scene colour."""
    lo = bgr.min(axis=2).astype(np.int16)
    hi = bgr.max(axis=2).astype(np.int16)
    return ((lo >= 145) & (hi - lo < 80)).astype(np.uint8) * 255


class Tracker:
    def __init__(self, image, offset=(0, 90)):
        self.template = glyphs(image)
        self.offset = offset
        self.height, self.width = self.template.shape
        self.variants = []
        if self.template.std() < 20:
            raise ValueError('选区中没有清晰的白色名字，请重新框选名字一行。')

    def locate(self, mask, threshold=0.67):
        best = (None, 0.0)
        for tracker in (self, *self.variants):
            result = tracker._locate(mask, threshold)
            if result[1] > best[1]:
                best = result
        return best

    def _locate(self, mask, threshold=0.67):
        h, w = mask.shape
        # Exclude party frames, announcement bar, minimap and bottom action bar.
        top, bottom = int(h * .16), int(h * .89)
        region = mask[top:bottom].copy()
        region[:max(0, int(h * .26) - top), int(w * .87):] = 0
        if region.shape[0] < self.height or w < self.width:
            return None, 0.0
        match = cv2.matchTemplate(region, self.template, cv2.TM_CCOEFF_NORMED)
        _, score, _, point = cv2.minMaxLoc(match)
        if not np.isfinite(score) or score < threshold:
            return None, float(score)
        x, y = point
        return (x + self.width / 2 + self.offset[0],
                y + top + self.height / 2 + self.offset[1]), float(score)


class NameOCR:
    """Read the configured names, then teach the fast tracker the current font."""
    def __init__(self, engine=None):
        if engine is None:
            from rapidocr_onnxruntime import RapidOCR
            engine = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1)
        self.engine = engine

    @staticmethod
    def parse(results, shape, config, scale=1.5, top=0):
        found = {'leader': [], 'self': []}
        h, w = shape[:2]
        aliases = {
            'leader': config.get('leader_names', ['上头狂战']),
            # The OCR model repeatedly reads the final 刃 as 列 at this font size.
            'self': config.get('self_names', ['上头影刃', '上头影列', '上头影刀', '上头影纳']),
        }
        expanded = []
        for result in results or []:
            if len(result) >= 6 and len(result[3]) == len(result[4]):
                boxes, tokens, scores = result[3:6]
                joined = ''.join(tokens)
                for role, names in aliases.items():
                    matched = next((name for name in names if name in joined), None)
                    if not matched:
                        continue
                    start = joined.index(matched)
                    selected, confidences, cursor = [], [], 0
                    for box, token, confidence in zip(boxes, tokens, scores):
                        if cursor < start+len(matched) and cursor+len(token) > start:
                            selected.extend(box)
                            confidences.append(float(confidence))
                        cursor += len(token)
                    if selected and confidences and min(confidences) >= .45:
                        pts = np.asarray(selected, dtype=float)
                        x1,y1 = pts.min(axis=0); x2,y2 = pts.max(axis=0)
                        expanded.append(([[x1,y1],[x2,y1],[x2,y2],[x1,y2]], matched, float(np.mean(confidences))))
            else:
                expanded.append(result[:3])
        for box, text, confidence in expanded:
            if float(confidence) < .65:
                continue
            text = re.sub(r'\s+', '', text)
            if text.count('上头') > 1:
                continue
            roles = [role for role, names in aliases.items() if any(name in text for name in names)]
            # Overlapping nameplates can merge into one OCR box: do not drive on it.
            if len(roles) != 1:
                continue
            role = roles[0]
            points = np.asarray(box, dtype=float) / scale
            points[:, 1] += top
            x1, y1 = points.min(axis=0)
            x2, y2 = points.max(axis=0)
            if y2-y1 > 32 or len(text) > 24:
                continue
            if y1 < h * .16 or y2 > h * .88:
                continue
            if x1 > w * .87 and y1 < h * .26:
                continue
            name_only = any(text.startswith(name) for name in aliases[role])
            dx = float(config.get(role, {}).get('offset', [0, 128])[0]) if name_only else 0
            dy = float(config.get(role, {}).get('offset', [0, 128])[1])
            foot = ((x1+x2)/2 + dx, (y1+y2)/2 + dy)
            crop = (max(0, int(x1)-2), max(0, int(y1)-2),
                    min(w, int(x2)+3), min(h, int(y2)+3))
            found[role].append((foot, float(confidence), crop, text))
        return {role: hits[0] for role, hits in found.items() if len(hits) == 1}

    def locate(self, frame, config):
        h = frame.shape[0]
        top, bottom = int(h*.16), int(h*.88)
        scene = frame[top:bottom].copy()
        # Exclude minimap text; party headers are outside this crop already.
        scene[:max(0, int(h*.26)-top), int(frame.shape[1]*.87):] = 0
        enlarged = cv2.resize(scene, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC)
        results, _ = self.engine(enlarged, use_cls=False, return_word_box=True)
        hits=self.parse(results, frame.shape, config, scale=1.5, top=top)
        if 'self' not in hits:
            partial=self.read_small_name_lines(frame,config)
            if partial is not None:
                hits['self']=partial
        return self.guild_pair_fallback(results,frame,config,hits,scale=1.5,top=top)

    @staticmethod
    def matches_small_identity(text, level):
        # The dense final characters often merge into one OCR character. Require
        # both the local HUD's level and the exact name prefix, not a fuzzy name.
        text=re.sub(r'\s+','',text)
        if not 1<=level<70 or '狂战' in text:
            return False
        return bool(re.search(r'(?<!\d)'+str(level)+r'(?!\d).{0,3}上头',text))

    @staticmethod
    def small_line_proposals(frame):
        gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
        spread=frame.max(2).astype(np.int16)-frame.min(2).astype(np.int16)
        white=((gray>100)&(spread<85)).astype(np.uint8)
        outline=cv2.dilate((gray<75).astype(np.uint8),np.ones((3,3),np.uint8))
        mask=cv2.morphologyEx(white*outline*255,cv2.MORPH_CLOSE,np.ones((2,9),np.uint8))
        h,w=gray.shape
        mask[:int(h*.16)]=0;mask[int(h*.88):]=0
        mask[:int(h*.26),int(w*.87):]=0
        _,_,stats,_=cv2.connectedComponentsWithStats(mask)
        boxes=[]
        for x,y,cw,ch,area in stats[1:]:
            if 35<=cw<=200 and 6<=ch<=24 and area>70:
                mid=int(y+ch/2)
                # Trim nearby scenery without trimming the thin name lettering.
                half=min(7,max(5,int(ch/2)+1))
                boxes.append((max(0,int(x)-3),max(0,mid-half),min(w,int(x+cw)+3),min(h,mid+half)))
        return boxes[:40]

    def read_small_name_lines(self,frame,config):
        h,w=frame.shape[:2]
        hud=frame[int(h*.964):h,int(w*.006):int(w*.083)]
        hud_result,_=self.engine.text_rec([cv2.resize(hud,None,fx=3,fy=3)],False)
        if not hud_result or hud_result[0][1]<.7:
            return None
        digits=re.search(r'(?i)L[vV]?[ .]*(\d{1,2})',hud_result[0][0])
        if not digits:
            return None
        level=int(digits.group(1))
        boxes=self.small_line_proposals(frame)
        if not boxes:
            return None
        crops=[cv2.resize(frame[y1:y2,x1:x2],None,fx=3,fy=3) for x1,y1,x2,y2 in boxes]
        recognized,_=self.engine.text_rec(crops,False)
        candidates=[]
        for box,(text,score,*_) in zip(boxes,recognized):
            if float(score)<.68 or not self.matches_small_identity(text,level):
                continue
            x1,y1,x2,y2=box
            foot=((x1+x2)/2,(y1+y2)/2+float(config.get('self',{}).get('offset',[0,128])[1]))
            if not any(np.hypot(foot[0]-p[0][0],foot[1]-p[0][1])<25 for p in candidates):
                candidates.append((foot,float(score),box,'HUD+prefix:'+text))
        return candidates[0] if len(candidates)==1 else None

    @staticmethod
    def guild_pair_fallback(results, frame, config, hits, scale=1.5, top=0):
        # In a two-person dungeon the identical guild tags can locate the second
        # player when a transparent/frozen effect erases their character name.
        if 'self' in hits or 'leader' not in hits:
            return hits
        h,w=frame.shape[:2]
        minimap=frame[int(h*.085):int(h*.23),int(w*.88):int(w*.99)]
        hsv=cv2.cvtColor(minimap,cv2.COLOR_BGR2HSV)
        blue=((hsv[:,:,0]>80)&(hsv[:,:,0]<115)&(hsv[:,:,1]>90)&(hsv[:,:,2]>40)).sum()
        if minimap.mean()>85 or blue<40:
            return hits
        markers=[]
        for result in results or []:
            if float(result[2])<.65 or '明月清' not in result[1]:
                continue
            pts=np.asarray(result[0],dtype=float)/scale
            pts[:,1]+=top
            x1,y1=pts.min(axis=0);x2,y2=pts.max(axis=0)
            if y1<h*.16 or y2>h*.75:
                continue
            center=((x1+x2)/2,(y1+y2)/2)
            markers.append((center,(center[0],center[1]+146),(int(x1),int(y1),int(x2),int(y2))))
        if len(markers)!=2 or np.hypot(*(np.subtract(markers[0][0],markers[1][0])))<40:
            return hits
        leader=hits['leader'][0]
        distances=[np.hypot(p[1][0]-leader[0],p[1][1]-leader[1]) for p in markers]
        which=int(np.argmin(distances))
        if distances[which]>65 or distances[1-which]<70:
            return hits
        center,foot,box=markers[1-which]
        x,y=map(round,center)
        hits['self']=(foot,.91,box,'guild:明月清风')
        return hits


class FollowPolicy:
    def __init__(self):
        self.last_target = None
        self.last_seen = 0.0
        self.last_keys = set()
        self.stuck_at = None
        self.stuck_since = 0.0
        self.stuck_keys = set()
        self.last_heading = set()
        self.exit_direction = None
        self.retry_until = 0.0
        self.last_own = None
        self.last_own_seen = 0.0

    def reset(self):
        self.__init__()

    @staticmethod
    def edge_direction(target, shape):
        h, w = shape[:2]
        x, y = target
        candidates = []
        if x < w*.12:
            candidates.append((x/(w*.12), 'left'))
        if x > w*.88:
            candidates.append(((w-x)/(w*.12), 'right'))
        return min(candidates)[1] if candidates else None

    def step(self, target, own, shape, now, gap=55, door_grace=4.0, scene_moved=False, exit_hint=None):
        h, w = shape[:2]
        if own is None:
            self.stuck_at = None
            # A clipped name/head on the boundary must not prevent the final door step.
            at_exit = self.last_own and (
                (self.exit_direction == 'left' and self.last_own[0] < w*.12) or
                (self.exit_direction == 'right' and self.last_own[0] > w*.88) or
                (self.exit_direction == 'up' and self.last_own[1] < h*.42) or
                (self.exit_direction == 'down' and self.last_own[1] > h*.81))
            if at_exit and now-self.last_own_seen < .55 and now-self.last_seen < door_grace:
                return {self.exit_direction}, '门口角色暂时被遮挡：短暂继续压门'
            return set(), '找不到小号，等待画面恢复'
        self.last_own,self.last_own_seen=own,now
        if target is None:
            elapsed = now-self.last_seen
            if self.exit_direction and 0 <= elapsed < door_grace:
                keys = {self.exit_direction}
                # Continue to align with the last observed doorway lane.
                if self.exit_direction in ('left', 'right'):
                    dy = self.last_target[1]-own[1]
                    if abs(dy) > 14:
                        keys.add('down' if dy > 0 else 'up')
                elif abs(self.last_target[0]-own[0]) > 20:
                    keys.add('right' if self.last_target[0] > own[0] else 'left')
                note = '大号出屏：沿最后出口方向继续追门'
            elif self.last_target and 0 <= elapsed < min(1.2, door_grace) and self.last_heading:
                keys, note = set(self.last_heading), '大号暂时不可见：沿最近方向短暂寻找'
            else:
                self.stuck_at = None
                return set(), '找不到大号，停止并等待'
        else:
            self.last_target, self.last_seen = target, now
            dx, dy = target[0] - own[0], target[1] - own[1]
            self.exit_direction = exit_hint or self.edge_direction(target, shape)
            near_door = self.exit_direction is not None
            follow_gap = min(gap, 8) if near_door else gap
            keys = set()
            if abs(dx) > follow_gap:
                keys.add('right' if dx > 0 else 'left')
            if abs(dy) > (6 if near_door else 13):
                keys.add('down' if dy > 0 else 'up')
            # A door requires walking into its boundary, not stopping beside the leader.
            if self.exit_direction in ('left', 'right') and abs(dy) <= 18:
                keys.discard('left'); keys.discard('right')
                keys.add(self.exit_direction)
            elif self.exit_direction in ('up', 'down') and abs(dx) <= 22:
                keys.discard('up'); keys.discard('down')
                keys.add(self.exit_direction)
            self.last_keys = set(keys)
            if keys:
                self.last_heading = set(keys)
            note = ('门口：继续向出口移动' if near_door and keys else
                    '跟随：' + '+'.join(sorted(keys)) if keys else '已靠近大号')
        if now < self.retry_until:
            return set(), '原地等待，稍后自动重试'
        # Stop at an obstacle instead of pressing forever. This version has no path planner.
        moved = scene_moved or self.stuck_at is None or np.hypot(own[0]-self.stuck_at[0], own[1]-self.stuck_at[1]) > 9
        if moved or keys != self.stuck_keys or not keys:
            self.stuck_at, self.stuck_since, self.stuck_keys = own, now, set(keys)
        elif now - self.stuck_since > 3.5:
            self.retry_until = now+.65
            self.stuck_since = self.retry_until
            return set(), '可能卡住：短暂停顿后自动重试，可直接手动绕开'
        return keys, note


class MOUSEINPUT(C.Structure):
    _fields_ = [('dx', W.LONG), ('dy', W.LONG), ('mouseData', W.DWORD),
                ('dwFlags', W.DWORD), ('time', W.DWORD), ('dwExtraInfo', C.c_size_t)]


class KEYBDINPUT(C.Structure):
    _fields_ = [('wVk', W.WORD), ('wScan', W.WORD), ('dwFlags', W.DWORD),
                ('time', W.DWORD), ('dwExtraInfo', C.c_size_t)]


class HARDWAREINPUT(C.Structure):
    _fields_ = [('uMsg', W.DWORD), ('wParamL', W.WORD), ('wParamH', W.WORD)]


class INPUTUNION(C.Union):
    _fields_ = [('ki', KEYBDINPUT), ('mi', MOUSEINPUT), ('hi', HARDWAREINPUT)]


class INPUT(C.Structure):
    _anonymous_ = ('u',)
    _fields_ = [('type', W.DWORD), ('u', INPUTUNION)]


class Windows:
    def __init__(self):
        self.u = C.WinDLL('user32', use_last_error=True)
        self.u.FindWindowW.argtypes = [W.LPCWSTR, W.LPCWSTR]
        self.u.FindWindowW.restype = W.HWND
        self.u.GetForegroundWindow.restype = W.HWND
        self.u.GetClientRect.argtypes = [W.HWND, C.POINTER(W.RECT)]
        self.u.ClientToScreen.argtypes = [W.HWND, C.POINTER(W.POINT)]
        self.u.IsIconic.argtypes = [W.HWND]
        self.u.SendInput.argtypes = [W.UINT, C.POINTER(INPUT), C.c_int]
        self.u.SendInput.restype = W.UINT
        self.u.SetProcessDPIAware()
        self.lock = threading.RLock()
        self.held = set()

    def game(self):
        return self.u.FindWindowW(None, '地下城与勇士')

    def rect(self, hwnd):
        r, p = W.RECT(), W.POINT(0, 0)
        if not hwnd or self.u.IsIconic(hwnd) or not self.u.GetClientRect(hwnd, C.byref(r)):
            return None
        if not self.u.ClientToScreen(hwnd, C.byref(p)) or r.right < 400 or r.bottom < 300:
            return None
        return {'left': p.x, 'top': p.y, 'width': r.right, 'height': r.bottom}

    def foreground(self, hwnd):
        return bool(hwnd) and self.u.GetForegroundWindow() == hwnd

    def manual_arrows(self):
        with self.lock:
            return {key for key, vk in (('left',0x25),('up',0x26),('right',0x27),('down',0x28))
                    if key not in self.held and self.u.GetAsyncKeyState(vk) & 0x8000}

    def send(self, key, up=False):
        inp = INPUT(type=1)
        inp.ki = KEYBDINPUT(0, ARROWS[key], 0x0008 | 0x0001 | (0x0002 if up else 0), 0, 0)
        if self.u.SendInput(1, C.byref(inp), C.sizeof(inp)) != 1:
            raise OSError('方向键发送失败；游戏和工具可能权限不同。')

    def release(self):
        with self.lock:
            for key in list(self.held):
                self.send(key, up=True)
                self.held.discard(key)

    def apply(self, keys, hwnd, run=False):
        with self.lock:
            if not self.foreground(hwnd):
                self.release()
                return
            for key in self.held - keys:
                self.send(key, up=True)
            self.held.intersection_update(keys)
            for key in keys - self.held:
                # Re-check immediately before each key down.
                if not self.foreground(hwnd):
                    self.release()
                    return
                if run and key in ('left','right'):
                    self.send(key)
                    self.held.add(key)
                    time.sleep(.03)
                    self.send(key,up=True)
                    self.held.discard(key)
                    time.sleep(.03)
                    if not self.foreground(hwnd):
                        self.release()
                        return
                self.send(key)
                self.held.add(key)


class Selector(tk.Toplevel):
    def __init__(self, owner, frame, role, done):
        super().__init__(owner)
        self.title(('大号' if role == 'leader' else '小号') + '：框选名字，再点角色脚底')
        self.attributes('-topmost', True)
        self.frame, self.role, self.done = frame, role, done
        self.phase, self.start, self.box = 0, None, None
        self.label = ttk.Label(self, text='第1步：拖框只圈住角色名字那一行（不要圈公会、称号和等级）。')
        self.label.pack(pady=8)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        self.photo = ImageTk.PhotoImage(Image.fromarray(rgb))
        self.canvas = tk.Canvas(self, width=frame.shape[1], height=frame.shape[0], highlightthickness=0)
        self.canvas.pack()
        self.canvas.create_image(0, 0, image=self.photo, anchor='nw')
        self.canvas.bind('<ButtonPress-1>', self.down)
        self.canvas.bind('<B1-Motion>', self.move)
        self.canvas.bind('<ButtonRelease-1>', self.up)
        self.bind('<Escape>', lambda e: self.destroy())

    def down(self, event):
        if self.phase == 1:
            x1, y1, x2, y2 = self.box
            if not (0 <= event.x < self.frame.shape[1] and 0 <= event.y < self.frame.shape[0]):
                return
            offset = (event.x - (x1+x2)/2, event.y - (y1+y2)/2)
            self.done(self.role, self.frame[y1:y2, x1:x2].copy(), offset, self.frame.shape)
            self.destroy()
        else:
            self.start = (event.x, event.y)

    def move(self, event):
        if self.phase == 0 and self.start:
            self.canvas.delete('selection')
            self.canvas.create_rectangle(*self.start, event.x, event.y, outline='#00ff80', width=2, tags='selection')

    def up(self, event):
        if self.phase != 0 or not self.start:
            return
        h, w = self.frame.shape[:2]
        x1, x2 = sorted((max(0, min(w, self.start[0])), max(0, min(w, event.x))))
        y1, y2 = sorted((max(0, min(h, self.start[1])), max(0, min(h, event.y))))
        if not (18 <= x2-x1 <= 210 and 7 <= y2-y1 <= 38):
            self.label.configure(text='选区应为名字一行，宽18～210、高7～38像素，请重新框选。')
            self.start = None
            return
        self.box = (x1, y1, x2, y2)
        self.phase = 1
        self.label.configure(text='第2步：点一下这个角色脚底接触地面的位置，用来校准跟随距离。')


class App:
    def __init__(self):
        self.win = Windows()
        self.root = tk.Tk()
        self.root.title('DNF 小号跟随 · 本地试用版')
        self.root.geometry('560x540')
        self.root.resizable(False, False)
        self.enabled = threading.Event()
        self.closed = threading.Event()
        self.policy = FollowPolicy()
        self.trackers, self.config = {}, {'gap': 85, 'threshold': .67, 'door_grace': 4.0, 'auto_run': True}
        self.state_lock = threading.RLock()
        self.status_text = '先采集大号和小号的名字；保持游戏窗口大小不变。'
        self.debug_frame = None
        self.show_debug = tk.BooleanVar(value=False)
        self.preview = None
        self.capture_role = None
        self.preview_only = False
        self.last_detection = ''
        self.last_diagnostic = 0.0
        self.last_state_write = 0.0
        self.last_hotkey = ''
        self.ocr = None
        self.ocr_attempted = False
        self.last_ocr = 0.0
        self.manual_until = 0.0
        self.vision_epoch = 0
        self.ocr_jobs = queue.Queue(maxsize=1)
        self.ocr_results = queue.Queue(maxsize=1)
        self.ocr_busy = threading.Event()
        self.previous_scene = None
        self.scene_window = cv2.createHanningWindow((160,90), cv2.CV_32F)
        self.own_flow=VerifiedFlow()
        self.load()
        if len(self.trackers) == 2:
            self.status_text = '两个人的名字已载入。进副本后按 F8 开始，F9 停止。'
        panel = ttk.Frame(self.root, padding=18)
        panel.pack(fill='both', expand=True)
        ttk.Label(panel, text='小号跟着大号走', font=('Microsoft YaHei UI', 18, 'bold')).pack(anchor='w')
        ttk.Label(panel, text='仅识别游戏画面；只按方向键。需要游戏在前台。').pack(anchor='w', pady=(4, 14))
        row = ttk.Frame(panel)
        row.pack(fill='x')
        ttk.Button(row, text='① 采集大号名字', command=lambda: self.prepare_capture('leader')).pack(side='left', padx=(0, 12))
        ttk.Button(row, text='② 采集小号名字', command=lambda: self.prepare_capture('self')).pack(side='left')
        self.ready_label = ttk.Label(panel)
        self.ready_label.pack(anchor='w', pady=8)
        self.running_label = ttk.Label(panel, font=('Microsoft YaHei UI', 11, 'bold'))
        self.running_label.pack(anchor='w', pady=(0, 6))
        ttk.Label(panel, text='采集：点击后有3秒切回游戏，随后在截图上框名字、点脚底。\n建议在副本中采集，两人站开，名字不要重叠。').pack(anchor='w')
        controls = ttk.Frame(panel)
        controls.pack(fill='x', pady=14)
        ttk.Button(controls, text='准备开始 / 暂停  F8', command=self.toggle).pack(side='left', padx=(0, 10))
        ttk.Button(controls, text='立即停止  F9', command=self.stop).pack(side='left')
        ttk.Checkbutton(panel, text='识别预览（预览窗口不要盖住游戏）', variable=self.show_debug).pack(anchor='w')
        self.dry_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(panel, text='只检测名字，不发送方向键', variable=self.dry_var,
                        command=self.change_dry_run).pack(anchor='w')
        self.status = ttk.Label(panel, text='', wraplength=515, font=('Microsoft YaHei UI', 10))
        self.status.pack(anchor='w', pady=14)
        ttk.Label(panel, text='方向键手动操作后自动接回；F9停止。\n暗场自动增强，出屏限时追门；复杂障碍仍可手动绕开。', foreground='#666666').pack(anchor='w')
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.register_hotkeys()
        self.ocr_thread = threading.Thread(target=self.ocr_loop, daemon=True)
        self.ocr_thread.start()
        self.worker = threading.Thread(target=self.loop, daemon=True)
        self.worker.start()
        if '--observe' in sys.argv:
            self.preview_only = True
            self.dry_var.set(True)
            if len(self.trackers) == 2:
                self.enabled.set()
        self.root.after(80, self.tick)

    def load(self):
        if not CONFIG.exists():
            return
        try:
            self.config.update(json.loads(CONFIG.read_text(encoding='utf-8')))
            for role in ('leader', 'self'):
                p = BASE / (role + '.png')
                if p.exists() and role in self.config:
                    im = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
                    self.trackers[role] = Tracker(im, self.config[role]['offset'])
                    for variant in self.config[role].get('variants', []):
                        vi = cv2.imdecode(np.fromfile(BASE / variant['file'], dtype=np.uint8), cv2.IMREAD_COLOR)
                        self.trackers[role].variants.append(Tracker(vi, variant['offset']))
        except Exception:
            logging.exception('load config')
            self.trackers = {}

    def register_hotkeys(self):
        # Tk consumes unhandled thread messages: own the hotkeys in a dedicated
        # message thread and pass commands to Tk through a queue.
        self.hotkey_queue = queue.Queue()
        self.hotkey_ready = threading.Event()
        self.hotkey_error = None
        self.hotkey_thread_id = None
        self.hotkey_thread = threading.Thread(target=self.hotkey_loop, daemon=True)
        self.hotkey_thread.start()
        if not self.hotkey_ready.wait(3):
            raise RuntimeError('热键线程启动超时。')
        if self.hotkey_error:
            raise RuntimeError(self.hotkey_error)

    def hotkey_loop(self):
        self.hotkey_thread_id = C.windll.kernel32.GetCurrentThreadId()
        registered = []
        try:
            for ident, vk in ((1, 0x77), (2, 0x78), (3, 0x75), (4, 0x76)):
                if not self.win.u.RegisterHotKey(None, ident, 0x4000, vk):
                    self.hotkey_error = 'F6～F9 已被其他工具占用，请关闭重复运行的跟随工具。'
                    return
                registered.append(ident)
            self.hotkey_ready.set()
            msg = W.MSG()
            while self.win.u.GetMessageW(C.byref(msg), None, 0, 0) > 0:
                if msg.message == 0x0312:
                    self.hotkey_queue.put(int(msg.wParam))
        finally:
            self.hotkey_ready.set()
            for ident in registered:
                self.win.u.UnregisterHotKey(None, ident)

    def prepare_capture(self, role):
        self.stop()
        self.capture_role = role
        self.status_text = '3秒后截图：现在请切回游戏，让两个人名字清晰可见。'
        self.root.iconify()
        self.root.after(3000, lambda: self.capture(role))

    def capture(self, role):
        if self.capture_role != role:
            return
        self.capture_role = None
        hwnd = self.win.game()
        rect = self.win.rect(hwnd)
        if not rect or not self.win.foreground(hwnd):
            self.status_text = '采集取消：游戏必须在前台且不能最小化。'
            return
        with mss.mss() as cap:
            frame = np.array(cap.grab(rect))[:, :, :3]
        self.config['native_shape'] = list(frame.shape[:2])
        frame = cv2.resize(frame, VIEW_SIZE, interpolation=cv2.INTER_AREA)
        cv2.imencode('.png', frame)[1].tofile(BASE / ('capture_' + role + '.png'))
        Selector(self.root, frame, role, self.selected)

    def change_dry_run(self):
        self.stop()
        self.preview_only = self.dry_var.get()

    def selected(self, role, image, offset, shape):
        try:
            tracker = Tracker(image, offset)
            other = 'self' if role == 'leader' else 'leader'
            if other in self.config and list(shape[:2]) != self.config[other]['shape']:
                raise ValueError('两次采集的游戏尺寸不同，请保持尺寸一致后重新采集。')
            with self.state_lock:
                previous = self.config.get(role, {})
                variants = list(previous.get('variants', []))
                if role in self.trackers and (BASE / (role + '.png')).exists():
                    variant_name = role + '_variant_' + str(time.time_ns()) + '.png'
                    (BASE / variant_name).write_bytes((BASE / (role + '.png')).read_bytes())
                    variants.append({'file': variant_name, 'offset': previous['offset']})
                variants = variants[-4:]
                for variant in variants:
                    vi = cv2.imdecode(np.fromfile(BASE / variant['file'], dtype=np.uint8), cv2.IMREAD_COLOR)
                    tracker.variants.append(Tracker(vi, variant['offset']))
                self.trackers[role] = tracker
                self.config[role] = {'offset': list(offset), 'shape': list(shape[:2]), 'variants': variants}
                cv2.imencode('.png', image)[1].tofile(BASE / (role + '.png'))
                CONFIG.write_text(json.dumps(self.config, ensure_ascii=False, indent=2), encoding='utf-8')
            self.status_text = ('大号' if role == 'leader' else '小号') + '名字已保存。两项采集完后回到副本按 F8。'
        except Exception as e:
            self.status_text = str(e)

    def stop(self):
        self.enabled.clear()
        self.vision_epoch += 1
        self.capture_role = None
        # Release without waiting for a slower OCR pass to finish.
        self.win.release()
        with self.state_lock:
            self.policy.reset()
            self.own_flow.clear()
            self.previous_scene=None
        self.status_text = '已停止，方向键已松开。F8 重新开始。'

    def toggle(self):
        if self.enabled.is_set():
            self.stop()
        elif len(self.trackers) != 2:
            self.status_text = '需要先采集大号和小号名字。'
        else:
            with self.state_lock:
                self.load()
                self.policy.reset()
                self.enabled.set()
            if not self.worker.is_alive():
                self.worker = threading.Thread(target=self.loop, daemon=True)
                self.worker.start()
            self.status_text = '已准备，回到游戏后开始跟随。F9 立即停止。'

    def learn_name(self, role, frame, hit):
        foot, score, box, text = hit
        if text.startswith('guild:'):
            return
        x1, y1, x2, y2 = box
        patch = frame[y1:y2, x1:x2].copy()
        if patch.shape[0] < 7 or patch.shape[1] < 18:
            return
        try:
            learned = Tracker(patch, (foot[0]-(x1+x2)/2, foot[1]-(y1+y2)/2))
            tracker = self.trackers[role]
            tracker.variants.append(learned)
            tracker.variants = tracker.variants[-10:]
            logging.info('OCR reacquired %s: %s score %.3f', role, text, score)
        except ValueError:
            pass

    def ocr_loop(self):
        """Slow name reading must not interrupt motion or block F9/manual input."""
        while not self.closed.is_set():
            try:
                job = self.ocr_jobs.get(timeout=.2)
            except queue.Empty:
                continue
            epoch, hwnd, started, frame, config = job
            try:
                if self.ocr is None:
                    self.ocr = NameOCR()
                hits = self.ocr.locate(frame, config)
                result = (epoch, hwnd, started, frame, hits)
                if self.ocr_results.full():
                    self.ocr_results.get_nowait()
                self.ocr_results.put_nowait(result)
            except Exception:
                logging.exception('Background OCR failed')
            finally:
                self.ocr_busy.clear()

    def loop(self):
        try:
            with mss.mss() as cap:
                while not self.closed.wait(.07):
                    with self.state_lock:
                        if not self.enabled.is_set():
                            self.win.release()
                            continue
                        hwnd = self.win.game()
                        rect = self.win.rect(hwnd)
                        if not rect or not self.win.foreground(hwnd):
                            self.win.release()
                            self.policy.reset()
                            self.vision_epoch += 1
                            self.status_text = '已准备：切回游戏继续；F9 停止。' + self.last_detection
                            continue
                        if self.win.manual_arrows():
                            self.manual_until = time.monotonic()+.55
                        if time.monotonic() < self.manual_until:
                            self.win.release()
                            self.policy.reset()
                            self.vision_epoch += 1
                            self.own_flow.clear()
                            self.status_text = '手动操作中：松开方向键后自动接回跟随'
                            continue
                        frame = np.array(cap.grab(rect))[:, :, :3]
                        if list(frame.shape[:2]) != self.config.get('native_shape', list(frame.shape[:2])):
                            self.win.release()
                            if abs(frame.shape[1]/frame.shape[0] - 4/3) > .05:
                                self.enabled.clear()
                                self.status_text = '窗口比例变了：请使用4:3游戏窗口，再按 F8。'
                                continue
                            self.config['native_shape'] = list(frame.shape[:2])
                            self.policy.reset()
                        frame = cv2.resize(frame, VIEW_SIZE, interpolation=cv2.INTER_AREA)
                        frame, dark, transition = enhance_scene(frame)
                        if transition:
                            self.win.release()
                            self.policy.reset()
                            self.vision_epoch += 1
                            self.previous_scene = None
                            self.own_flow.clear()
                            self.status_text = '画面正在切换：等待亮起后自动恢复'
                            continue
                        scene_gray = cv2.cvtColor(frame[110:520,40:710], cv2.COLOR_BGR2GRAY)
                        scene_gray = cv2.resize(scene_gray,(160,90)).astype(np.float32)
                        scene_moved = False
                        if self.previous_scene is not None:
                            shift, response = cv2.phaseCorrelate(self.previous_scene,scene_gray,self.scene_window)
                            scene_moved = response > .15 and .25 < np.hypot(*shift) < 25
                        self.previous_scene = scene_gray
                        # Manual Enter/Escape pauses immediately rather than driving through menus/chat.
                        if any(self.win.u.GetAsyncKeyState(vk) & 0x8000 for vk in (0x0D, 0x1B)):
                            self.enabled.clear()
                            self.win.release()
                            self.policy.reset()
                            self.status_text = '检测到聊天/菜单按键，已暂停。关闭后按 F8 恢复。'
                            continue
                        mask = glyphs(frame)
                        target, ts = self.trackers['leader'].locate(mask, self.config['threshold'])
                        own, ss = self.trackers['self'].locate(mask, max(.8,self.config['threshold']))
                        while not self.ocr_results.empty():
                            epoch, source_hwnd, started, source, hits = self.ocr_results.get_nowait()
                            age = time.monotonic()-started
                            if epoch != self.vision_epoch or source_hwnd != hwnd or age > 6:
                                continue
                            for role, hit in hits.items():
                                self.learn_name(role, source, hit)
                                if role == 'self':
                                    self.own_flow.seed(source,hit[2],hit[0],started)
                                point, score = self.trackers[role].locate(mask, self.config['threshold'])
                                if point is None and age < .9:
                                    point, score = hit[0], hit[1]
                                if role == 'leader' and target is None:
                                    target, ts = point, score
                                elif role == 'self' and own is None:
                                    own, ss = point, score
                        now = time.monotonic()
                        anchor_used=False
                        flow_point,flow_score=self.own_flow.update(frame,now)
                        if flow_point is not None:
                            own,ss=flow_point,flow_score
                            anchor_used=True
                        refresh_flow=self.own_flow.points is not None and now-self.own_flow.verified>.8
                        if (target is None or own is None or refresh_flow) and now-self.last_ocr >= .5 and not self.ocr_busy.is_set():
                            self.ocr_busy.set()
                            self.ocr_jobs.put_nowait((self.vision_epoch, hwnd, now, frame.copy(), self.config.copy()))
                            self.last_ocr = now
                        if target and own and np.hypot(target[0]-own[0], target[1]-own[1]) < 3:
                            target = None  # ambiguous overlap: never drive on a duplicate match
                        keys, note = self.policy.step(target, own, frame.shape, time.monotonic(), self.config['gap'], self.config['door_grace'], scene_moved=scene_moved, exit_hint=vertical_gate_hint(frame,target))
                        if self.preview_only:
                            self.policy.stuck_since = time.monotonic()
                        if self.win.manual_arrows():
                            self.manual_until = time.monotonic()+.55
                            self.win.release()
                            self.policy.reset()
                            self.vision_epoch += 1
                            continue
                        self.win.apply(keys if self.enabled.is_set() and not self.preview_only else set(), hwnd,run=self.config.get('auto_run',True))
                        prefix = ('仅检测，未按键：' if self.preview_only else '') + ('暗场增强：' if dark else '') + ('标签追踪：' if anchor_used else '')
                        self.status_text = f'{prefix}{note}  大号 {ts:.2f} / 小号 {ss:.2f}'
                        self.last_detection = f' 上次识别：大号 {ts:.2f} / 小号 {ss:.2f}'
                        if time.monotonic() - self.last_diagnostic >= 1:
                            diagnostic = {'time': time.time(), 'preview_only': self.preview_only,
                                          'leader_score': ts, 'self_score': ss,
                                          'leader': target, 'self': own,
                                          'directions': sorted(keys), 'status': note}
                            (BASE / 'last_detection.json').write_text(json.dumps(diagnostic, ensure_ascii=False, indent=2), encoding='utf-8')
                            self.last_diagnostic = time.monotonic()
                        for point, colour in ((target, (60, 220, 60)), (own, (0, 210, 255))):
                            if point:
                                cv2.circle(frame, tuple(map(int, point)), 12, colour, 2)
                        self.debug_frame = frame
        except Exception as e:
            logging.exception('follower loop')
            self.enabled.clear()
            self.status_text = '已停止：' + str(e)
        finally:
            self.win.release()

    def tick(self):
        while not self.hotkey_queue.empty():
            ident = self.hotkey_queue.get_nowait()
            self.last_hotkey = {1: 'F8', 2: 'F9', 3: 'F6', 4: 'F7'}[ident] + time.strftime(' %H:%M:%S')
            logging.info('Hotkey %s', self.last_hotkey)
            if ident == 1:
                self.toggle()
            elif ident == 2:
                self.stop()
            elif ident in (3, 4):
                self.stop()
                role = 'leader' if ident == 3 else 'self'
                self.capture_role = role
                self.root.after(250, lambda r=role: self.capture(r))
        self.status.configure(text=self.status_text)
        self.running_label.configure(
            text=('运行中：寻找并跟随大号' if self.enabled.is_set() else '已暂停：按 F8 开始') + ('  |  ' + self.last_hotkey if self.last_hotkey else ''),
            foreground='#137333' if self.enabled.is_set() else '#a63b00')
        self.ready_label.configure(text='大号：上头狂战' + (' ✓' if 'leader' in self.trackers else '（未设置）') + '    小号：上头影刃' + (' ✓' if 'self' in self.trackers else '（未设置）'))
        if time.monotonic()-self.last_state_write > 1:
            (BASE/'state.json').write_text(json.dumps({'enabled': self.enabled.is_set(),
                'worker_alive': self.worker.is_alive(), 'last_hotkey': self.last_hotkey,
                'status': self.status_text, 'time': time.time()}, ensure_ascii=False, indent=2), encoding='utf-8')
            self.last_state_write = time.monotonic()
        if self.show_debug.get() and self.debug_frame is not None:
            if self.preview is None or not self.preview.winfo_exists():
                self.preview = tk.Toplevel(self.root)
                self.preview.title('识别预览：绿色大号 / 黄色小号')
                self.preview_label = ttk.Label(self.preview)
                self.preview_label.pack()
                self.preview.protocol('WM_DELETE_WINDOW', lambda: self.show_debug.set(False))
            im = cv2.cvtColor(self.debug_frame, cv2.COLOR_BGR2RGB)
            self.preview_photo = ImageTk.PhotoImage(Image.fromarray(im).resize((640, 480)))
            self.preview_label.configure(image=self.preview_photo)
        elif self.preview is not None and self.preview.winfo_exists():
            self.preview.destroy()
        if not self.closed.is_set():
            self.root.after(80, self.tick)

    def close(self):
        self.stop()
        self.closed.set()
        if self.hotkey_thread_id:
            self.win.u.PostThreadMessageW(self.hotkey_thread_id, 0x0012, 0, 0)
            self.hotkey_thread.join(timeout=1)
        self.worker.join(timeout=2)
        self.ocr_thread.join(timeout=1)
        self.win.release()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == '__main__':
    logging.basicConfig(filename=BASE / 'follow.log', level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(message)s', encoding='utf-8')
    try:
        App().run()
    except Exception as exc:
        logging.exception('startup')
        try:
            messagebox.showerror('跟随工具启动失败', str(exc))
        except Exception:
            pass
        raise
