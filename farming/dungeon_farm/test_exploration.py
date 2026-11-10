import unittest
from dungeon_farm.exploration import RoomExplorer

def doors(*names):return [{'direction':name,'x':0,'y':0} for name in names]

class ExplorationTests(unittest.TestCase):
    def test_verified_preference_does_not_revisit_a_used_exit(self):
        e=RoomExplorer();e.enter('fork',None)
        self.assertEqual(e.choose(doors('left','up','right'),'up')['direction'],'up')
        e.departing('up');e.enter('branch','down')
        e.departing('down');e.enter('fork','up')
        self.assertEqual(e.choose(doors('left','up','right'),'up')['direction'],'left')
    def test_dead_end_backtracks_then_takes_unvisited_branch(self):
        e=RoomExplorer();e.enter('entry',None)
        self.assertEqual(e.choose(doors('left'))['direction'],'left')
        e.departing('left');e.enter('fork','right')
        self.assertEqual(e.choose(doors('left','up','down','right'))['direction'],'left')
        e.departing('left');e.enter('dead_end','right')
        self.assertEqual(e.choose(doors('right'))['direction'],'right')
        e.departing('right');e.enter('fork','left')
        self.assertEqual(e.choose(doors('left','up','down','right'))['direction'],'up')
        e.departing('up');e.enter('boss','down')

    def test_clear_room_revisit_does_not_reset_tried_exits(self):
        e=RoomExplorer();e.enter('a',None);e.departing('left');e.enter('b','right')
        e.departing('right');e.enter('a','left')
        self.assertEqual(e.choose(doors('left','down'))['direction'],'down')
