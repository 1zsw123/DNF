"""Align on the inside of a doorway before attempting the room transition."""
import math
import time

class DoorApproach:
    def __init__(self):
        self.identity=None;self.aligned=False;self.push=25
        self.last_position=None;self.progress_at=0;self.probe=0;self.offset=0
        self.escape=[];self.escaped=set()
    def target(self,door,position,doors=()):
        direction=door['direction'];x,y=door['x'],door['y']
        while self.escape and math.dist(position,self.escape[0])<=18:self.escape.pop(0)
        if self.escape:return self.escape[0]
        # Finish entrance-escape waypoints before switching to the exit goal.
        # Recomputing them each frame oscillates at the boundary; walking
        # parallel too close to a portal can trigger it behind the actor.
        for other in doors:
            if other==door:continue
            ox,oy=other['x'],other['y'];side=other['direction'];px,py=position
            entrance=(side,ox,oy)
            if entrance in self.escaped:continue
            exposed=(side=='left' and px<ox+100) or (side=='right' and px>ox-100)
            if exposed and abs(py-oy)<140:
                outside=(side=='left' and px<ox) or (side=='right' and px>ox)
                lane=oy+(-90 if py<oy else 90) if outside and abs(py-oy)<85 else py
                inward=ox+(240 if side=='left' else -240)
                self.escape=([(px,lane)] if lane!=py else [])+[(inward,lane)]
                self.escaped.add(entrance)
                return self.escape[0]
            exposed=(side=='up' and py<oy+90) or (side=='down' and py>oy-90)
            if exposed and abs(px-ox)<140:
                outside=(side=='up' and py<oy) or (side=='down' and py>oy)
                lane=ox+(-120 if px<ox else 120) if outside and abs(px-ox)<110 else px
                inward=oy+(150 if side=='up' else -150)
                self.escape=([(lane,py)] if lane!=px else [])+[(lane,inward),(ox+(180 if x>=ox else -180),inward)]
                self.escaped.add(entrance)
                return self.escape[0]
        identity=(direction,round(x),round(y))
        now=time.monotonic()
        if identity!=self.identity:
            self.identity=identity;self.aligned=False;self.push=25
            self.last_position=position;self.progress_at=now;self.probe=0;self.offset=0
        dx,dy={'left':(-1,0),'right':(1,0),'up':(0,-1),'down':(0,1)}[direction]
        if math.dist(position,self.last_position)>12:
            self.last_position=position;self.progress_at=now
        elif self.aligned and now-self.progress_at>1.2:
            # Door object origins are not exact trigger lanes in this client.
            # Probe nearby lanes after an actual stall, realigning inside
            # before pushing again; do not learn the closed edge as a wall.
            self.probe+=1;self.offset=(35,-35,70,-70,0)[(self.probe-1)%5]
            self.aligned=False;self.push=25;self.progress_at=now
        x+=self.offset if dy else 0
        y+=self.offset if dx else 0
        inside=(x-dx*60,y-dy*45)
        if not self.aligned:
            # A character already in the door lane need not walk backwards.
            lane=abs(position[1]-y)<=12 if dx else abs(position[0]-x)<=12
            near=abs(position[0]-x)<=85 if dx else abs(position[1]-y)<=70
            if math.dist(position,inside)<=18 or (lane and near):self.aligned=True
        if self.aligned:
            if math.dist(position,(x+dx*self.push,y+dy*self.push))<=18:
                self.push=min(100,self.push+5)
            return (x+dx*self.push,y+dy*self.push)
        return inside
