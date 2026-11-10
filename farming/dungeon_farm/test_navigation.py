import unittest
from dungeon_farm.navigation import Navigator


class NavigationTests(unittest.TestCase):
    def test_speculative_padding_does_not_seal_a_narrow_passage(self):
        n=Navigator();n.reset('r')
        n.blocked={(x,y) for x in range(4,7) for y in range(9,12)}-{(5,10)}
        n.contacts={(6,9),(6,10)}
        move=n.steer('r',(100,200),(300,200),0)
        self.assertFalse(n.no_path)
        self.assertTrue(move)
        self.assertTrue(n.contacts<=n.blocked)
    def test_target_just_left_of_old_fixed_boundary_can_be_planned(self):
        n=Navigator()
        self.assertIsNotNone(n.plan((5,10),(-2,10)))
    def test_known_floor_is_preferred_to_unknown_upper_wall(self):
        n=Navigator()
        n.free={(x,16) for x in range(5,31)}|{(x,y) for x in (5,30) for y in range(10,17)}
        n.blocked={(9,y) for y in range(7,14)}
        path=n.plan((5,10),(30,10))
        self.assertIsNotNone(path)
        self.assertTrue(all(y>=10 for x,y in path))
        self.assertTrue(any(y>=14 for x,y in path))
    def test_fast_character_does_not_bounce_at_waypoint(self):
        n=Navigator();p=[101.,200.]
        for i in range(150):
            move=n.steer('r',p,(360,200),i*.04)
            if not move:break
            p[0]+=18*(('right' in move)-('left' in move))
            p[1]+=18*(('down' in move)-('up' in move))
        self.assertLess(abs(p[0]-360),12)
        self.assertLess(i,40)
        self.assertEqual(n.collisions,0)

    def test_trapped_character_stops_instead_of_circling_forever(self):
        n=Navigator()
        for i in range(1300):
            n.steer('r',(100,200),(500,200),i*.02)
            if n.no_path:break
        self.assertTrue(n.no_path)
        self.assertLess(i,1250)

    def test_moving_target_does_not_hide_blocked_movement(self):
        n=Navigator()
        for i in range(10):
            n.steer('room',(100,200),(300+i*20,200),i*.1)
        self.assertGreater(n.collisions,0)

    def test_tall_room_bottom_exit_is_reachable(self):
        n=Navigator()
        path=n.plan(n.node((782,440)),n.node((782,493)))
        self.assertIsNotNone(path)
        self.assertEqual(path[-1],n.node((782,493)))

    def test_learns_wall_and_goes_around(self):
        n=Navigator();p=[100.,200.]
        # Impassable vertical slab; upper/lower passages both exist.
        for i in range(1500):
            move=n.steer('room',p,(360,200),i*.02)
            dx=('right' in move)-('left' in move)
            dy=('down' in move)-('up' in move)
            candidate=[p[0]+dx*3,p[1]+dy*3]
            if not (180<=candidate[0]<=240 and 140<=candidate[1]<=280): p=candidate
            if abs(p[0]-360)<8 and abs(p[1]-200)<8: break
        self.assertLess(abs(p[0]-360),8)
        self.assertLess(abs(p[1]-200),8)
        self.assertGreater(n.collisions,0)
        self.assertLess(n.collisions,16)

    def test_casting_pause_is_not_a_collision(self):
        n=Navigator();n.steer('a',(100,200),(300,200),0)
        n.pause();n.steer('a',(100,200),(300,200),5)
        self.assertEqual(n.collisions,0)

    def test_scene_change_discards_old_obstacles(self):
        n=Navigator();n.reset('a');n.blocked.add((10,10))
        n.steer('b',(100,200),(300,200),0)
        self.assertFalse(n.blocked)

    def test_no_diagonal_cutting_through_wall_corners(self):
        n=Navigator();n.blocked={(6,10),(5,11)}
        path=n.plan((5,10),(6,11))
        self.assertNotEqual(path[0],(6,11))
