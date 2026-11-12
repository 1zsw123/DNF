"""Estimate the fixed HUD orb fill; never identify or use arbitrary items."""
import numpy as np

class RecoveryBudget:
    """One potion input per dungeon run, including retries after revival."""
    def __init__(self, limit=1):
        self.limit=limit;self.used=0

    def available(self, resources, age):
        return self.used<self.limit and need_recovery(resources,age)

    def sent(self):
        self.used+=1

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
