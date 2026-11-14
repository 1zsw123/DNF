import unittest
from dataclasses import replace
import numpy as np
from dungeon_farm.hotbar import SLOTS, REGION, slot_levels, CooldownTracker
from dungeon_farm.berserker_rotation import make_planner
from dungeon_farm.planner import Observation, Enemy

BRIGHT = {k: 120+5*i for i, k in enumerate('qwertyasdfgh')}


def crop_with(levels):
    x0, y0, w, h = REGION
    crop = np.zeros((h, w, 3), dtype=np.uint8)
    for key, (cx, cy) in SLOTS.items():
        crop[cy-y0-8:cy-y0+8, cx-x0-8:cx-x0+8] = levels.get(key, 0)
    return crop


class SlotLevelTests(unittest.TestCase):
    def test_reads_each_slot_centre(self):
        levels = slot_levels(crop_with(BRIGHT))
        self.assertEqual(set(levels), set(SLOTS))
        for key, value in BRIGHT.items():
            self.assertAlmostEqual(levels[key], value, delta=1)


class TrackerTests(unittest.TestCase):
    def test_dark_slot_is_cooling_and_bright_is_ready(self):
        t = CooldownTracker()
        for i in range(10): t.update(dict(BRIGHT), i*.05)
        dark = dict(BRIGHT, r=50)
        t.update(dark, .6)
        self.assertFalse(t.ready('r', .6))
        self.assertTrue(t.ready('q', .6))
        self.assertTrue(t.darkened_since('r', .55))

    def test_brief_ready_flash_does_not_inflate_reference(self):
        t = CooldownTracker()
        for i in range(10): t.update(dict(BRIGHT), i*.05)
        for i in range(5): t.update(dict(BRIGHT, q=240), .5+i*.05)
        t.update(dict(BRIGHT), 1)
        self.assertTrue(t.ready('q', 1))

    def test_slot_first_seen_dark_learns_ready_level(self):
        t = CooldownTracker()
        start = dict(BRIGHT, e=55)
        t.update(start, 0)
        self.assertTrue(t.ready('e', 0))  # unknown yet: never blocks
        for i in range(10): t.update(dict(BRIGHT), .05*(i+1))
        t.update(start, 1)
        self.assertFalse(t.ready('e', 1))

    def test_black_or_uniform_frame_is_unknown(self):
        t = CooldownTracker()
        t.update(dict(BRIGHT), 0)
        t.update({k: 3 for k in BRIGHT}, .1)
        self.assertIsNone(t.ready('q', .1))
        t.update({k: 90 for k in BRIGHT}, .2)
        self.assertIsNone(t.ready('q', .2))

    def test_stale_reading_is_unknown(self):
        t = CooldownTracker()
        t.update(dict(BRIGHT), 0)
        self.assertIsNone(t.ready('q', 2))


class Game:
    """Tiny model: a pressed ready skill starts its real cooldown (dark slot);
    a press on cooldown or a dropped press changes nothing."""
    CD = {'q':8,'w':20,'e':40,'r':45,'t':50,'a':3.5,'s':6,'d':15,'f':25,'g':120,'y':130,'h':1}

    def __init__(self, drop=()):
        self.until = {}
        self.drop = list(drop)  # keys whose next press is dropped (e.g. room fade-in)
        self.dual = False
        self.wasted = []
        self.casts = []

    def levels(self, now):
        return {k: (45 if self.until.get(k, -1) > now else BRIGHT[k]) for k in BRIGHT}

    def press(self, key, now, release=False):
        if key == 'x' or release:
            return
        if self.until.get(key, -1) > now:
            self.wasted.append((now, key));return
        if key in self.drop:
            self.drop.remove(key);return
        self.until[key] = now+self.CD[key]
        self.casts.append((now, key))
        if key == 'h':
            self.dual = not self.dual


def run(planner, game, seconds=60, enemy=(150, 200)):
    tracker = CooldownTracker();planner.hotbar = tracker
    obs = Observation(0, scene='room', position=(100, 200), facing='right',
                      enemies=(Enemy('e', *enemy),), perception_valid=True)
    taps = []
    for i in range(int(seconds/.05)):
        now = i*.05
        tracker.update(game.levels(now), now)
        d = planner.step(replace(obs, timestamp=now), now)
        if d.tap:
            game.press(d.tap, now, d.action == 'release')
            taps.append((now, d.tap, d.action))
            planner.acknowledge(d, now, True)
    return taps


class PlannerWithHotbarTests(unittest.TestCase):
    def test_never_presses_a_slot_that_reads_as_cooling(self):
        game = Game()
        run(make_planner(), game)
        self.assertEqual(game.wasted, [])

    def test_basic_attacks_fill_time_when_all_skills_are_cooling(self):
        game = Game()
        taps = run(make_planner(), game, seconds=30)
        late = [k for t, k, _ in taps if t > 10]
        self.assertGreater(late.count('x'), 20)

    def test_every_skill_still_used_when_ready(self):
        game = Game()
        run(make_planner(), game, seconds=60)
        self.assertTrue(set('qwertasdfgy') <= {k for _, k in game.casts})

    def test_dual_blades_end_up_on(self):
        game = Game()
        run(make_planner(), game, seconds=10)
        self.assertTrue(game.dual)
        self.assertEqual(sum(k == 'h' for _, k in game.casts), 1)

    def test_dropped_dual_blade_press_is_retried(self):
        game = Game(drop=['h'])
        taps = run(make_planner(), game, seconds=10)
        self.assertTrue(game.dual)
        self.assertEqual(sum(k == 'h' for _, k, _ in taps), 2)

    def test_dropped_skill_press_is_skipped_then_retried(self):
        game = Game(drop=['q'])
        taps = run(make_planner(), game, seconds=10)
        q = [t for t, k, _ in taps if k == 'q']
        self.assertGreaterEqual(len(q), 2)
        self.assertGreaterEqual(q[1]-q[0], 2.5)
        self.assertIn('q', {k for _, k in game.casts})

    def test_hotbar_that_never_darkens_falls_back_to_plain_spam(self):
        p = make_planner()
        tracker = CooldownTracker();p.hotbar = tracker
        obs = Observation(0, scene='room', position=(100, 200), facing='right',
                          enemies=(Enemy('e', 150, 200),), perception_valid=True)
        keys = []
        for i in range(400):
            now = i*.05
            tracker.update(dict(BRIGHT), now)  # wrong region: always "ready"
            d = p.step(replace(obs, timestamp=now), now)
            if d.tap:
                keys.append(d.tap);p.acknowledge(d, now, True)
        self.assertTrue(p.hotbar_gave_up)
        self.assertTrue(set('qwertasd') <= set(keys))

    def test_without_hotbar_behaviour_is_unchanged(self):
        p = make_planner()
        self.assertIsNone(p.hotbar)
        self.assertTrue(p.usable(p.skills[0], 0))


if __name__ == '__main__':
    unittest.main()


class GreyAndToggleTests(unittest.TestCase):
    def test_saturation_tells_grey_from_colour(self):
        from dungeon_farm.hotbar import slot_saturation
        x0, y0, w, h = REGION
        crop = np.zeros((h, w, 3), dtype=np.uint8)
        for key, (cx, cy) in SLOTS.items():
            crop[cy-y0-8:cy-y0+8, cx-x0-8:cx-x0+8] = (76, 76, 76) if key in 'wr' else (40, 90, 200)
        sat = slot_saturation(crop)
        self.assertLess(sat['w'], 5);self.assertLess(sat['r'], 5)
        self.assertGreater(sat['q'], 100)

    def test_grey_slot_is_never_ready(self):
        t = CooldownTracker()
        sat = {k: (0 if k in 'wr' else 150) for k in BRIGHT}
        for i in range(10): t.update(dict(BRIGHT), i*.05, sat)
        self.assertFalse(t.ready('w', .45));self.assertFalse(t.ready('r', .45))
        self.assertTrue(t.ready('q', .45))

    def test_greyed_out_skills_are_not_pressed(self):
        # As in the 2026-11-14 run: W and R are pure grey (unusable).
        p = make_planner();tracker = CooldownTracker();p.hotbar = tracker
        game = Game()
        obs = Observation(0, scene='room', position=(100, 200), facing='right',
                          enemies=(Enemy('e', 150, 200),), perception_valid=True)
        keys = []
        for i in range(600):
            now = i*.05
            sat = {k: (0 if k in 'wr' else 150) for k in BRIGHT}
            tracker.update(game.levels(now), now, sat)
            d = p.step(replace(obs, timestamp=now), now)
            if d.tap:
                game.press(d.tap, now, d.action == 'release');keys.append(d.tap);p.acknowledge(d, now, True)
        self.assertNotIn('w', keys);self.assertNotIn('r', keys)
        self.assertIn('q', keys)

    def test_previous_round_h_press_does_not_block_this_round(self):
        p = make_planner()
        p.last_used['h'] = -5  # carried over from an earlier run in the same session
        game = Game()
        run(p, game, seconds=5)
        self.assertTrue(game.dual)

    def test_h_waits_for_its_slot_to_light_up(self):
        p = make_planner();tracker = CooldownTracker();p.hotbar = tracker
        game = Game()
        obs = Observation(0, scene='room', position=(100, 200), facing='right',
                          enemies=(Enemy('e', 150, 200),), perception_valid=True)
        pressed = None
        for i in range(100):
            now = i*.05
            levels = game.levels(now)
            if now < 1.8:  # every icon dimmed by an animation
                levels = {k: v*.4 for k, v in levels.items()} if now > .2 else levels
            tracker.update(levels, now)
            d = p.step(replace(obs, timestamp=now), now)
            if d.tap:
                if d.tap == 'h' and pressed is None: pressed = now
                game.press(d.tap, now);p.acknowledge(d, now, True)
        self.assertGreaterEqual(pressed, 1.8)
        self.assertTrue(game.dual)
