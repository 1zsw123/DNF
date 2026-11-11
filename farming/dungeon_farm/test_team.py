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
        door={'x':1000,'y':300};near={'xyz':(910,310,0)};far={'xyz':(300,310,0)}
        self.assertTrue(gate_ready((900,300),near,door))
        self.assertFalse(gate_ready((900,300),far,door))
        self.assertFalse(gate_ready((900,300),near,door,False))
        self.assertFalse(gate_ready((300,300),None,door))
        self.assertTrue(gate_ready((300,300),far,door))
        self.assertTrue(close_to_partner((910,310),near))

    def test_follower_actions_never_attack_and_never_use_lost_coordinates(self):
        partner={'xyz':(200,300,0)}
        for own,peer,linked in (((0,300),partner,True),((200,300),partner,True),((0,300),None,True),((0,300),partner,False)):
            decision=follower_decision(own,peer,linked)
            self.assertIsNone(decision.tap)
            if not peer or not linked:self.assertIsNone(decision.destination)


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
