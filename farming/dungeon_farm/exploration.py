"""Explore variable dungeon layouts; remember exits and backtrack dead ends."""
class RoomExplorer:
    def __init__(self):
        self.rooms={};self.current=None;self.pending=None

    def enter(self,scene,entry):
        if self.pending:
            old,direction=self.pending
            self.rooms[old]['used'].add(direction)
        room=self.rooms.setdefault(scene,{'used':set(),'parent':entry})
        if entry:room['used'].add(entry)
        self.current=scene;self.pending=None

    def choose(self,doors,preferred=None):
        room=self.rooms[self.current]
        available={d['direction']:d for d in doors}
        order=list(dict.fromkeys(([preferred] if preferred else [])+['left','up','down','right']))
        for direction in order:
            if direction in available and direction not in room['used']:
                return available[direction]
        return available.get(room['parent'])

    def departing(self,direction):self.pending=(self.current,direction)
