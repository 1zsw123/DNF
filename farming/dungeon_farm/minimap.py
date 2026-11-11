"""Read Arden's calibrated minimap and route over its visible room graph."""
from collections import deque
import time
import cv2
import numpy as np

XS=(584,598,613,627)
YS=(44,58,73,87,102)
STEPS={'left':(-1,0),'right':(1,0),'up':(0,-1),'down':(0,1)}
# This client's Arden layout, verified through a completed run. Fog hides
# unexplored corridors on a fresh run; local door objects still veto edges.
ARDEN_PATH=((0,0),(1,0),(1,1),(2,1),(2,2),(2,3),(1,3),(1,4),(2,4),(3,4))
ARDEN_EDGES=list(zip(ARDEN_PATH,ARDEN_PATH[1:]))+[((1,0),(2,0)),((2,2),(3,2)),((1,3),(0,3))]
ARDEN_ROOMS={node for edge in ARDEN_EDGES for node in edge}


class MinimapSignals:
    """Independent lightweight capture: room routing never waits for OCR."""
    def __init__(self,dungeon):
        import mss
        self.capture=mss.mss();self.dungeon=dungeon;self.due=0

    def poll(self,win,hwnd,full=False):
        now=time.monotonic()
        if now<self.due:return None
        self.due=now+.15
        rect=win.rect(hwnd)
        if not rect or not win.foreground(hwnd):return None
        frame=cv2.resize(np.asarray(self.capture.grab(rect))[:,:,:3],(640,480))
        debug={}
        value=read_minimap(frame,self.dungeon,debug)
        return {'minimap':value,'diagnostic':debug}

    def close(self):self.capture.close()


def read_minimap(frame,dungeon,debug=None):
    if dungeon!='阿登高地' or frame.shape[:2]!=(480,640):return None
    hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV)
    h,s,v=cv2.split(hsv)
    blue=(h>=85)&(h<=125)&(s>80)&(v>35)
    b,g,r=(a.astype(float) for a in cv2.split(frame))
    glow=(b>170)&(g<b*.8)&(r<b*.4)
    red=((h<20)|(h>170))&(s>140)&(v>100)
    rooms=set();players=[];bosses=[]
    for row,y in enumerate(YS):
        for col,x in enumerate(XS):
            tile=(col,row);patch=np.s_[y-3:y+4,x-3:x+4]
            if float(blue[patch].mean())>.6:rooms.add(tile)
            if int(glow[patch].sum())>=3:players.append(tile)
            if int(red[patch].sum())>=12:bosses.append(tile)
    # This calibrated Arden layout's boss is at the lower-right tile.
    # Red world scenery shows through fog elsewhere; it is not another boss.
    if (3,4) in bosses:bosses=[(3,4)]
    if debug is not None:debug.update(players=players,bosses=bosses,rooms=sorted(rooms))
    if len(players)!=1 or len(bosses)!=1:return None
    current,boss=players[0],bosses[0]
    rooms.add(boss)
    if current not in rooms:return None
    # Room backgrounds touch even where there is a wall. Require a lighter
    # connector at the shared edge; adjacency alone invents shortcuts.
    corridor=(b>65)&(g>b*.58)&(r>b*.24)&(b>r*1.25)
    edges=[]
    for a in sorted(rooms):
        for direction in ('right','down'):
            dx,dy=STEPS[direction];other=(a[0]+dx,a[1]+dy)
            if other not in rooms:continue
            x=round((XS[a[0]]+XS[other[0]])/2);y=round((YS[a[1]]+YS[other[1]])/2)
            patch=corridor[y-3:y+4,x-1:x+2] if dx else corridor[y-1:y+2,x-3:x+4]
            middle=corridor[y-3:y+4,x] if dx else corridor[y,x-3:x+4]
            # The red boss icon covers its connector. The current room's
            # verified doors must still corroborate the final step at runtime.
            if (int(patch.sum())>=6 and int(middle.sum())>=2) or boss in (a,other):edges.append([a,other])
    path=shortest_path(current,boss,edges)
    source='visible'
    if path is None and boss==(3,4) and current in ARDEN_ROOMS and rooms<=ARDEN_ROOMS:
        # Only fill fog for the calibrated layout, never guess another map.
        # The follower's current room and boss must both be visible.
        edges=list(ARDEN_EDGES)
        path=shortest_path(current,boss,edges)
        source='verified_layout_under_fog'
    if path is None:return None
    return {'current':current,'boss':boss,'rooms':sorted(rooms),'edges':edges,'path':path,'source':source}


def shortest_path(start,goal,edges,blocked=()):
    start,goal=tuple(start),tuple(goal)
    graph={};blocked={frozenset((tuple(a),tuple(b))) for a,b in blocked}
    for a,b in edges:
        a,b=tuple(a),tuple(b)
        if frozenset((a,b)) in blocked:continue
        graph.setdefault(a,[]).append(b);graph.setdefault(b,[]).append(a)
    queue=deque([[start]]);seen={start}
    while queue:
        path=queue.popleft()
        if path[-1]==goal:return path
        for neighbor in graph.get(path[-1],[]):
            if neighbor not in seen:seen.add(neighbor);queue.append(path+[neighbor])
    return None


class MinimapRoute:
    def __init__(self):
        self.scene=None;self.signature=None;self.stamp=None;self.confirmations=0
        self.status='waiting';self.path=None
        self.blocked=set()
        self.edges=None;self.boss=None;self.current=None;self.locations={}

    def enter(self,scene,crossed=None):
        if scene==self.scene:return
        previous=self.current
        self.scene=scene;self.signature=None;self.stamp=None;self.confirmations=0
        self.current=self.locations.get(scene)
        if self.current is None and previous is not None and crossed in STEPS and self.edges:
            dx,dy=STEPS[crossed];candidate=(previous[0]+dx,previous[1]+dy)
            edge=frozenset((previous,candidate))
            if any(edge==frozenset(e) for e in self.edges) and tuple(sorted(edge)) not in self.blocked:
                self.current=candidate;self.locations[scene]=candidate
        self._plan()

    def _plan(self):
        self.path=shortest_path(self.current,self.boss,self.edges,self.blocked) if self.current is not None and self.boss is not None else None
        self.status=('at_boss' if self.current==self.boss else 'ready') if self.path else 'waiting'

    def confirm(self,scene,reading,stamp):
        self.enter(scene)
        if not reading:return self.current is not None
        # After initial acquisition, the graph belongs to the entire run.
        # Transient fog/lighting changes must not erase or rewrite that graph.
        signature=(tuple(reading['current']),tuple(reading['boss']))
        if self.edges is None:
            signature+=(tuple(sorted(tuple(sorted((tuple(a),tuple(b)))) for a,b in reading['edges'])),)
        if stamp!=self.stamp:
            self.confirmations=self.confirmations+1 if signature==self.signature else 1
            self.signature=signature;self.stamp=stamp
        if self.confirmations<2:return self.current is not None
        if self.boss is not None and tuple(reading['boss'])!=self.boss:
            self.current=None;self.path=None;self.status='layout_mismatch';return False
        self.current=tuple(reading['current']);self.boss=tuple(reading['boss'])
        self.locations[scene]=self.current
        if self.edges is None:self.edges=[(tuple(a),tuple(b)) for a,b in reading['edges']]
        self._plan()
        return True

    def choose(self,scene,doors,reading=None,stamp=None,validate_doors=True):
        if not self.confirm(scene,reading,stamp):return None
        current=self.current;boss=self.boss
        if current==boss:self.status='at_boss';self.path=[current];return None
        available={d['direction']:d for d in doors}
        # A room drawn next to another is not permission to use a missing door.
        blocked=[(current,(current[0]+dx,current[1]+dy)) for key,(dx,dy) in STEPS.items() if key not in available]
        if validate_doors:self.blocked.update(tuple(sorted(edge)) for edge in blocked)
        self.path=shortest_path(current,boss,self.edges,self.blocked)
        if not self.path or len(self.path)<2:self.status='no_path';return None
        dx,dy=self.path[1][0]-current[0],self.path[1][1]-current[1]
        direction=next(key for key,value in STEPS.items() if value==(dx,dy))
        self.status='ready'
        return available.get(direction)
