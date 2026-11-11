import unittest
import struct
from dungeon_farm.route import onward_door,read_doors

class DoorReader:
    delta=0
    def __init__(self,x,y):
        self.process=self
        self.raw=bytearray(0x25c)
        struct.pack_into('<I',self.raw,0,0x015E1BEC)
        struct.pack_into('<I',self.raw,0xb8,77)
        struct.pack_into('<3f',self.raw,0x18c,x,y,0)
        struct.pack_into('<I',self.raw,0x258,2)
    def object_addresses(self,scene):return [1]
    def read(self,address,size):
        return self.raw if address==1 else '淺栖之地的下側領主門\0'.encode('utf-16le')

class RouteTests(unittest.TestCase):
    def test_arden_north_assets_and_south_exit_stay_distinct(self):
        for x,y in ((226,100),(273,101)):
            self.assertEqual(read_doors(DoorReader(x,y),77,'阿登高地')[0]['direction'],'up')
        self.assertEqual(read_doors(DoorReader(762,490),77,'阿登高地')[0]['direction'],'down')
        self.assertEqual(read_doors(DoorReader(273,101),77,'根特东门')[0]['direction'],'down')
        self.assertEqual(read_doors(DoorReader(1311,1536),77,'阿登高地'),[])
    def test_only_forward_exit(self):
        a={'direction':'up'}; b={'direction':'down'}
        self.assertEqual(onward_door([a,b],'up'),b)
    def test_branch_does_not_guess(self):
        self.assertIsNone(onward_door([{'direction':d} for d in ('up','left','down')],'up'))
    def test_dead_end_does_not_backtrack(self):
        self.assertIsNone(onward_door([{'direction':'up'}],'up'))
    def test_unknown_entry_stops(self):
        self.assertIsNone(onward_door([{'direction':d} for d in ('up','down')],'left'))
