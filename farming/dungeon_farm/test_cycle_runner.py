import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from dungeon_farm.runtime import Control,run

class RunnerTests(unittest.TestCase):
    def test_identity_mismatch_stops_before_inventory_or_entry(self):
        selected={'name':'不打团','role_type':0x16f0000}
        for actual in ({'name':'上头枪','role_type':0x16f0000},
                       {'name':'不打团','role_type':0x16f0004}):
            with self.subTest(actual=actual), tempfile.TemporaryDirectory() as folder, \
                 patch('dungeon_farm.runtime.DATA',Path(folder)), \
                 patch('dungeon_farm.characters.discover_current',return_value=actual), \
                 patch('dungeon_farm.utilities.maintenance') as maintenance, \
                 patch('dungeon_farm.town_entry.prepare') as entry, \
                 patch('dungeon_farm.runtime.run_round') as fight:
                control=Control();control.character=selected;updates=[]
                run(control,'阿登高地',updates.append,allow_town_entry=True)
                maintenance.assert_not_called();entry.assert_not_called();fight.assert_not_called()
                self.assertEqual(updates[-1]['result'],'wrong_character')

    def test_matching_identity_reaches_entry_and_stops_at_fatigue(self):
        selected={'name':'不打团','role_type':0x16f0000}
        with tempfile.TemporaryDirectory() as folder, patch('dungeon_farm.runtime.DATA',Path(folder)), \
             patch('dungeon_farm.characters.discover_current',return_value=selected), \
             patch('dungeon_farm.town_entry.prepare',return_value='fatigue_empty') as entry:
            control=Control();control.character=selected;updates=[]
            run(control,'阿登高地',updates.append)
            entry.assert_called_once();self.assertEqual(updates[-1]['result'],'fatigue_empty')
    def test_verified_town_reentry_keeps_count_and_original_difficulty(self):
        with tempfile.TemporaryDirectory() as folder, patch('dungeon_farm.runtime.DATA',Path(folder)), \
             patch('dungeon_farm.town_entry.prepare',return_value='ready') as entry, \
             patch('dungeon_farm.runtime.run_round',return_value={'result':'finished','scene':123,'profile':{}}), \
             patch('dungeon_farm.cycle.replay',side_effect=['town_reentry','fatigue_empty']):
            updates=[];run(Control(),'阿登高地',updates.append,repeat=True,difficulty='冒险级')
            self.assertEqual(entry.call_count,2)
            self.assertFalse(entry.call_args_list[0].kwargs['allow_town_entry'])
            self.assertTrue(entry.call_args_list[1].kwargs['allow_town_entry'])
            self.assertEqual(entry.call_args_list[1].kwargs['difficulty'],'冒险级')
            self.assertEqual(updates[-1]['result'],'fatigue_empty')
            self.assertEqual(updates[-1]['completed'],2)

    def test_town_reentry_requires_matching_character_and_town_scene(self):
        from unittest.mock import Mock
        from dungeon_farm.cycle import verified_arden_town
        reader=Mock(local_root=10);reader.uint.side_effect=lambda addr:100 if addr==10 else 0
        reader.actor.return_value={'name':'上头枪'}
        signals={'map_title':'悬空的海港'};profile={'self_name':'上头枪'}
        self.assertTrue(verified_arden_town(signals,reader,profile))
        self.assertFalse(verified_arden_town({'map_title':'阿登高地'},reader,profile))
        self.assertFalse(verified_arden_town(signals,reader,{'self_name':'不打团'}))
        reader.uint.side_effect=lambda addr:100
        self.assertFalse(verified_arden_town(signals,reader,profile))

    def test_follower_does_not_apply_old_map_entry_preset(self):
        control=Control();control.team_config={'mode':'follower'}
        with tempfile.TemporaryDirectory() as folder, patch('dungeon_farm.runtime.DATA',Path(folder)), \
             patch('dungeon_farm.team_link.TeamLink'), \
             patch('dungeon_farm.runtime.selected_profile',return_value={'self_name':'follower'}), \
             patch('dungeon_farm.town_entry.prepare') as entry, \
             patch('dungeon_farm.runtime.run_round',return_value={'result':'stopped'}) as follow:
            updates=[];run(control,'阿登高地',updates.append,repeat=True,allow_town_entry=True)
            entry.assert_not_called();follow.assert_called_once()
            self.assertEqual(updates[-1]['result'],'stopped')

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
