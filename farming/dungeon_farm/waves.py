"""Empty-room debounce; a late spawn always revokes exit readiness."""
class WaveTracker:
    def __init__(self, settle_seconds=3.5):
        self.settle_seconds=settle_seconds
        self.reset()

    def reset(self):
        self.number=1
        self.empty_since=None

    def suspend(self):
        # Unobserved time while paused/away cannot certify an empty room.
        self.empty_since=None

    def update(self, has_enemies, now):
        new_wave=False
        if has_enemies:
            if self.empty_since is not None and now-self.empty_since>=.4:
                self.number+=1
                new_wave=True
            self.empty_since=None
            return False,new_wave
        if self.empty_since is None:self.empty_since=now
        return now-self.empty_since>=self.settle_seconds,False
