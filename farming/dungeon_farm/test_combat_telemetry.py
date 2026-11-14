import math
import struct
import time
import unittest
from unittest.mock import Mock
from dungeon_farm.combat_telemetry import SoloReader, observe,own_g_object,G_OBJECTS


class SoloTests(unittest.TestCase):
    def test_g_prerequisite_requires_type_name_and_this_characters_owner(self):
        for vt,name in G_OBJECTS.items():
            raw=bytearray(0x25c)
            for offset,value in ((0,vt+0x1000),(0x90,33),(0x258,900)):
                struct.pack_into('<I',raw,offset,value)
            reader=Mock();reader.uint.return_value=100
            reader.process.read.return_value=(name+'\0').encode('utf-16le')
            self.assertTrue(own_g_object(reader,300,raw,0x1000,100))
            reader.uint.return_value=101
            self.assertFalse(own_g_object(reader,300,raw,0x1000,100))
            reader.uint.return_value=100;reader.process.read.return_value='伪装对象\0'.encode('utf-16le')
            self.assertFalse(own_g_object(reader,300,raw,0x1000,100))

    def test_ghent_support_squad_matches_real_names_and_types(self):
        import json
        from pathlib import Path
        preset=json.loads((Path(__file__).parent/'presets.json').read_text(encoding='utf8'))['根特东门']
        allowed={int(k,16):v for k,v in preset['apc_targets'].items()}
        cases=[(0x16fb6a4,'支援兵菲力普'),(0x16fb6a4,'隊長高頓'),
               (0x16fb6a4,'支援兵拉斐爾'),(0x16fb6a4,'支援兵奧古斯丁'),
               (0x16fa1a4,'突擊兵莉莉安娜')]
        for vt,name in cases:
            with self.subTest(name=name):
                r=self.reader();r.delta=0;r.leader_name='上头召唤师'
                def raw(address,size):
                    if address==900:return (name+'\0').encode('utf-16le').ljust(size,b'\0')
                    result=bytearray(size)
                    for offset,value in ((0,vt),(0x90,273),(0xb8,200),(0x258,900)):
                        struct.pack_into('<I',result,offset,value)
                    struct.pack_into('<3f',result,0x18c,137,240,0)
                    return bytes(result)
                r.process.read.side_effect=raw
                connection=Mock(reader=r)
                connection.sample.return_value={'scene':200,'self_base':100,'self':(50,60,0),'time':time.monotonic()}
                obs,sample=observe(connection,30,allowed_types=set(),allowed_apcs=allowed)
                self.assertEqual(len(obs.enemies),1)
                self.assertTrue(obs.perception_valid)
                self.assertEqual(sample['unverified_monsters'],[])

    def reader(self):
        r=Mock()
        r.local_root=10;r.local_xyz=20;r.pid=30;r.self_name='上头狂战'
        r.uint.side_effect=lambda address:{10:100,100+0xb8:200}.get(address,0)
        r.actor.return_value={'name':'上头狂战','xyz':(50.,60.,0.)}
        r.object_addresses.return_value=(100,300)
        r.process.xyz.return_value=(50.,60.,0.)
        return r

    def test_no_teammate_is_required(self):
        self.assertTrue(SoloReader(self.reader()).sample()['solo'])

    def test_wrong_local_character_is_rejected(self):
        r=self.reader();r.actor.return_value={'name':'other','xyz':(50.,60.,0.)}
        self.assertIsNone(SoloReader(r).sample())

    def test_stale_local_actor_or_mirror_is_rejected(self):
        for values in ((80.,60.,0.),(math.nan,60.,0.)):
            r=self.reader();r.process.xyz.return_value=values
            self.assertIsNone(SoloReader(r).sample())
        r=self.reader();r.object_addresses.return_value=(300,)
        self.assertIsNone(SoloReader(r).sample())

    def test_unknown_monster_cannot_be_mistaken_for_empty_room(self):
        r=self.reader();r.delta=0
        def raw(address,size):
            result=bytearray(size)
            struct.pack_into('<I',result,0,0x1800000)
            struct.pack_into('<I',result,0x90,273 if address==100 else 529)
            struct.pack_into('<I',result,0xb8,200)
            return bytes(result)
        r.process.read.side_effect=raw
        connection=Mock(reader=r)
        connection.sample.return_value={'scene':200,'self_base':100,'self':(50,60,0),'time':time.monotonic()}
        obs,sample=observe(connection,30)
        self.assertFalse(obs.perception_valid)
        self.assertEqual(sample['unverified_monsters'],['0x1800000'])

    def test_ignore_unknown_preserves_known_targets_and_presend_validation(self):
        from dungeon_farm.planner import Decision,attack_still_valid
        r=self.reader();r.delta=0;r.object_addresses.return_value=(100,300,400)
        def raw(address,size):
            result=bytearray(size)
            for offset,value in ((0,0x16ff424 if address==400 else 0x1800000),
                                 (0x90,529),(0xb8,200)):
                struct.pack_into('<I',result,offset,value)
            if address==400:struct.pack_into('<3f',result,0x18c,100,60,0)
            return bytes(result)
        r.process.read.side_effect=raw
        connection=Mock(reader=r)
        connection.sample.return_value={'scene':200,'self_base':100,'self':(50,60,0),'time':time.monotonic()}
        obs,sample=observe(connection,30,allowed_types={0x16ff424},ignore_unknown=True)
        self.assertTrue(obs.perception_valid)
        self.assertEqual([e.identity for e in obs.enemies],[hex(400)])
        self.assertEqual(sample['unverified_monsters'],['0x1800000'])
        self.assertTrue(attack_still_valid(Decision('combat',tap='x',target_id=hex(400)),obs,obs.scene))
        r.object_addresses.return_value=(100,300)
        obs,sample=observe(connection,30,allowed_types={0x16ff424},ignore_unknown=True)
        self.assertTrue(obs.perception_valid);self.assertEqual(obs.enemies,())
        self.assertEqual(len(sample['unverified_details']),1)

    def test_enemy_apc_requires_both_verified_type_and_name(self):
        for name,expected in [('TMH通信兵',True),('其他角色',False),('尼貝爾',False)]:
            r=self.reader();r.delta=0;r.leader_name='上头召唤师'
            def raw(address,size):
                if address==900:return (name+'\0').encode('utf-16le').ljust(size,b'\0')
                result=bytearray(size)
                struct.pack_into('<I',result,0,0x16fb6a4)
                struct.pack_into('<I',result,0x90,273)
                struct.pack_into('<I',result,0xb8,200)
                struct.pack_into('<I',result,0x258,900)
                struct.pack_into('<3f',result,0x18c,100,200,0)
                return bytes(result)
            r.process.read.side_effect=raw
            connection=Mock(reader=r)
            connection.sample.return_value={'scene':200,'self_base':100,'self':(50,60,0),'time':time.monotonic()}
            obs,sample=observe(connection,30,allowed_types=set(),allowed_apcs={0x16fb6a4:['TMH通信兵']},friendly_apcs={0x16fb6a4:['尼貝爾']})
            self.assertEqual(bool(obs.enemies),expected)
            self.assertEqual(bool(sample['unverified_monsters']),not expected and name!='尼貝爾')


if __name__=='__main__':unittest.main()


class PendingEnemyTests(unittest.TestCase):
    def frame(self,coords):
        from dungeon_farm import combat_telemetry
        r=Mock();r.local_root=10;r.delta=0;r.self_name='上头狂战';r.leader_name='x'
        r.uint.side_effect=lambda address:{10:100,100+0xb8:200}.get(address,0)
        r.object_addresses.return_value=tuple([100]+[300+i for i in range(len(coords))])
        def raw(address,size):
            result=bytearray(size)
            for offset,value in ((0,0x017930C4),(0x90,529),(0xb8,200)):
                struct.pack_into('<I',result,offset,value)
            if address>=300:struct.pack_into('<3f',result,0x18c,*coords[address-300])
            return bytes(result)
        r.process.read.side_effect=raw
        connection=Mock(reader=r)
        connection.sample.return_value={'scene':200,'self_base':100,'self':(50,60,0),'time':time.monotonic()}
        return observe(connection,30),combat_telemetry

    def test_uninitialized_enemy_is_pending_not_a_lost_frame(self):
        (obs,sample),_=self.frame([(137,240,0),(0,0,0)])
        self.assertEqual(len(obs.enemies),1)
        self.assertEqual(sample['pending_enemies'],1)

    def test_all_pending_still_returns_frame(self):
        (obs,sample),_=self.frame([(0,0,0),(math.nan,1,1)])
        self.assertEqual(obs.enemies,())
        self.assertEqual(sample['pending_enemies'],2)

    def test_failure_reason_is_recorded(self):
        from dungeon_farm import combat_telemetry
        connection=Mock();connection.sample.return_value=None
        self.assertIsNone(observe(connection,30))
        self.assertEqual(combat_telemetry.LAST_FAILURE,'own_sample')


class GenericApcTests(unittest.TestCase):
    def frame(self,name,generic=True,friends=None):
        r=Mock();r.local_root=10;r.delta=0;r.self_name='上头狂战';r.leader_name='x'
        r.uint.side_effect=lambda address:{10:100,100+0xb8:200}.get(address,0)
        r.object_addresses.return_value=(100,300)
        def raw(address,size):
            if size==96:return name.encode('utf-16le')+bytes(2)
            result=bytearray(size)
            for offset,value in ((0,0x016FA1A4),(0x90,273),(0xb8,200),(0x258,0x5000)):
                struct.pack_into('<I',result,offset,value)
            if address==300:struct.pack_into('<3f',result,0x18c,166,311,0)
            return bytes(result)
        r.process.read.side_effect=raw
        connection=Mock(reader=r)
        connection.sample.return_value={'scene':200,'self_base':100,'self':(50,60,0),'time':time.monotonic()}
        return observe(connection,30,allowed_apcs={},friendly_apcs=friends or {},generic_monsters=generic)

    def test_generic_mode_targets_unlisted_human_enemy(self):
        obs,sample=self.frame('德魯伊·梅亞')
        self.assertEqual(len(obs.enemies),1)
        self.assertEqual(sample['guessed_apcs'],{'0x12c':'德魯伊·梅亞'})
        self.assertEqual(sample['unverified_monsters'],[])

    def test_known_ally_is_never_targeted(self):
        obs,sample=self.frame('偉大的杜爾夫',friends={0x016FA1A4:['偉大的杜爾夫']})
        self.assertEqual(obs.enemies,())

    def test_preset_modes_still_require_listed_names(self):
        obs,sample=self.frame('德魯伊·梅亞',generic=False)
        self.assertEqual(obs.enemies,())
        self.assertEqual(sample['unverified_monsters'],['0x16fa1a4'])
