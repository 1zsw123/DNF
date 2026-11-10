import unittest
from dungeon_farm.route import onward_door

class RouteTests(unittest.TestCase):
    def test_only_forward_exit(self):
        a={'direction':'up'}; b={'direction':'down'}
        self.assertEqual(onward_door([a,b],'up'),b)
    def test_branch_does_not_guess(self):
        self.assertIsNone(onward_door([{'direction':d} for d in ('up','left','down')],'up'))
    def test_dead_end_does_not_backtrack(self):
        self.assertIsNone(onward_door([{'direction':'up'}],'up'))
    def test_unknown_entry_stops(self):
        self.assertIsNone(onward_door([{'direction':d} for d in ('up','down')],'left'))
