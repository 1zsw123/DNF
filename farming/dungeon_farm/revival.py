"""One X per confirmed death, then wait for a fresh living observation."""
class Revival:
    def __init__(self):
        self.dead=False;self.sent_at=None;self.attempts=0

    def observe(self, dead):
        revived=self.dead and not dead
        self.dead=dead
        if not dead:self.sent_at=None;self.attempts=0
        return revived

    def action(self,now):
        if not self.dead:return None
        if self.sent_at is None or now-self.sent_at>=3:
            return 'revive' if self.attempts<2 else 'revive_failed'
        return 'waiting_revive'

    def sent(self,now):
        self.sent_at=now;self.attempts+=1
