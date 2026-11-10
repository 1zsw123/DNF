"""Online collision map + A*; observations only, no game input or memory writes."""
import math
from pathfinding.core.grid import Grid
from pathfinding.core.diagonal_movement import DiagonalMovement
from pathfinding.finder.a_star import AStarFinder


class Navigator:
    def __init__(self, cell=20):
        self.cell=cell
        self.scene=None
        self.blocked=set()
        self.contacts=set()
        self.free=set()
        self.path=[]
        self.goal=None
        self.probe=None
        self.collisions=0
        self.last_collision=None
        self.no_path=False
        self.previous=None
        self.watch_time=None
        self.watch_cells=set()
        self.stalled_for=0
        self.replans=0
        self.failure_reason=''

    def node(self, p):
        return tuple(round(v/self.cell) for v in p)

    def point(self, n):
        return tuple(v*self.cell for v in n)

    def reset(self, scene):
        self.__init__(self.cell)
        self.scene=scene

    def pause(self):
        # Time spent casting/paused must never be treated as blocked movement.
        self.probe=None
        self.previous=None
        self.watch_time=None

    def plan(self, start, goal):
        # Unknown cells are traversable until actual movement disproves that.
        # Broad bounds allow learning room edges without assuming every room
        # has the same walkable height.
        xmin,xmax=min(-1,start[0]-3,goal[0]-3),max(100,start[0]+10,goal[0]+10)
        ymin,ymax=min(3,start[1]-3,goal[1]-3),max(22,start[1]+3,goal[1]+3)
        if not all(xmin<=p[0]<=xmax and ymin<=p[1]<=ymax for p in (start,goal)):
            return None
        # Known floor is cheaper than speculative shortcuts above/below a
        # wall. Reuse safe ground instead of repeatedly probing unknown edges.
        grid=Grid(matrix=[[0 if (x,y) in self.blocked else (1 if (x,y) in self.free else 3) for x in range(xmin,xmax+1)]
                          for y in range(ymin,ymax+1)])
        finder=AStarFinder(diagonal_movement=DiagonalMovement.only_when_no_obstacle)
        path,_=finder.find_path(grid.node(start[0]-xmin,start[1]-ymin),
                               grid.node(goal[0]-xmin,goal[1]-ymin),grid)
        if not path:return None
        nodes=[(p.x+xmin,p.y+ymin) for p in path]
        # Keep turns and short checkpoints; don't stop steering at every 20px
        # cell of a straight corridor. All skipped cells were checked by A*.
        result=[];anchor=nodes[0]
        for i,node in enumerate(nodes[1:],1):
            turn=i==len(nodes)-1 or (node[0]-nodes[i-1][0],node[1]-nodes[i-1][1])!=(nodes[i+1][0]-node[0],nodes[i+1][1]-node[1])
            if turn or math.dist(anchor,node)>=6:
                result.append(node);anchor=node
        return result

    def steer(self, scene, position, destination, now):
        if self.scene!=scene: self.reset(scene)
        here=self.node(position); goal=self.node(destination)
        self.free.add(here);self.blocked.discard(here)
        # Scale arrival tolerance to observed movement; fixed 6px could make
        # a running character bounce across a waypoint without reaching it.
        step=math.dist(position,self.previous) if self.previous else 0
        tolerance=max(6,min(18,step*.6))
        self.previous=tuple(position)
        if self.watch_time is not None:
            self.stalled_for+=min(.25,max(0,now-self.watch_time))
        self.watch_time=now
        if here not in self.watch_cells:
            self.watch_cells.add(here);self.stalled_for=0
        if self.stalled_for>=8:
            self.replans+=1;self.stalled_for=0;self.path=[];self.probe=None
            if self.replans>=3:
                self.no_path=True;self.failure_reason='连续三次在已走过的区域停滞';return frozenset()
        if goal!=self.goal:
            # A moving monster must not erase evidence of a blocked step.
            self.goal=goal;self.path=[]
        if self.probe:
            waypoint,best,since=self.probe
            distance=math.dist(position,waypoint)
            if distance<best-4:
                self.probe=(waypoint,distance,now)
            elif now-since>.5 and distance>tolerance:
                dx,dy=waypoint[0]-position[0],waypoint[1]-position[1]
                length=math.hypot(dx,dy)
                ahead=self.node((position[0]+dx/length*self.cell,
                                 position[1]+dy/length*self.cell))
                # Learn the immediate blocked cell, not the distant goal.
                # A one-cell fringe avoids repeatedly hitting the same face.
                learned={ahead}
                if abs(dx)>abs(dy):
                    learned.update((ahead[0],ahead[1]+s) for s in (-1,1))
                else:
                    learned.update((ahead[0]+s,ahead[1]) for s in (-1,1))
                self.blocked.update(learned-self.free)
                self.contacts.update({ahead}-self.free)
                self.collisions+=1;self.last_collision=position
                self.path=[];self.probe=None
        while self.path and math.dist(position,self.point(self.path[0]))<=tolerance:
            self.path.pop(0);self.probe=None
        if not self.path:
            # A blocked goal may be an obstacle surface. Stop short at the
            # nearest reachable adjacent cell instead of clearing that wall.
            candidates=[goal] if goal not in self.blocked else [
                (goal[0]+dx,goal[1]+dy) for dx,dy in ((1,0),(-1,0),(0,1),(0,-1))
                if (goal[0]+dx,goal[1]+dy) not in self.blocked]
            paths=[p for g in candidates if (p:=self.plan(here,g)) is not None]
            if not paths:
                # The untested one-cell fringe can seal a narrow passage.
                # Remove that padding before declaring the character trapped;
                # retain measured contacts and never clear confirmed walls.
                self.blocked=self.contacts-self.free
                candidates=[goal] if goal not in self.blocked else [
                    (goal[0]+dx,goal[1]+dy) for radius in (1,2,3)
                    for dx,dy in ((radius,0),(-radius,0),(0,radius),(0,-radius))
                    if (goal[0]+dx,goal[1]+dy) not in self.blocked]
                paths=[p for g in candidates if (p:=self.plan(here,g)) is not None]
                if not paths:
                    self.no_path=True;self.failure_reason='已移除推测障碍边缘，仍无可达路线';self.pause();return frozenset()
            self.no_path=False;self.path=min(paths,key=len)
        waypoint=self.point(self.path[0]) if self.path else destination
        if len(self.path)==1 and self.path[0]==goal:waypoint=destination
        distance=math.dist(position,waypoint)
        if not self.probe or self.probe[0]!=waypoint:
            self.probe=(waypoint,distance,now)
        dx,dy=waypoint[0]-position[0],waypoint[1]-position[1]
        axis_tolerance=max(3,tolerance*.7)
        return frozenset(([('right' if dx>0 else 'left')] if abs(dx)>axis_tolerance else [])+
                         ([('down' if dy>0 else 'up')] if abs(dy)>axis_tolerance else []))
