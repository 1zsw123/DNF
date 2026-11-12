"""One X per confirmed death, then wait for a fresh living observation."""
class Revival:
    def __init__(self):
        self.dead=False;self.sent_at=None;self.attempts=0
        self.observed_at=None

    def observe(self, dead, observed_at=None):
        if observed_at is not None:
            if self.observed_at is not None and observed_at<=self.observed_at:return False
            self.observed_at=observed_at
        revived=self.dead and not dead
        self.dead=dead
        if not dead:self.sent_at=None;self.attempts=0
        return revived

    def action(self,now):
        if not self.dead:return None
        if self.sent_at is None or now-self.sent_at>=3:
            # A delayed OCR result captured before X says nothing about the
            # outcome of X. Wait for an observation captured after its grace
            # period before either retrying or declaring revival failed.
            if (self.sent_at is not None and self.observed_at is not None
                    and self.observed_at<self.sent_at+3):
                return 'revive_unconfirmed' if now-self.sent_at>=20 else 'waiting_revive'
            return 'revive' if self.attempts<2 else 'revive_failed'
        return 'waiting_revive'

    def sent(self,now):
        self.sent_at=now;self.attempts+=1

    def suspend(self,now):
        # Foreground loss/manual input pauses observation. Do not charge that
        # time to the revive timeout or reuse pre-resume death evidence.
        if self.sent_at is not None:self.sent_at=now
