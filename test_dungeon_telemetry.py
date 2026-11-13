import struct
import unittest
from dungeon_telemetry import DungeonTelemetry, LOCAL_ROOT, LOCAL_XYZ, ROLE_TYPES, follow_directions


class FakeProcess:
    def __init__(self):
        self.memory = {}
    def put(self, address, data):
        self.memory.update({address+i: byte for i, byte in enumerate(data)})
    def read(self, address, size):
        try: return bytes(self.memory[address+i] for i in range(size))
        except KeyError: return None
    def xyz(self, address):
        raw = self.read(address, 12)
        return struct.unpack('<3f', raw) if raw else None
    def close(self): pass


class TelemetryTests(unittest.TestCase):
    def setUp(self):
        self.p = FakeProcess()
        self.scene, self.own, self.leader, self.vector = 0x100000, 0x200000, 0x300000, 0x400000
        self.p.put(LOCAL_ROOT, struct.pack('<I', self.own))
        self.p.put(LOCAL_XYZ, struct.pack('<3f', 110, 346, 0))
        self.add_actor(self.own, '上头影刃', (110, 346, 0))
        self.add_actor(self.leader, '上头狂战', (559, 244, 0))
        self.set_list([self.own, self.leader])
        self.r = DungeonTelemetry(1, self.p)
    def add_actor(self, address, name, xyz):
        raw = bytearray(0x25c)
        struct.pack_into('<I', raw, 0, ROLE_TYPES[name])
        struct.pack_into('<I', raw, 0xb8, self.scene)
        struct.pack_into('<3f', raw, 0x18c, *xyz)
        struct.pack_into('<I', raw, 0x258, address + 0x1000)
        self.p.put(address, raw)
        self.p.put(address + 0x1000, (name+'\0').encode('utf-16le').ljust(64, b'\0'))
    def set_list(self, addresses):
        self.p.put(self.scene+0x10, struct.pack('<3I', self.vector, self.vector+4*len(addresses), self.vector+4*len(addresses)))
        self.p.put(self.vector, struct.pack('<'+'I'*len(addresses), *addresses))
    def test_live_pair_and_direction(self):
        s = self.r.sample()
        self.assertEqual(s['leader'], (559, 244, 0))
        self.assertEqual(follow_directions(s), ({'right', 'up'}, True))

    def test_dynamic_pair_accepts_new_names_types_and_rejects_nonplayer_or_stale(self):
        for address,name,vt in ((self.own,'新小号',0x16fb6a4),(self.leader,'新大号',0x16fa214)):
            self.p.put(address,struct.pack('<I',vt))
            self.p.put(address+0x90,struct.pack('<I',273))
            self.p.put(address+0x1000,(name+'\0').encode('utf-16le').ljust(64,b'\0'))
        r=DungeonTelemetry(1,self.p,self_name='新小号',leader_name='新大号',role_types={},automatic_role_types=True)
        self.assertEqual(r.sample()['leader_name'],'新大号')
        self.p.put(self.leader+0x90,struct.pack('<I',529))
        self.assertIsNone(r.sample())
        self.p.put(self.leader+0x90,struct.pack('<I',273))
        self.set_list([self.own]);self.assertIsNone(r.sample())

    def test_dynamic_wrong_local_name_never_reverses_the_pair(self):
        for address in (self.own,self.leader):self.p.put(address+0x90,struct.pack('<I',273))
        r=DungeonTelemetry(1,self.p,self_name='上头狂战',leader_name='上头影刃',role_types={},automatic_role_types=True)
        self.assertIsNone(r.sample())
    def test_stale_town_position_is_rejected(self):
        self.p.put(LOCAL_XYZ, struct.pack('<3f', 923, 161, 0))
        self.assertIsNone(self.r.sample())
    def test_removed_actor_is_not_reused(self):
        self.assertIsNotNone(self.r.sample())
        self.set_list([self.own])
        self.assertIsNone(self.r.sample())
    def test_different_scene_is_rejected(self):
        self.p.put(self.leader+0xb8, struct.pack('<I', self.scene+100))
        self.assertIsNone(self.r.sample())
    def test_duplicate_identity_is_rejected(self):
        other = 0x500000
        self.add_actor(other, '上头狂战', (9, 9, 0))
        self.set_list([self.own, self.leader, other])
        self.assertIsNone(self.r.sample())
    def test_invalid_vector_is_rejected(self):
        self.p.put(self.scene+0x14, struct.pack('<I', self.vector+400000))
        self.assertIsNone(self.r.sample())
    def test_close_to_leader_stops(self):
        self.assertEqual(follow_directions({'self': (100,100,0), 'leader':(108,105,0)}), (set(),False))
    def test_relocated_module_uses_new_roots_and_types(self):
        delta=0x200000
        self.p.put(LOCAL_ROOT+delta,struct.pack('<I',self.own))
        self.p.put(LOCAL_XYZ+delta,struct.pack('<3f',110,346,0))
        for address,name in ((self.own,'上头影刃'),(self.leader,'上头狂战')):
            self.p.put(address,struct.pack('<I',ROLE_TYPES[name]+delta))
        relocated=DungeonTelemetry(2,self.p,module_base=0x400000+delta)
        self.assertEqual(relocated.sample()['leader'],(559,244,0))
        self.assertIsNone(self.r.sample())
    def change_list_during_sample(self, addresses):
        original=self.p.read
        calls=0
        def read(address,size):
            nonlocal calls
            if address==self.scene+0x10:
                calls+=1
                if calls==2:self.set_list(addresses)
            return original(address,size)
        self.p.read=read
    def test_combat_effects_changing_list_do_not_interrupt_pair(self):
        self.change_list_during_sample([self.own,self.leader,0x600000])
        self.assertIsNotNone(self.r.sample())
    def test_player_removed_during_scan_is_rejected(self):
        self.change_list_during_sample([self.own])
        self.assertIsNone(self.r.sample())
    def test_changed_small_character_uses_configured_name_and_type(self):
        new_type=0x16fb6a4
        self.p.put(self.own,struct.pack('<I',new_type))
        self.p.put(self.own+0x1000,('上头枪\0').encode('utf-16le').ljust(64,b'\0'))
        gunner=DungeonTelemetry(1,self.p,self_name='上头枪',
            role_types={'上头枪':new_type,'上头狂战':ROLE_TYPES['上头狂战']})
        self.assertEqual(gunner.sample()['self_name'],'上头枪')
        self.assertIsNone(self.r.sample())
    def test_same_name_with_wrong_character_type_is_rejected(self):
        self.p.put(self.own+0x1000,('上头枪\0').encode('utf-16le').ljust(64,b'\0'))
        gunner=DungeonTelemetry(1,self.p,self_name='上头枪',
            role_types={'上头枪':0x16fb6a4,'上头狂战':ROLE_TYPES['上头狂战']})
        self.assertIsNone(gunner.sample())
    def test_berserker_can_follow_gunner_without_reversing_axes(self):
        for address,name,vt in ((self.own,'上头狂战',0x16f972c),(self.leader,'上头枪',0x16fb6a4)):
            self.p.put(address,struct.pack('<I',vt))
            self.p.put(address+0x1000,(name+'\0').encode('utf-16le').ljust(64,b'\0'))
        reverse=DungeonTelemetry(1,self.p,self_name='上头狂战',leader_name='上头枪',
            role_types={'上头狂战':0x16f972c,'上头枪':0x16fb6a4})
        sample=reverse.sample()
        self.assertEqual(sample['self_name'],'上头狂战')
        self.assertEqual(sample['leader_name'],'上头枪')
        self.assertEqual(follow_directions(sample),({'right','up'},True))


if __name__ == '__main__': unittest.main()
