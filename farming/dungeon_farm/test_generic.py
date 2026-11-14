import json
import struct
import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
import cv2
import numpy as np
from dungeon_farm.generic import GENERIC,combined_preset,room_ready
from dungeon_farm.combat_telemetry import observe
from dungeon_farm.minimap import read_minimap,MinimapRoute
from dungeon_farm.runtime import Control,run


class GenericTests(unittest.TestCase):
    def test_entry_needs_real_room_not_town_menu_or_old_scene(self):
        sample={'scene':123};doors=[{'direction':'right'}]
        self.assertTrue(room_ready({},sample,doors))
        for signal in ('selection','finished','retry','exhausted','dead','overlay','notice'):
            self.assertFalse(room_ready({signal:True},sample,doors))
        for own in (None,{'scene':0}):self.assertFalse(room_ready({},own,doors))
        self.assertFalse(room_ready({},sample,[]))
        self.assertFalse(room_ready({},sample,doors,123))

    def test_new_monster_class_is_targeted_but_helper_and_unclassified_player_are_not(self):
        r=Mock(local_root=10,delta=0,self_name='me',leader_name='peer')
        r.uint.side_effect=lambda addr:{10:100,100+0xb8:200}.get(addr,0)
        r.object_addresses.return_value=(100,300,400,500)
        def memory(addr,size):
            if addr==900:return '友军机器人\0'.encode('utf-16le').ljust(size,b'\0')
            raw=bytearray(size)
            for off,v in ((0,0x1800000),(0x90,273 if addr in (100,500) else 529),
                          (0xb8,200),(0x258,900 if addr==400 else 0)):
                struct.pack_into('<I',raw,off,v)
            struct.pack_into('<3f',raw,0x18c,200,300,0)
            return bytes(raw)
        r.process.read.side_effect=memory
        conn=Mock(reader=r);conn.sample.return_value={'scene':200,'self_base':100,'self':(50,60,0),'time':time.monotonic()}
        observation,sample=observe(conn,30,allowed_types=set(),allowed_apcs={},
                                  friendly_monsters={0x1800000:['友军机器人']},generic_monsters=True,ignore_unknown=True)
        self.assertEqual([e.identity for e in observation.enemies],[hex(300)])
        self.assertEqual(len(sample['unverified_details']),1)
        self.assertEqual(sample['unverified_details'][0]['address'],hex(500))

    def test_combined_friends_are_kept_and_map_routes_are_not_copied(self):
        presets={'one':{'friendly_monsters':{'x':['a']},'route_rules':[1]},
                 'two':{'friendly_monsters':{'x':['b','a']}}}
        combined=combined_preset(presets)
        self.assertEqual(combined['friendly_monsters']['x'],['a','b'])
        self.assertEqual(combined['route_rules'],[])
        self.assertIn('偉大的杜爾夫',combined['friendly_apcs']['0x16fe0e4'])

    def drawing(self,ox=540,oy=60):
        frame=np.zeros((480,640,3),np.uint8)
        cv2.rectangle(frame,(ox-8,20),(636,oy+30),(40,70,100),1)
        path=[(0,0),(1,0),(1,1),(2,1)]
        points={node:(round(ox+14.5*node[0]),round(oy+14.5*node[1])) for node in path}
        for x,y in points.values():frame[y-5:y+6,x-5:x+6]=(70,25,5)
        for a,b in zip(path,path[1:]):cv2.line(frame,points[a],points[b],(130,100,60),3)
        x,y=points[path[-1]];frame[y-2:y+3,x-2:x+3]=(20,50,200)
        x,y=points[path[0]];frame[y-1:y+2,x:x+2]=(220,150,40)
        return frame

    def test_dynamic_map_has_no_arden_origin_or_fixed_boss(self):
        for ox,oy in ((540,60),(570,95),(500,120)):
            value=read_minimap(self.drawing(ox,oy),GENERIC)
            self.assertIsNotNone(value)
            self.assertEqual(len(value['path']),4)
            self.assertEqual(value['source'],'generic_visible')
        self.assertIsNone(read_minimap(np.zeros((480,640,3),np.uint8),GENERIC))

    def test_fog_reveal_extends_remembered_graph(self):
        route=MinimapRoute(incremental=True)
        a={'current':(0,0),'boss':(2,0),'edges':[((0,0),(1,0))]}
        route.confirm('a',a,1);route.confirm('a',a,2)
        b={**a,'edges':a['edges']+[((1,0),(2,0))]}
        route.confirm('a',b,3);route.confirm('a',b,4)
        self.assertEqual(route.path,[(0,0),(1,0),(2,0)])
        route.confirm('a',a,5)
        self.assertEqual(route.path,[(0,0),(1,0),(2,0)])

    def test_world_scenery_outside_hud_cannot_supply_room_connections(self):
        frame=self.drawing()
        frame[120:175,475:635]=(70,25,5)
        frame[140:143,500:502]=(220,150,40)
        debug={};value=read_minimap(frame,GENERIC,debug)
        self.assertIsNotNone(value)
        self.assertEqual(len(value['rooms']),4)
        self.assertLess(debug['bounds'][3],120)
        frame[20:91,532:637]=0
        self.assertIsNone(read_minimap(frame,GENERIC))

    def test_fog_icons_provide_heading_but_do_not_invent_a_corridor(self):
        from dungeon_farm.generic import boss_heading
        frame=np.zeros((480,640,3),np.uint8)
        cv2.rectangle(frame,(532,20),(636,90),(40,70,100),1)
        frame[59:62,540:542]=(220,150,40)
        frame[58:63,596:601]=(20,50,200)
        value=read_minimap(frame,GENERIC)
        self.assertIsNotNone(value)
        self.assertEqual(value['edges'],[]);self.assertIsNone(value['path'])
        route=MinimapRoute(incremental=True)
        route.confirm('a',value,1);route.confirm('a',value,2)
        self.assertEqual(boss_heading(route,[{'direction':'left'},{'direction':'right'}]),'right')
        self.assertIsNone(route.choose('a',[{'direction':'right'}]))

    def test_generic_never_uses_town_selection_and_can_repeat_without_named_map(self):
        with tempfile.TemporaryDirectory() as folder,patch('dungeon_farm.runtime.DATA',Path(folder)), \
             patch('dungeon_farm.generic.prepare',return_value='ready') as entry, \
             patch('dungeon_farm.utilities.maintenance') as maintenance, \
             patch('dungeon_farm.runtime.run_round',return_value={'result':'finished','scene':123,'profile':{}}), \
             patch('dungeon_farm.cycle.replay',side_effect=['town_reentry','fatigue_empty']):
            updates=[]
            run(Control(),GENERIC,updates.append,repeat=True,allow_town_entry=True,difficulty='王者级')
            maintenance.assert_not_called()
            self.assertEqual(entry.call_count,2)
            self.assertTrue(all(not call.kwargs['allow_town_entry'] for call in entry.call_args_list))
            self.assertEqual(updates[-1]['result'],'fatigue_empty')
            self.assertEqual(updates[-1]['completed'],2)

    def test_manual_town_return_waits_for_next_entry_without_maintaining_or_counting_clear(self):
        with tempfile.TemporaryDirectory() as folder,patch('dungeon_farm.runtime.DATA',Path(folder)), \
             patch('dungeon_farm.generic.prepare',return_value='ready') as entry, \
             patch('dungeon_farm.runtime.run_round',side_effect=[{'result':'returned_town'},{'result':'stopped'}]) as fight, \
             patch('dungeon_farm.cycle.replay') as replay:
            updates=[];run(Control(),GENERIC,updates.append)
            self.assertEqual(entry.call_count,2);self.assertEqual(fight.call_count,2)
            replay.assert_not_called()
            self.assertEqual(updates[-1]['completed'],0)
            self.assertIn('waiting_manual_entry',[u['state'] for u in updates])


if __name__=='__main__':unittest.main()


class AllyGuessTests(unittest.TestCase):
    def test_unlisted_human_enemy_is_targeted_until_it_dies(self):
        from dungeon_farm.generic import AllyGuess
        from dungeon_farm.planner import Enemy
        g=AllyGuess()
        mia=Enemy('0x1',166,311);imp=Enemy('0x2',100,200)
        kept,allies=g.filter('r1',(mia,imp),{'0x1':'德魯伊·梅亞'},0)
        self.assertEqual(kept,(mia,imp))
        kept,allies=g.filter('r1',(mia,),{'0x1':'德魯伊·梅亞'},10)
        self.assertEqual(kept,(mia,))
        kept,allies=g.filter('r1',(),{},12)  # it died
        self.assertEqual((kept,allies),((),()))

    def test_guess_that_never_dies_is_treated_as_ally(self):
        from dungeon_farm.generic import AllyGuess
        from dungeon_farm.planner import Enemy
        g=AllyGuess(patience=25);npc=Enemy('0x9',50,50)
        g.filter('r1',(npc,),{'0x9':'某NPC'},0)
        self.assertEqual(g.filter('r1',(npc,),{'0x9':'某NPC'},20)[0],(npc,))
        kept,allies=g.filter('r1',(npc,),{'0x9':'某NPC'},26)
        self.assertEqual((kept,allies),((),('某NPC',)))
        # Later rooms in this run: the same name is no longer targeted.
        other=Enemy('0xa',10,10)
        self.assertEqual(g.filter('r2',(Enemy('0xb',1,1),other),{'0xb':'某NPC'},30)[0],(other,))

    def test_clock_does_not_run_while_real_monsters_remain(self):
        from dungeon_farm.generic import AllyGuess
        from dungeon_farm.planner import Enemy
        g=AllyGuess(patience=25);npc=Enemy('0x9',50,50);imp=Enemy('0x2',1,1)
        for t in range(0,60,5):
            kept,allies=g.filter('r1',(npc,imp),{'0x9':'某NPC'},t)
            self.assertEqual(allies,())
        self.assertEqual(g.filter('r1',(npc,),{'0x9':'某NPC'},61)[0],(npc,))
