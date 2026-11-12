"""OCR owns its capture thread; combat never waits for image recognition."""
import threading
import time


class BackgroundSignals:
    def __init__(self, win, control, factory=None):
        if factory is None:
            from dungeon_farm.screen_signals import ScreenSignals
            factory = ScreenSignals
        self.latest = None
        self.error = None
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self._run, args=(win, control, factory), daemon=True)
        self.thread.start()

    def _run(self, win, control, factory):
        screen = None
        try:
            screen = factory()
            while not self.stop.is_set() and not control.stop.is_set():
                if control.paused.is_set():
                    with self.lock:
                        self.latest = None
                    self.stop.wait(.08)
                    continue
                hwnd = win.game()
                if not control.paused.is_set() and hwnd and win.foreground(hwnd):
                    started = time.monotonic()
                    value = screen.poll(win, hwnd, full=True)
                    if (value is not None and not control.paused.is_set()
                            and not control.stop.is_set() and win.foreground(hwnd)):
                        with self.lock:
                            self.latest = (started, time.monotonic(), value)
                self.stop.wait(.08)
        except Exception as exc:
            self.error = exc
        finally:
            if screen is not None:
                screen.close()

    def read(self, after=0, max_age=3):
        if self.error is not None:
            raise RuntimeError('后台画面识别失败') from self.error
        with self.lock:
            value = self.latest
        if value and value[0] >= after and time.monotonic()-value[0] <= max_age:
            return value
        return None

    def close(self):
        self.stop.set()
        self.thread.join(timeout=5)
