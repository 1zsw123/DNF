import itertools
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from dungeon_farm.runtime import Control
from dungeon_farm.cycle import replay


class TeamCycleTests(unittest.TestCase):
    def test_follower_reentry_requires_party_and_current_session(self):
        from dungeon_farm.team import follower_reentered
        signals={'texts':['冰霜幽暗密林地狱级']}
        sample={'scene':2,'party':{'name':'leader'}}
        peer={'active':True,'phase':'combat','session':'new','round':2}
        self.assertTrue(follower_reentered(signals,sample,1,peer,['new',1]))
        self.assertFalse(follower_reentered(signals,sample,1,peer,['old',1]))
        self.assertFalse(follower_reentered(signals,{'scene':2},1,peer,['new',1]))
        self.assertFalse(follower_reentered(signals,sample,2,peer,['new',1]))
        self.assertFalse(follower_reentered({'finished':True},sample,1,peer,['new',1]))
        self.assertFalse(follower_reentered(signals,sample,1,None,['new',1]))

    def scenario(self,mode,confirmed=True,reenter=True,overlay=False):
        control=Control();control.team_config={'mode':mode};control.team_round=['session',1] if confirmed else None
        link=Mock();control.team_link=link;link.ready.side_effect=[False,False,True]
        link.remote.return_value={'active':True,'phase':'combat','session':'session','round':2}
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
            return {'texts':['根特东门普通级'],'retry':None if entered else (500,70),'finished':not entered,
                    'overlay':overlay,'notice':'repair' if overlay else None,'notice_confirm':(5,5) if overlay else None}
        screen=Mock();screen.poll.side_effect=signals
        connection=Mock();connection.sample.return_value={'scene':2,'party':{'name':'leader'}}
        ticks=itertools.count(0,2)
        with tempfile.TemporaryDirectory() as folder,patch('dungeon_farm.cycle.DATA',Path(folder)), \
             patch('dungeon_farm.cycle.Windows',return_value=win),patch('dungeon_farm.cycle.CycleInputs',return_value=keys), \
             patch('dungeon_farm.cycle.ScreenSignals',return_value=screen),patch('dungeon_farm.cycle.CoordinateConnection',return_value=connection), \
             patch('dungeon_farm.cycle.read_doors',return_value=[{'direction':'right'}]), \
             patch('dungeon_farm.inventory.inspect_inventory',return_value={'gold':100,'cubes':1000}) as inventory, \
             patch('dungeon_farm.cycle.time.monotonic',side_effect=lambda:next(ticks)):
            result=replay(control,report,1,{},reenter=reenter)
            if mode=='follower':inventory.assert_not_called()
        return result,keys,events,link

    def test_follower_waits_without_any_inventory_or_maintenance_input(self):
        result,keys,events,link=self.scenario('follower')
        self.assertEqual(result,'reentered');keys.key.assert_not_called()
        self.assertIn('waiting_leader',events)
        link.update.assert_any_call(phase='ready',ready_for=['session',1])
        keys.chord.assert_not_called();keys.click.assert_not_called();keys.close_overlay.assert_not_called()

    def test_follower_final_round_stops_without_maintenance_or_ready_signal(self):
        result,keys,events,link=self.scenario('follower',reenter=False)
        self.assertEqual(result,'finished');self.assertEqual(keys.method_calls,[])
        self.assertNotIn('waiting_leader',events)

    def test_follower_does_not_click_notices_or_dismiss_user_panels(self):
        result,keys,events,link=self.scenario('follower',overlay=True)
        self.assertEqual(result,'replay_timeout');self.assertEqual(keys.method_calls,[])
        self.assertIn('follower_overlay',events);self.assertNotIn('waiting_leader',events)

    def test_leader_only_retries_after_partner_ready(self):
        result,keys,events,link=self.scenario('leader')
        self.assertEqual(result,'reentered');self.assertEqual(link.ready.call_count,3)
        self.assertEqual([c.args[0] for c in keys.key.call_args_list],['retry'])
        self.assertLess(events.index('waiting_partner_ready'),events.index('retrying'))
        self.assertEqual([c.args[0] for c in keys.chord.call_args_list],['sell','repair'])

    def test_unbound_follower_round_never_acknowledges_readiness(self):
        result,keys,events,link=self.scenario('follower',False)
        self.assertEqual(result,'team_round_unconfirmed');keys.key.assert_not_called()
        self.assertNotIn('waiting_leader',events)
