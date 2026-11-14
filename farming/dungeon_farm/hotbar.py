"""Read the 12 skill slots' cooldown state from the screen (no memory reads).

Layout observed on this 70 client (normalized 640x480 frame): two rows of six
slots at the lower right, Q W E R T Y on top and A S D F G H below; positions
calibrated from a saved hotbar-sample.png. A slot on cooldown, or every slot
while an uncancellable animation plays, is drawn darkened; a skill that cannot
be used at all (e.g. weapon restriction) is drawn in pure grey.

Each slot learns its own "ready" brightness, so different icons need no
reference images. Anything uncertain (no frame yet, black loading frame, a
reading that looks like the wrong region) reports *unknown*, and callers then
fall back to plain spamming rather than refusing to press.
"""
import time

# Slot centres in the normalized 640x480 frame.
_X = (444, 467, 491, 514, 538, 561)
SLOTS = {**{k:(x,427) for k,x in zip('qwerty',_X)}, **{k:(x,457) for k,x in zip('asdfgh',_X)}}
GREY = 30  # mean HSV saturation below this: a greyed-out (unusable) icon
REGION = (420, 410, 168, 64)  # x, y, width, height of the crop holding all slots
PATCH = 6                     # half size of the sampled square at each slot centre


def _patches(crop):
    x0, y0 = REGION[0], REGION[1]
    for key, (cx, cy) in SLOTS.items():
        px, py = cx-x0, cy-y0
        patch = crop[max(0,py-PATCH):py+PATCH, max(0,px-PATCH):px+PATCH, :3]
        if patch.size:
            yield key, patch


def slot_levels(crop):
    """Mean brightness (max channel) of each slot's central patch.

    ``crop`` is the REGION already scaled to 640x480 units (HxWx3 array)."""
    import numpy as np
    return {key: float(np.mean(np.max(patch, axis=2))) for key, patch in _patches(crop)}


def slot_saturation(crop):
    """Mean HSV saturation (0-255) of each slot's central patch."""
    import numpy as np
    out = {}
    for key, patch in _patches(crop):
        p = patch.astype(float)
        hi, lo = p.max(axis=2), p.min(axis=2)
        out[key] = float(np.mean(np.where(hi > 0, (hi-lo)/np.maximum(hi, 1)*255, 0)))
    return out


class CooldownTracker:
    """Per-slot ready/cooldown estimate from successive brightness readings."""
    def __init__(self, ready_ratio=.62, cluster=.75, alpha=.04, min_level=25, max_age=.5, persist=8):
        self.ready_ratio = ready_ratio  # below this share of the ready level: cooling down
        self.cluster = cluster          # samples above this share update the ready level
        self.alpha = alpha              # slow, so a brief "ready" flash cannot inflate it
        self.min_level = min_level
        self.max_age = max_age
        self.persist = persist          # consecutive brighter samples to accept a new level
        self.high_run = {}
        self.ref = {}
        self.level = {}
        self.time = None
        self.last_dark = {}
        self.sat = {}
        self.disabled = False

    def update(self, levels, now, saturation=None):
        if not levels:
            return
        values = list(levels.values())
        # A black/loading frame or a uniform patch is not a hotbar reading.
        if max(values) < self.min_level or max(values)-min(values) < 4:
            self.time = None
            return
        for key, value in levels.items():
            ref = self.ref.get(key)
            if ref is None:
                self.ref[key] = value
                continue
            if value > ref/self.cluster:
                # A slot first seen while dark gets its real ready level once
                # a clearly brighter level persists; a brief ready-flash does not.
                self.high_run[key] = self.high_run.get(key, 0)+1
                if self.high_run[key] >= self.persist:
                    self.ref[key] = value
                    self.high_run[key] = 0
                continue
            self.high_run[key] = 0
            if value >= self.cluster*ref:
                self.ref[key] = ref + self.alpha*(value-ref)
        self.level = dict(levels)
        self.sat = dict(saturation or {})
        self.time = now
        for key in levels:
            if not self._ready(key):
                self.last_dark[key] = now

    def _ready(self, key):
        if key in self.sat and self.sat[key] < GREY:
            return False  # greyed out: cannot be used at all right now
        ref, value = self.ref.get(key), self.level.get(key)
        if ref is None or value is None:
            return True
        return value >= self.ready_ratio*ref

    def fresh(self, now):
        return not self.disabled and self.time is not None and 0 <= now-self.time <= self.max_age

    def ready(self, key, now):
        """True/False when known; None when the reading is unavailable."""
        if not self.fresh(now) or key not in self.level:
            return None
        return self._ready(key)

    def darkened_since(self, key, since):
        return self.last_dark.get(key, float('-inf')) >= since

    def snapshot(self):
        return {'level':{k:round(v) for k,v in self.level.items()},
                'sat':{k:round(v) for k,v in self.sat.items()},
                'ref':{k:round(v) for k,v in self.ref.items()},
                'ready':sorted(k for k in self.level if self._ready(k)),
                'disabled':self.disabled}


class HotbarReader:
    """Small, fast capture of the slot region of the game's client area."""
    def __init__(self, interval=.06):
        self.interval = interval
        self.capture = None
        self.due = 0
        self.saved = False

    def read(self, win, hwnd, now=None):
        now = time.monotonic() if now is None else now
        if now < self.due:
            return None
        self.due = now+self.interval
        rect = win.rect(hwnd)
        if not rect:
            return None
        import cv2
        import numpy as np
        if self.capture is None:
            import mss
            self.capture = mss.mss()
        sx, sy = rect['width']/640, rect['height']/480
        x, y, w, h = REGION
        box = {'left':int(rect['left']+x*sx), 'top':int(rect['top']+y*sy),
               'width':max(1,int(w*sx)), 'height':max(1,int(h*sy))}
        raw = np.asarray(self.capture.grab(box))[:, :, :3]
        crop = cv2.resize(raw, (w, h), interpolation=cv2.INTER_AREA)
        return crop

    def save_sample(self, crop, path):
        """Keep one crop per run so the slot geometry can be checked later."""
        if self.saved or crop is None:
            return
        import cv2
        ok, data = cv2.imencode('.png', cv2.resize(crop, None, fx=3, fy=3, interpolation=cv2.INTER_NEAREST))
        if ok:
            path.write_bytes(data.tobytes())
            self.saved = True

    def close(self):
        if self.capture is not None:
            self.capture.close()
            self.capture = None
