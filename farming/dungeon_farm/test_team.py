import copy
import json
import socket
import struct
import time
import unittest
from unittest.mock import Mock
from dungeon_farm.team import read_partner,gate_ready,close_to_partner,follower_decision
from dungeon_farm.team_link import TeamLink,validate_config


class PartyTests(unittest.TestCase):
    def test_actual_map_selects_friendly_apcs_not_old_gui_preset(self):
        from pathlib import Path
        from dungeon_farm.team import follower_scene_preset,follower_link_ready
        presets=json.loads((Path(__file__).parent/'presets.json').read_text(encoding='utf8'))
        name,preset=follower_scene_preset(presets,'追擊殲滅戰－冒險級')
        self.assertEqual(name,'追击歼灭战')
        self.assertIn('背叛者郎克',preset['friendly_apcs']['0x16fb6a4'])
        name,preset=follower_scene_preset(presets,'根特东门-冒险级')
        self.assertNotIn('背叛者郎克',preset.get('friendly_apcs',{}).get('0x16fb6a4',[]))
        self.assertIsNone(follower_scene_preset(presets,'未知副本')[0])
        unknown=follower_scene_preset(presets,'列车上的海贼-地狱级')[1]
        self.assertEqual(unknown['friendly_apcs'],{'0x16fe0e4':['偉大的杜爾夫']})
        self.assertNotIn('friendly_apcs',presets['溶岩穴'])
        self.assertTrue(follower_link_ready({'phase':'combat','active':False},{'xyz':(10,20,0)}))
        for peer,actor in ((None,{}),({'phase':'combat'},None),({'phase':'ready'},{}),({'phase':'stopped'},{})):
            self.assertFalse(follower_link_ready(peer,actor))

    def test_map_title_ignores_chat_and_inventory_names(self):
        from dungeon_farm.screen_signals import lifecycle_signals
        def item(x,y,text):return [[[x,y],[x+40,y],[x+40,y+10],[x,y+10]],text,.99]
        signals=lifecycle_signals([item(500,3,'追击歼灭战-冒险级'),item(20,300,'阿登高地')])
        self.assertEqual(signals['map_title'],'追击歼灭战-冒险级')

    def reader(self,name='小号',kind=273):
        reader=Mock(delta=0)
        reader.object_addresses.return_value=[100]
        raw=bytearray(0x25c)
        for offset,value in ((0,0x16fc11c),(0x90,kind),(0xb8,77),(0x258,900)):
            struct.pack_into('<I',raw,offset,value)
        struct.pack_into('<3f',raw,0x18c,200,300,0)
        reader.process.read.side_effect=lambda address,size:bytes(raw) if address in (100,101) else (name+'\0').encode('utf-16le')
        return reader

    def test_partner_requires_full_name_player_kind_and_unique_membership(self):
        self.assertEqual(read_partner(self.reader(),77,'小号')['xyz'],(200.,300.,0.))
        self.assertIsNone(read_partner(self.reader('小号宠物'),77,'小号'))
        self.assertIsNone(read_partner(self.reader(kind=529),77,'小号'))
        reader=self.reader();reader.object_addresses.return_value=[100,101]
        self.assertIsNone(read_partner(reader,77,'小号'))
        reader=self.reader();reader.object_addresses.side_effect=[[100],[]]
        self.assertIsNone(read_partner(reader,77,'小号'))

    def test_leader_waits_at_door_for_partner_and_live_link(self):
        door={'direction':'right','x':1000,'y':300};near={'xyz':(910,310,0)};far={'xyz':(300,310,0)}
        self.assertTrue(gate_ready((900,300),near,door))
        self.assertFalse(gate_ready((900,300),far,door))
        self.assertFalse(gate_ready((900,300),near,door,False))
        self.assertFalse(gate_ready((300,300),None,door))
        self.assertTrue(gate_ready((300,300),far,door))
        self.assertTrue(close_to_partner((910,310),near))

    def test_follower_actions_never_attack_and_never_use_lost_coordinates(self):
        partner={'xyz':(200,300,0)}
        for own,peer,linked in (((0,300),partner,True),((200,300),partner,True),((0,300),None,True),((0,300),partner,False)):
            decision=follower_decision(own,peer,linked,room_clear=True,doors=[{'direction':'right','x':250,'y':300}])
            self.assertIsNone(decision.tap)
            if not peer or not linked:self.assertIsNone(decision.destination)

    def test_waits_during_combat_even_when_leader_is_at_door(self):
        result=follower_decision((0,300),{'xyz':(900,300,0)},True,
                                 room_clear=False,doors=[{'direction':'right','x':1000,'y':300}])
        self.assertEqual(result.state,'waiting_room_clear')
        self.assertIsNone(result.destination);self.assertFalse(result.move)

    def test_clear_room_requires_leader_at_unambiguous_available_exit(self):
        leader={'xyz':(900,300,0)};doors=[{'direction':'right','x':1000,'y':300}]
        result=follower_decision((100,300),leader,True,room_clear=True,doors=doors)
        self.assertEqual(result.destination,(940,300));self.assertIsNone(result.tap)
        for peer,exits in ((leader,[]),({'xyz':(500,300,0)},doors),
                           (leader,doors+[{'direction':'left','x':800,'y':300}])):
            result=follower_decision((100,300),peer,True,room_clear=True,doors=exits)
            self.assertEqual(result.state,'waiting_leader_door');self.assertIsNone(result.destination)

    def test_second_wave_revokes_movement_and_new_room_resets_wait(self):
        from dungeon_farm.waves import WaveTracker
        waves=WaveTracker();leader={'xyz':(900,300,0)};doors=[{'direction':'right','x':1000,'y':300}]
        def step(enemies,now):
            clear,_=waves.update(enemies,now)
            return follower_decision((100,300),leader,True,room_clear=clear,doors=doors)
        self.assertIsNone(step(True,0).destination)
        self.assertIsNone(step(False,1).destination)
        self.assertEqual(step(False,4.6).state,'following')
        self.assertIsNone(step(True,4.7).destination)
        waves.reset()
        self.assertIsNone(step(False,9).destination)

    def test_standing_beside_leader_is_not_door_arrival(self):
        leader={'xyz':(840,300,0)};door={'direction':'right','x':1000,'y':300}
        result=follower_decision((840,300),leader,True,room_clear=True,doors=[door])
        self.assertEqual(result.state,'following');self.assertEqual(result.destination,(940,300))
        result=follower_decision((940,300),leader,True,room_clear=True,doors=[door])
        self.assertEqual(result.state,'following_entering');self.assertEqual(result.destination,(1025,300))
        # Disappearing door or a leader off the exit lane revokes completion.
        self.assertNotEqual(follower_decision((940,300),leader,True,room_clear=True).state,'following_close')
        off_lane={'xyz':(940,390,0)}
        self.assertEqual(follower_decision((940,300),off_lane,True,room_clear=True,doors=[door]).state,'waiting_leader_door')

    def test_each_exit_direction_targets_inside_door_not_leader(self):
        for direction,target in [('left',(1060,300)),('right',(940,300)),('up',(1000,345)),('down',(1000,255))]:
            door={'direction':direction,'x':1000,'y':300};leader={'xyz':(1000,300,0)}
            result=follower_decision((500,500),leader,True,room_clear=True,doors=[door])
            self.assertEqual(result.destination,target)
            self.assertEqual(follower_decision(target,leader,True,room_clear=True,doors=[door]).state,'following_entering')
        self.assertEqual(follower_decision((1000,300),leader,True,room_clear=True,doors=[{'x':1000,'y':300}]).state,'waiting_leader_door')

    def test_portal_push_persists_beyond_inside_waypoint_and_stops_on_new_wave(self):
        from dungeon_farm.door_approach import DoorApproach
        for direction,inside,axis,sign in [('left',(360,300),0,-1),('right',(240,300),0,1),
                                           ('up',(300,345),1,-1),('down',(300,255),1,1)]:
            door={'direction':direction,'x':300,'y':300};leader={'xyz':(300,300,0)}
            approach=DoorApproach()
            decision=follower_decision(inside,leader,True,room_clear=True,doors=[door],door_approach=approach)
            self.assertEqual(decision.state,'following_entering')
            self.assertGreater(sign*(decision.destination[axis]-300),0)
            first=decision.destination
            decision=follower_decision(first,leader,True,room_clear=True,doors=[door],door_approach=approach)
            self.assertGreater(sign*(decision.destination[axis]-first[axis]),0)
            for ready,linked in ((False,True),(True,False)):
                stopped=follower_decision(first,leader,linked,room_clear=ready,doors=[door],door_approach=approach)
                self.assertIsNone(stopped.destination)


class LinkTests(unittest.TestCase):
    def config(self,mode='leader'):
        return dict(mode=mode,partner='小号' if mode=='leader' else '大号',host='127.0.0.1',port=18770,token='a'*32)

    def test_config_requires_named_pair_and_private_numeric_address(self):
        validate_config(self.config(),'大号')
        for edit in ({'partner':'大号'},{'token':''},{'port':80}):
            with self.assertRaises(ValueError):validate_config(self.config()|edit,'大号')
        for host in ('example.com','8.8.8.8','0.0.0.0'):
            with self.assertRaises(ValueError):validate_config(self.config('follower')|{'host':host},'小号')

    def test_real_lan_handshake_ready_round_and_stale_heartbeat(self):
        with socket.socket() as probe:probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
        leader=TeamLink(self.config()|{'port':port},'大号',bind_host='127.0.0.1')
        follower=TeamLink(self.config('follower')|{'port':port},'小号')
        try:
            leader.update(round=1,phase='combat',active=True)
            follower.update(phase='combat',active=True)
            until=time.monotonic()+3
            while not (leader.remote() and follower.remote()) and time.monotonic()<until:time.sleep(.02)
            self.assertIsNotNone(leader.remote());self.assertIsNotNone(follower.remote())
            state=leader.snapshot()
            follower.update(phase='ready',ready_for=[state['session'],1])
            until=time.monotonic()+3
            while not leader.ready() and time.monotonic()<until:time.sleep(.02)
            self.assertTrue(leader.ready())
            leader.update(round=2);self.assertFalse(leader.ready())
            bad=copy.deepcopy(follower.snapshot());bad['name']='其他人'
            self.assertFalse(leader.accept(bad))
            # Stop polling before simulating a stale peer.
            follower.close();leader.seen=time.monotonic()-4
            self.assertIsNone(leader.remote());self.assertFalse(leader.ready())
        finally:follower.close();leader.close()


if __name__=='__main__':unittest.main()
