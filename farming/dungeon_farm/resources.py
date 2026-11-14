"""Estimate the fixed HUD orb fill; never identify or use arbitrary items."""
import numpy as np

POTION_LIMITS=('1','2','3','5','10','不限')

class RecoveryBudget:
    """Potion inputs per dungeon run, including retries after revival.

    ``limit=None`` means no per-run cap; the runtime still spaces inputs."""
    def __init__(self, limit=1):
        self.limit=limit;self.used=0

    def available(self, resources, age):
        return (self.limit is None or self.used<self.limit) and need_recovery(resources,age)

    def sent(self):
        self.used+=1

def potion_limit(character):
    """Per-run potion cap for a character: an int, or None for no cap.

    The berserker scheme defaults to no cap; other schemes keep the earlier
    one-potion-per-run default unless the character sets ``potion_limit``."""
    character=character or {}
    value=character.get('potion_limit')
    if value is None:
        value='不限' if character.get('rotation','狂战士')=='狂战士' else '1'
    if value not in POTION_LIMITS:raise ValueError('每局血药上限无效')
    return None if value=='不限' else int(value)

def orb_fill(frame):
    def fill(x,channel):
        area=frame[420:460,x-8:x+8].astype(float)
        color=area[:,:,channel]
        others=np.max(np.delete(area,channel,axis=2),axis=2)
        colored=(color>40)&(color>others*1.3+8)
        return float(np.mean(np.mean(colored,axis=1)>.35))
    return {'hp_fill':fill(30,2),'mp_fill':fill(610,0)}

def need_recovery(resources,age):
    return bool(resources and 0<=age<2 and
                # Loading/black frames hide both HUD orbs. Zero/zero is not
                # evidence of low health and must never consume an item.
                (resources['hp_fill']>0 or resources['mp_fill']>0) and
                resources['hp_fill']<.50)
