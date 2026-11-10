import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from dungeon_farm.runtime import Control,run

class RunnerTests(unittest.TestCase):
    def test_final_requested_round_still_maintains_without_reentry(self):
        with tempfile.TemporaryDirectory() as folder, patch('dungeon_farm.runtime.DATA',Path(folder)), \
             patch('dungeon_farm.town_entry.prepare',return_value='ready'), \
             patch('dungeon_farm.runtime.run_round',return_value={'result':'finished','scene':123,'profile':{}}), \
             patch('dungeon_farm.cycle.replay',return_value='finished') as replay:
            updates=[];run(Control(),'追击歼灭战',updates.append,repeat=True,max_runs=1,difficulty='普通级')
            self.assertFalse(replay.call_args.kwargs['reenter'])
            self.assertEqual(updates[-1]['completed'],1)
            self.assertEqual(updates[-1]['result'],'finished')
            result=json.loads((Path(folder)/'farming-results.jsonl').read_text(encoding='utf8'))
            self.assertEqual(result['difficulty'],'普通级')
            self.assertIsNone(result['net_gold'])
    def test_high_difficulty_is_rejected_before_input(self):
        with tempfile.TemporaryDirectory() as folder, patch('dungeon_farm.runtime.DATA',Path(folder)), patch('dungeon_farm.town_entry.prepare') as entry:
            updates=[];run(Control(),'追击歼灭战',updates.append,difficulty='地狱级',allow_town_entry=True)
            entry.assert_not_called()
            self.assertEqual(updates[-1]['result'],'error')
    def test_repeat_stops_at_fatigue_error_after_verified_reentry(self):
        with tempfile.TemporaryDirectory() as folder, patch('dungeon_farm.runtime.DATA',Path(folder)), \
             patch('dungeon_farm.town_entry.prepare',return_value='ready'), \
             patch('dungeon_farm.runtime.run_round',return_value={'result':'finished','scene':123,'profile':{}}) as fight, \
             patch('dungeon_farm.cycle.replay',side_effect=['reentered','fatigue_empty']) as replay:
            updates=[];run(Control(),'根特东门',updates.append,repeat=True)
            self.assertEqual(fight.call_count,2)
            self.assertEqual(replay.call_count,2)
            self.assertEqual(updates[-1]['result'],'fatigue_empty')
            self.assertEqual(updates[-1]['completed'],2)
            self.assertEqual(json.loads((Path(folder)/'cycle-status.json').read_text(encoding='utf8'))['result'],'fatigue_empty')

    def test_unknown_enemy_does_not_maintain_or_retry(self):
        with tempfile.TemporaryDirectory() as folder, patch('dungeon_farm.runtime.DATA',Path(folder)), \
             patch('dungeon_farm.town_entry.prepare',return_value='ready'), \
             patch('dungeon_farm.runtime.run_round',return_value={'result':'unknown_monsters'}) as fight, \
             patch('dungeon_farm.cycle.replay') as replay:
            updates=[];run(Control(),'根特东门',updates.append,repeat=True)
            replay.assert_not_called();self.assertEqual(fight.call_count,1)
            self.assertEqual(updates[-1]['completed'],0)
