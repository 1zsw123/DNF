import itertools
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from dungeon_farm.runtime import Control
from dungeon_farm.cycle import replay


class TeamCycleTests(unittest.TestCase):
    def scenario(self,mode,confirmed=True):
        control=Control();control.team_config={'mode':mode};control.team_round=['session',1] if confirmed else None
        link=Mock();control.team_link=link;link.ready.side_effect=[False,False,True]
        win=Mock();win.game.return_value=9;win.foreground.return_value=True;win.u.GetAsyncKeyState.return_value=0
        keys=Mock(last_chord_state={});keys.chord.return_value=True
        entered=False;events=[]
        def report(value):
            nonlocal entered
            events.append(value['state'])
            if value['state']=='waiting_leader':entered=True
        def key(name,*args):
            nonlocal entered
            if name=='retry':entered=True
            return True
        keys.key.side_effect=key
        def signals(*args,**kwargs):
            return {'texts':['根特东门普通级'],'retry':None if entered else (500,70),'finished':not entered}
        screen=Mock();screen.poll.side_effect=signals
        connection=Mock();connection.sample.return_value={'scene':2}
        ticks=itertools.count(0,2)
        with tempfile.TemporaryDirectory() as folder,patch('dungeon_farm.cycle.DATA',Path(folder)), \
             patch('dungeon_farm.cycle.Windows',return_value=win),patch('dungeon_farm.cycle.CycleInputs',return_value=keys), \
             patch('dungeon_farm.cycle.ScreenSignals',return_value=screen),patch('dungeon_farm.cycle.CoordinateConnection',return_value=connection), \
             patch('dungeon_farm.cycle.read_doors',return_value=[{'direction':'right'}]), \
             patch('dungeon_farm.inventory.inspect_inventory',return_value={'gold':100,'cubes':1000}), \
             patch('dungeon_farm.cycle.time.monotonic',side_effect=lambda:next(ticks)):
            result=replay(control,report,1,{},reenter=True)
        return result,keys,events,link

    def test_follower_maintains_then_waits_without_f10(self):
        result,keys,events,link=self.scenario('follower')
        self.assertEqual(result,'reentered');keys.key.assert_not_called()
        self.assertIn('waiting_leader',events)
        link.update.assert_any_call(phase='ready',ready_for=['session',1])
        self.assertEqual([c.args[0] for c in keys.chord.call_args_list],['sell','repair'])

    def test_leader_only_retries_after_partner_ready(self):
        result,keys,events,link=self.scenario('leader')
        self.assertEqual(result,'reentered');self.assertEqual(link.ready.call_count,3)
        self.assertEqual([c.args[0] for c in keys.key.call_args_list],['retry'])
        self.assertLess(events.index('waiting_partner_ready'),events.index('retrying'))

    def test_unbound_follower_round_never_acknowledges_readiness(self):
        result,keys,events,link=self.scenario('follower',False)
        self.assertEqual(result,'team_round_unconfirmed');keys.key.assert_not_called()
        self.assertNotIn('waiting_leader',events)
