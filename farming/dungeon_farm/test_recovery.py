import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from dungeon_farm.recovery import plan, pick, RECOVERABLE
from dungeon_farm.runtime import Control, run


class PlanTests(unittest.TestCase):
    def test_clicks_return_to_town_text_only(self):
        found=[((320,200),'返回城镇',.95),((320,240),'退出游戏',.97),((320,160),'游戏设置',.9)]
        self.assertEqual(plan(found,0),('click',(320,200)))

    def test_never_clicks_quit_or_character_select(self):
        found=[((320,240),'退出游戏',.97),((320,200),'选择角色',.95)]
        self.assertEqual(plan(found,0),('escape',None))
        self.assertIsNone(pick([((1,1),'返回城镇退出游戏',.99)],('返回城镇',)))

    def test_confirms_only_a_town_dialog_after_clicking(self):
        found=[((320,200),'是否返回城镇？',.9),((280,260),'确定',.95),((360,260),'取消',.95)]
        self.assertEqual(plan(found,1),('confirm',(280,260)))
        self.assertEqual(plan([((280,260),'确定',.95)],1),('escape',None))
        self.assertEqual(plan(found,0)[0],'escape')  # never confirm a dialog we did not open

    def test_low_confidence_text_is_ignored(self):
        self.assertEqual(plan([((320,200),'返回城镇',.4)],0),('escape',None))


class AutoReentryTests(unittest.TestCase):
    def go(self,rounds,left='town',auto=True,**kw):
        control=Control();control.auto_recover=auto
        with tempfile.TemporaryDirectory() as folder, patch('dungeon_farm.runtime.DATA',Path(folder)), \
             patch('dungeon_farm.town_entry.prepare',return_value='ready') as entry, \
             patch('dungeon_farm.runtime.run_round',side_effect=rounds) as fight, \
             patch('dungeon_farm.recovery.leave_dungeon',return_value=left) as leave, \
             patch('dungeon_farm.cycle.replay',return_value='finished'):
            updates=[];run(control,'追击歼灭战',updates.append,repeat=True,max_runs=1,**kw)
        return updates,entry,fight,leave

    def test_stuck_round_leaves_and_reenters_same_difficulty(self):
        updates,entry,fight,leave=self.go([{'result':'stuck'},{'result':'finished','scene':1,'profile':{}}],difficulty='地狱级')
        leave.assert_called_once()
        self.assertEqual(fight.call_count,2)
        self.assertEqual(entry.call_count,2)
        self.assertTrue(entry.call_args_list[1].kwargs['allow_town_entry'])
        self.assertEqual(entry.call_args_list[1].kwargs['difficulty'],'地狱级')
        self.assertEqual(updates[-1]['completed'],1)
        self.assertIn('auto_reentry',[u['state'] for u in updates])

    def test_three_failures_in_a_row_stop_the_run(self):
        updates,entry,fight,leave=self.go([{'result':'error'}]*5)
        self.assertEqual(leave.call_count,3)
        self.assertEqual(fight.call_count,4)
        self.assertEqual(updates[-1]['result'],'error')

    def test_failed_exit_stops(self):
        updates,entry,fight,leave=self.go([{'result':'no_path'}],left='exit_failed')
        self.assertEqual(fight.call_count,1)
        self.assertEqual(updates[-1]['result'],'no_path')

    def test_user_stop_and_fatigue_never_reenter(self):
        self.assertNotIn('stopped',RECOVERABLE);self.assertNotIn('fatigue_empty',RECOVERABLE)
        updates,entry,fight,leave=self.go([{'result':'stopped'}])
        leave.assert_not_called()

    def test_option_off_keeps_old_stop_behaviour(self):
        updates,entry,fight,leave=self.go([{'result':'stuck'}],auto=False)
        leave.assert_not_called();self.assertEqual(fight.call_count,1)

    def test_town_return_skips_exit_and_walks_back_in(self):
        updates,entry,fight,leave=self.go([{'result':'returned_town'},{'result':'finished','scene':1,'profile':{}}])
        leave.assert_not_called()
        self.assertEqual(entry.call_count,2)


if __name__=='__main__':unittest.main()
