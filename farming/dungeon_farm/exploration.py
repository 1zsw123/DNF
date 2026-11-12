"""Explore variable dungeon layouts; remember exits and backtrack dead ends."""
from collections import deque

class RoomExplorer:
    def __init__(self):
        self.rooms={};self.current=None;self.pending=None

    def enter(self,scene,entry):
        if self.pending:
            old,direction=self.pending
            self.rooms[old]['used'].add(direction)
            self.rooms[old]['links'][direction]=scene
        room=self.rooms.setdefault(scene,{'used':set(),'parent':entry,'links':{},'available':set()})
        if self.pending and entry:room['links'][entry]=self.pending[0]
        if entry:room['used'].add(entry)
        self.current=scene;self.pending=None

    def choose(self,doors,preferred=None):
        room=self.rooms[self.current]
        available={d['direction']:d for d in doors}
        room['available'].update(available)
        order=list(dict.fromkeys(([preferred] if preferred else [])+['left','up','down','right']))
        for direction in order:
            if direction in available and direction not in room['used']:
                return available[direction]
        # Returning through an entrance does not prove the child branch was
        # finished. Route over observed room links to any remaining frontier,
        # including a room abandoned by an accidental portal transition.
        queue=deque([(self.current,None)]);seen={self.current}
        while queue:
            node,first=queue.popleft();record=self.rooms[node]
            if first is not None and record['available']-record['used']:
                return available.get(first)
            for direction,neighbor in record['links'].items():
                if node==self.current and direction not in available:continue
                if neighbor not in seen:
                    seen.add(neighbor);queue.append((neighbor,first or direction))
        return available.get(room['parent'])

    def departing(self,direction):self.pending=(self.current,direction)
