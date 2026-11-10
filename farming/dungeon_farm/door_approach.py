"""Align on the inside of a doorway before attempting the room transition."""
import math

class DoorApproach:
    def __init__(self):self.identity=None;self.aligned=False
    def target(self,door,position):
        direction=door['direction'];x,y=door['x'],door['y']
        identity=(direction,round(x),round(y))
        if identity!=self.identity:self.identity=identity;self.aligned=False
        dx,dy={'left':(-1,0),'right':(1,0),'up':(0,-1),'down':(0,1)}[direction]
        inside=(x-dx*60,y-dy*45)
        if not self.aligned:
            # A character already in the door lane need not walk backwards.
            lane=abs(position[1]-y)<=12 if dx else abs(position[0]-x)<=12
            near=abs(position[0]-x)<=85 if dx else abs(position[1]-y)<=70
            if math.dist(position,inside)<=18 or (lane and near):self.aligned=True
        return (x+dx*25,y+dy*25) if self.aligned else inside
