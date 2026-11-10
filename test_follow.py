"""Offline tests: no screen capture and no keyboard injection."""
import unittest
import cv2
import numpy as np
from follow import Tracker, FollowPolicy, NameOCR, glyphs, enhance_scene, vertical_gate_hint, INPUT, C, Windows
from tracking import VerifiedFlow
import threading
from unittest.mock import patch
from pathlib import Path


class VisualTests(unittest.TestCase):
    def test_localize_name_with_changed_background(self):
        # White glyphs are preserved while the world background changes.
        sample = np.full((22, 118, 3), (30, 45, 100), np.uint8)
        cv2.putText(sample, 'LEADER', (2, 17), cv2.FONT_HERSHEY_SIMPLEX, .55,
                    (250, 250, 250), 1, cv2.LINE_8)
        tracker = Tracker(sample, (0, 65))
        world = np.full((600, 800, 3), (85, 45, 25), np.uint8)
        roi = world[250:272, 400:518]
        roi[glyphs(sample) > 0] = 250
        point, score = tracker.locate(glyphs(world))
        self.assertGreater(score, .98)
        self.assertEqual(point, (459, 326))

    def test_missing_name_and_party_frame_are_rejected(self):
        sample = np.zeros((20, 100, 3), np.uint8)
        cv2.putText(sample, 'SELF', (0, 16), 0, .6, (255, 255, 255), 1)
        tracker = Tracker(sample)
        frame = np.zeros((600, 800, 3), np.uint8)
        frame[20:40, 20:120] = sample
        self.assertIsNone(tracker.locate(glyphs(frame))[0])

    def test_alternate_name_style_has_its_own_foot_offset(self):
        a = np.zeros((20, 100, 3), np.uint8)
        b = a.copy()
        cv2.putText(a, 'IDLE', (0,16), 0, .6, (255,255,255), 1)
        cv2.putText(b, 'MOVE', (0,16), 0, .6, (255,255,255), 1)
        tracker = Tracker(a, (0,90))
        tracker.variants.append(Tracker(b, (-10,75)))
        frame = np.zeros((600,800,3), np.uint8)
        frame[250:270,300:400] = b
        point, score = tracker.locate(glyphs(frame))
        self.assertGreater(score, .98)
        self.assertEqual(point, (340,335))


class MotionTests(unittest.TestCase):
    def test_axes_and_dead_zone(self):
        p = FollowPolicy()
        self.assertEqual(p.step((300, 200), (100, 250), (600, 800), 1)[0], {'right', 'up'})
        self.assertEqual(p.step((110, 255), (100, 250), (600, 800), 2)[0], set())

    def test_loss_of_self_always_stops(self):
        p = FollowPolicy()
        p.step((790, 300), (700, 300), (600, 800), 1)
        self.assertEqual(p.step(None, None, (600, 800), 1.1)[0], set())

    def test_offscreen_chase_is_bounded_and_reacquires_visible_leader(self):
        p = FollowPolicy()
        p.step((790, 300), (600, 300), (600, 800), 1)
        self.assertEqual(p.step(None, (610, 300), (600, 800), 1.2)[0], {'right'})
        self.assertEqual(p.step(None, (620, 300), (600, 800), 3)[0], {'right'})
        self.assertEqual(p.step(None, (630, 300), (600, 800), 5.2)[0], set())
        self.assertEqual(p.step((400,300),(630,300),(600,800),5.3)[0], {'left'})
        p.reset()
        p.step((400, 300), (200, 300), (600, 800), 2)
        self.assertEqual(p.step(None, (210, 300), (600, 800), 2.1)[0], {'right'})
        self.assertFalse(p.step(None,(220,300),(600,800),3.3)[0])

    def test_obstacle_stops_instead_of_holding_forever(self):
        p = FollowPolicy()
        p.step((600, 300), (200, 300), (600, 800), 1)
        keys, note = p.step((600, 300), (200, 300), (600, 800), 5)
        self.assertFalse(keys)
        self.assertTrue(note.startswith('可能卡住'))
        self.assertFalse(p.step((600,300),(200,300),(600,800),5.2)[0])
        self.assertEqual(p.step((600,300),(200,300),(600,800),5.8)[0], {'right'})

    def test_keep_nameplates_apart_but_close_distance_at_door(self):
        p = FollowPolicy()
        self.assertFalse(p.step((500,300),(460,300),(600,800),1,gap=55)[0])
        self.assertEqual(p.step((790,300),(750,300),(600,800),2,gap=55)[0], {'right'})

    def test_native_input_structure_size(self):
        self.assertEqual(C.sizeof(INPUT), 40 if C.sizeof(C.c_void_p) == 8 else 28)

    def test_door_push_continues_when_already_beside_leader(self):
        p = FollowPolicy()
        self.assertEqual(p.step((780,300),(779,300),(600,800),1)[0], {'right'})
        self.assertEqual(p.step(None,(785,300),(600,800),2)[0], {'right'})

    def test_clipped_self_at_door_gets_only_a_brief_final_push(self):
        p=FollowPolicy()
        p.step((790,300),(798,300),(600,800),1)
        self.assertEqual(p.step(None,None,(600,800),1.2)[0],{'right'})
        self.assertFalse(p.step(None,None,(600,800),1.7)[0])

    def test_camera_scroll_is_not_mistaken_for_being_stuck(self):
        p=FollowPolicy()
        p.step((600,300),(400,300),(600,800),1)
        keys,note=p.step((600,300),(400,300),(600,800),7,scene_moved=True)
        self.assertEqual(keys,{'right'})
        self.assertFalse(note.startswith('可能卡住'))

    def test_manual_arrow_detection_ignores_bot_held_keys(self):
        w=Windows.__new__(Windows)
        w.lock=threading.RLock();w.held={'right'}
        class FakeUser32:
            def GetAsyncKeyState(self,vk):
                return 0x8000 if vk in (0x25,0x27) else 0
        w.u=FakeUser32()
        self.assertEqual(w.manual_arrows(),{'left'})

    def test_run_double_taps_only_on_horizontal_direction_start(self):
        w=Windows.__new__(Windows);w.lock=threading.RLock();w.held=set()
        calls=[];w.foreground=lambda hwnd: True
        w.send=lambda key,up=False: calls.append((key,up))
        with patch('follow.time.sleep'):
            w.apply({'right'},1,run=True)
            w.apply({'right'},1,run=True)
            w.apply(set(),1,run=True)
        self.assertEqual(calls,[('right',False),('right',True),('right',False),('right',True)])


class DarkSceneTests(unittest.TestCase):
    @unittest.skipUnless((Path(__file__).parent/'dark-dungeon-fixture.png').exists(), 'Private screenshot fixture is not distributed')
    def test_vertical_gate_requires_two_crystals_and_correct_lane(self):
        im=enhance_scene(cv2.imread(str(Path(__file__).parent/'dark-dungeon-fixture.png')))[0]
        self.assertEqual(vertical_gate_hint(im,(340,530)),'down')
        self.assertIsNone(vertical_gate_hint(im,(527,455)))

    def test_floor_position_alone_is_not_a_bottom_door(self):
        p=FollowPolicy()
        self.assertFalse(p.step((500,545),(500,545),(614,819),1)[0])
    def test_dark_letters_are_lifted_without_changing_hud(self):
        frame=np.full((614,819,3),18,np.uint8)
        frame[:90]=200;frame[550:]=180
        cv2.putText(frame,'LEADER',(250,280),0,.7,(68,68,68),1)
        enhanced,dark,transition=enhance_scene(frame)
        self.assertTrue(dark);self.assertFalse(transition)
        self.assertGreater(int(enhanced[250:285,240:400].max()),145)
        self.assertTrue(np.array_equal(frame[:90],enhanced[:90]))

    def test_black_loading_scene_waits_without_inventing_details(self):
        frame=np.zeros((614,819,3),np.uint8)
        frame[:90]=200;frame[550:]=180
        result,dark,transition=enhance_scene(frame)
        self.assertTrue(transition)


class NameRecognitionTests(unittest.TestCase):
    @unittest.skipUnless((Path(__file__).parent/'current-dungeon-fixture.png').exists(), 'Private screenshot fixture is not distributed')
    def test_two_player_dungeon_guild_tags_can_locate_obscured_self(self):
        frame=cv2.imread(str(Path(__file__).parent/'current-dungeon-fixture.png'))
        tags=[([[430,315],[490,315],[490,333],[430,333]],'明月清风',.95),
              ([[645,327],[705,327],[705,345],[645,345]],'明月清风',.95)]
        hits={'leader':((673,481),.98,(0,0,1,1),'上头狂战')}
        result=NameOCR.guild_pair_fallback(tags,frame,{},hits,scale=1)
        self.assertEqual(result['self'][0],(460,470))

    @unittest.skipUnless(all((Path(__file__).parent/p).exists() for p in ('capture_self.png','current-dungeon-fixture.png')), 'Private screenshot fixtures are not distributed')
    def test_guild_fallback_is_disabled_in_town_or_with_three_markers(self):
        frame=cv2.imread(str(Path(__file__).parent/'capture_self.png'))
        tags=[([[430,315],[490,315],[490,333],[430,333]],'明月清风',.95),
              ([[645,327],[705,327],[705,345],[645,345]],'明月清风',.95)]
        hits={'leader':((673,481),.98,(0,0,1,1),'上头狂战')}
        self.assertNotIn('self',NameOCR.guild_pair_fallback(tags,frame,{},hits.copy(),scale=1))
        dungeon=cv2.imread(str(Path(__file__).parent/'current-dungeon-fixture.png'))
        tags.append(([[30,315],[90,315],[90,333],[30,333]],'明月清风',.95))
        self.assertNotIn('self',NameOCR.guild_pair_fallback(tags,dungeon,{},hits.copy(),scale=1))

    def test_names_survive_level_change_and_ocr_font_confusion(self):
        results = [([[100,200],[200,200],[200,220],[100,220]], 'Lv24上头影列', .9),
                   ([[400,230],[500,230],[500,250],[400,250]], 'Lv70上头狂战', .95)]
        hits = NameOCR.parse(results, (614,819,3), {}, scale=1, top=0)
        self.assertEqual(hits['self'][0], (150,338))
        self.assertEqual(hits['leader'][0], (450,368))

    def test_overlapping_names_and_duplicate_candidates_are_rejected(self):
        box = [[100,200],[200,200],[200,220],[100,220]]
        self.assertFalse(NameOCR.parse([(box,'上头影刃上头狂战',.95)], (614,819,3), {}, scale=1))
        self.assertNotIn('leader', NameOCR.parse([(box,'上头狂战',.95),(box,'上头狂战',.95)], (614,819,3), {}, scale=1))

    def test_party_header_names_are_never_world_positions(self):
        box = [[30,20],[130,20],[130,40],[30,40]]
        self.assertFalse(NameOCR.parse([(box,'上头狂战',.99)], (614,819,3), {}, scale=1))

    def test_adjacent_names_are_split_by_character_boxes(self):
        text = '上头影纳上头狂战'
        boxes = [[[100+i*12,200],[112+i*12,200],[112+i*12,218],[100+i*12,218]] for i in range(8)]
        result = [[[100,200],[196,200],[196,218],[100,218]], text,.95,boxes,list(text),[.95]*8]
        hits = NameOCR.parse([result], (614,819,3), {}, scale=1)
        self.assertEqual(hits['self'][0][0],124)
        self.assertEqual(hits['leader'][0][0],172)


class VerifiedFlowTests(unittest.TestCase):
    def sample(self):
        frame=np.zeros((400,600,3),np.uint8)
        cv2.putText(frame,'SMALL',(150,200),0,.6,(255,255,255),1)
        return frame

    def test_tracks_confirmed_label_translation(self):
        frame=self.sample();flow=VerifiedFlow()
        flow.seed(frame,(145,180,235,205),(190,300),1)
        translated=cv2.warpAffine(frame,np.float32([[1,0,35],[0,1,8]]),(600,400))
        point,score=flow.update(translated,1.2)
        self.assertIsNotNone(point)
        self.assertLess(np.hypot(point[0]-225,point[1]-308),2)

    def test_blank_screen_or_expired_identity_stops_tracking(self):
        frame=self.sample();flow=VerifiedFlow()
        flow.seed(frame,(145,180,235,205),(190,300),1)
        self.assertIsNone(flow.update(np.zeros_like(frame),1.2)[0])
        flow.seed(frame,(145,180,235,205),(190,300),1)
        self.assertIsNone(flow.update(frame,3.1)[0])


if __name__ == '__main__':
    unittest.main()
