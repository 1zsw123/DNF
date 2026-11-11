import unittest
from dungeon_farm.cycle import ReplayPlan,fresh_dungeon_room,dungeon_difficulty
from dungeon_farm.screen_signals import lifecycle_signals

def item(text,x=500,y=350):return [[[x-20,y-5],[x+20,y-5],[x+20,y+5],[x-20,y+5]],text,.99]

class ReplayTests(unittest.TestCase):
    def test_arden_alias_and_hidden_suffix_require_known_replay_difficulty(self):
        s={'texts':['决战的都市-亚顿-']}
        self.assertIsNone(dungeon_difficulty(s,'阿登高地'))
        self.assertFalse(fresh_dungeon_room(s,{'scene':20},10,[{}],'冒险级','阿登高地'))
        self.assertTrue(fresh_dungeon_room(s,{'scene':20},10,[{}],'冒险级','阿登高地',True))
        self.assertFalse(fresh_dungeon_room({'texts':['决战的都市-亚顿-王者级']},{'scene':20},10,[{}],'冒险级','阿登高地',True))
        self.assertEqual(dungeon_difficulty({'texts':['决战的都市-亚顿-冒']},'阿登高地'),'冒险级')
    def test_selected_pursuit_card_is_recognized_without_difficulty_badge(self):
        s=lifecycle_signals([item('追击歼灭战',425,73),item('Lv.062~065',425,85),item('返回城镇',590,442)],'追击歼灭战')
        self.assertTrue(s['target_selected'])
        self.assertEqual(dungeon_difficulty({'texts':['追击歼灭战-地狱级']},'追击歼灭战'),'地狱级')
        self.assertEqual(dungeon_difficulty({'texts':['追击歼灭战-菩通级']},'追击歼灭战'),'普通级')
    def test_enough_cubes_sells_without_disassembling(self):
        p=ReplayPlan();p.needs_disassembly=False;s={'retry':(500,70)}
        self.assertEqual(p.action(s,0),'sell');p.acknowledge('sell',0)
        self.assertEqual(p.action(s,2),'repair');p.acknowledge('repair',2)
        self.assertEqual(p.action(s,4),'retry')
    def test_pursuit_difficulty_is_not_confused_with_east_gate(self):
        s={'texts':['追擊殲滅戰','王者級']}
        self.assertEqual(dungeon_difficulty(s,'追击歼灭战'),'王者级')
        self.assertIsNone(dungeon_difficulty(s))
    def test_actual_ghost_countdown_is_detected_without_coin_word(self):
        self.assertTrue(lifecycle_signals([item('按下X键使用硬币',310,240),item('幽灵状态',310,348)])['dead'])
        self.assertFalse(lifecycle_signals([item('幽灵状态',100,400)])['dead'])
    def test_disassembly_notice_is_confirmed_before_retry(self):
        s=lifecycle_signals([item('裝備分解成功!',310,180),item('確認',318,310),item('相悅商店',440,250)])
        self.assertEqual(s['notice'],'disassemble')
        self.assertEqual(s['notice_confirm'],(318.,310.))
        self.assertFalse(s['overlay'])
        p=ReplayPlan();p.acknowledge('disassemble',0)
        self.assertEqual(p.action(s,2),'confirm_notice')
        p.acknowledge('confirm_notice',2)
        self.assertEqual(p.action({},3),'repair')

    def test_merchant_name_never_triggers_escape(self):
        self.assertFalse(lifecycle_signals([item('相悦商店')])['overlay'])
        self.assertFalse(lifecycle_signals([item('神秘商店')])['overlay'])
        self.assertIsNone(lifecycle_signals([item('确认',300,300)])['notice_confirm'])

    def test_replay_preserves_the_observed_difficulty(self):
        s={'texts':['根特東門','冒險級']}
        self.assertEqual(dungeon_difficulty(s),'冒险级')
        self.assertTrue(fresh_dungeon_room(s,{'scene':20},10,[{}],'冒险级'))
        self.assertFalse(fresh_dungeon_room({'texts':['根特东门','普通级']},{'scene':20},10,[{}],'冒险级'))

    def test_entry_targets_card_not_quick_party_or_hud(self):
        s=lifecycle_signals([item('根特东门',400,255),item('M 根特东门',595,390),item('返回城镇',595,440)])
        self.assertEqual(s['dungeon_option'],(400.,255.))
        self.assertTrue(s['selection'])
        self.assertIsNone(lifecycle_signals([item('根特东门',540,10)])['dungeon_option'])

    def test_reentry_accepts_both_start_sides(self):
        signals={'texts':['根特東門','普通級']}
        for direction in ('left','right'):
            self.assertTrue(fresh_dungeon_room(signals,{'scene':20},10,[{'direction':direction}]))
        self.assertFalse(fresh_dungeon_room(signals,{'scene':10},10,[{'direction':'left'}]))
        self.assertFalse(fresh_dungeon_room(signals,None,10,[{'direction':'right'}]))
        self.assertFalse(fresh_dungeon_room({'texts':['根特南门','普通级']},{'scene':20},10,[{}]))
        self.assertFalse(fresh_dungeon_room({'texts':['根特东门','王者级']},{'scene':20},10,[{}]))
        self.assertFalse(fresh_dungeon_room(dict(signals,finished=True),{'scene':20},10,[{}]))

    def test_maintenance_order_and_no_duplicate_actions(self):
        p=ReplayPlan();s={'retry':(500,350)}
        self.assertIsNone(p.action({},0))
        self.assertEqual(p.action(s,0),'disassemble');p.acknowledge('disassemble',0)
        self.assertIsNone(p.action(s,1))
        self.assertEqual(p.action(s,1.5),'repair');p.acknowledge('repair',1.5)
        self.assertIsNone(p.action({},3))
        self.assertEqual(p.action(s,3),'retry');p.acknowledge('retry',3)
        self.assertIsNone(p.action(s,40))
        self.assertEqual(p.action({'exhausted':True},41),'fatigue_empty')

    def test_fatigue_error_is_distinct_from_positive_fatigue(self):
        self.assertTrue(lifecycle_signals([item('疲勞值不足，無法進入地下城')])['exhausted'])
        self.assertTrue(lifecycle_signals([item('您的疲劳值'),item('不足，不能进入地下城')])['exhausted'])
        self.assertFalse(lifecycle_signals([item('剩余疲劳值 121/156')])['exhausted'])
        self.assertFalse(lifecycle_signals([item('普通级')])['exhausted'])

    def test_retry_requires_button_region(self):
        self.assertIsNone(lifecycle_signals([item('再次挑战者',200,80)])['retry'])
        self.assertEqual(lifecycle_signals([item('再次挑戰 F10',520,70),item('返回城鎮 F12',520,140)])['retry'],(520.,70.))
        self.assertIsNone(lifecycle_signals([item('再次挑战',520,70)])['retry'])

    def test_close_inventory_before_maintenance_and_bound_retries(self):
        p=ReplayPlan();s={'overlay':True}
        for i in range(4):
            self.assertEqual(p.action(s,i*2),'close_overlay');p.acknowledge('close_overlay',i*2)
        self.assertEqual(p.action(s,10),'overlay_blocked')
        self.assertEqual(p.stage,'wait_result')

    def test_no_continue_on_death(self):
        s=lifecycle_signals([item('是否使用复活币复活角色')])
        self.assertEqual(ReplayPlan().action(s,0),'character_dead')
