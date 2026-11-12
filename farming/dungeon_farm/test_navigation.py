import unittest
from dungeon_farm.navigation import Navigator


class NavigationTests(unittest.TestCase):
    def test_portal_avoidance_leaves_entry_without_a_fixed_interior_waypoint(self):
        n=Navigator()
        move=n.steer('room',(500,210),(900,300),0,avoid=((500,200),))
        self.assertNotIn('up',move)
        self.assertTrue(move);self.assertFalse(n.no_path)
        self.assertEqual(n.goal,n.node((900,300)))

    def test_half_cell_coordinates_keep_one_cell_translation(self):
        n=Navigator()
        for y in range(-70,751,20):
            self.assertEqual(n.node((1183,y-20))[1],n.node((1183,y))[1]-1)

    def test_observed_dark_city_pit_stall_records_forward_cell_not_own_floor(self):
        n=Navigator();position=(1183,730)
        n.steer('pit',position,(1183,394),0)
        n.steer('pit',position,(1183,394),.6)
        self.assertIn((59,36),n.contacts)
        self.assertNotIn(n.node(position),n.contacts)

    def test_retreat_routes_around_enemy_instead_of_through_it(self):
        n=Navigator();move=n.steer('r',(100,240),(500,240),0,avoid=((300,240),),floor_bounds=(120,360))
        self.assertTrue({'up','down'}&move)
        self.assertTrue(any(abs(y*20-240)>=80 for x,y in n.path))
        self.assertTrue(all(120<=y*20<=360 for x,y in n.path))
        self.assertEqual(n.contacts,set())

    def test_enemy_avoidance_is_temporary_and_keeps_real_walls(self):
        n=Navigator();n.reset('r');n.contacts={(40,10)};n.blocked=set(n.contacts)
        n.steer('r',(100,240),(500,240),0,avoid=((300,240),),floor_bounds=(120,360))
        self.assertTrue(n.danger)
        n.steer('r',(100,240),(500,240),.1)
        self.assertFalse(n.danger);self.assertIsNone(n.floor_bounds)
        self.assertEqual(n.contacts,{(40,10)})

    def test_corner_escape_uses_available_upper_floor(self):
        n=Navigator();move=n.steer('r',(0,366),(370,366),0,
                                  avoid=((90,355),(300,200)),floor_bounds=(200,366))
        self.assertIn('up',move);self.assertFalse(n.no_path)

    def test_incomplete_floor_band_does_not_make_a_false_trap(self):
        n=Navigator();n.reset('r');n.contacts={(10,10)};n.blocked=set(n.contacts)
        move=n.steer('r',(100,200),(300,200),0,avoid=((400,200),),floor_bounds=(200,200))
        self.assertTrue(move);self.assertFalse(n.no_path)
        self.assertIn((10,10),n.contacts)

    def test_separate_combat_retreats_do_not_accumulate_route_failure(self):
        n=Navigator();n.reset('r');n.contacts={(50,10)};n.blocked=set(n.contacts)
        for cycle in range(60):
            for step in range(9):
                n.steer('r',(420+step*3,320),(600,320),cycle*3+step*.1)
                self.assertFalse(n.no_path)
            n.pause()
        self.assertEqual(n.replans,0)
        self.assertEqual(n.stalled_for,0)
        self.assertIn((50,10),n.contacts)

    def test_temporary_mid_room_lock_is_rechecked_without_pausing_run(self):
        n=Navigator();p=[895.,208.]
        # The observed failure: four apparent contacts in ~2 s after combat.
        # Movement becomes available again once the transient lock ends.
        recovered=False
        for i in range(400):
            now=i*.02
            move=n.steer('r',p,(805,197),now)
            self.assertFalse(n.no_path)
            recovered |= n.recovery_attempts>0
            if now>=2.6:
                p[0]+=3*(('right' in move)-('left' in move))
                p[1]+=3*(('down' in move)-('up' in move))
            if abs(p[0]-805)<8 and abs(p[1]-197)<8:break
        self.assertTrue(recovered)
        self.assertLess(abs(p[0]-805),8)
        self.assertLess(abs(p[1]-197),8)

    def test_local_recovery_preserves_old_distant_contacts(self):
        n=Navigator();n.reset('r')
        n.contacts={(30,10)};n.blocked=set(n.contacts)
        n.contact_times={(30,10):-100}
        for i in range(115):n.steer('r',(100,200),(300,200),i*.02)
        self.assertIsNotNone(n.recovery_until)
        for i in range(115,160):n.steer('r',(100,200),(300,200),i*.02)
        self.assertIn((30,10),n.contacts)

    def test_initial_loading_lock_does_not_invent_four_walls(self):
        n=Navigator(entry_grace=3)
        for i in range(29):n.steer('new',(677,113),(677,255),i*.1)
        self.assertEqual(n.contacts,set());self.assertFalse(n.no_path)
        n.steer('new',(677,140),(677,255),3)
        self.assertEqual(n.collisions,0)
        n.reset('next');self.assertEqual(n.entry_grace,3)

    def test_entry_grace_still_detects_a_real_trap(self):
        n=Navigator(entry_grace=3)
        for i in range(1300):
            n.steer('r',(100,200),(500,200),i*.02)
            if n.no_path:break
        self.assertTrue(n.no_path)

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

    def test_retreat_replans_blocked_step_within_two_tenths(self):
        n=Navigator(entry_grace=3)
        first=n.steer('a',(100,200),(400,200),0,urgent=True)
        self.assertEqual(first,frozenset({'right'}))
        changed=n.steer('a',(100,200),(400,200),.2,urgent=True)
        self.assertEqual(n.collisions,1)
        self.assertNotEqual(changed,first)
        self.assertTrue(changed)
        self.assertFalse(n.contacts)
        self.assertTrue(n.temporary_contacts)

    def test_scene_change_discards_old_obstacles(self):
        n=Navigator();n.reset('a');n.blocked.add((10,10))
        n.steer('b',(100,200),(300,200),0)
        self.assertFalse(n.blocked)

    def test_no_diagonal_cutting_through_wall_corners(self):
        n=Navigator();n.blocked={(6,10),(5,11)}
        path=n.plan((5,10),(6,11))
        self.assertNotEqual(path[0],(6,11))
