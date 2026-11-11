"""Local party coordinates and pure decisions; never write game memory."""
import math
import struct
from dungeon_farm.combat_telemetry import SoloReader
from coordinate_connection import connect_verified
from dungeon_farm.planner import Decision


def read_partner(reader, scene, name):
    """Resolve an explicitly configured player by kind, full name and membership.

    A new profession need not reuse another character's hardcoded vtable.
    Only read fields already verified for kind 273 in this client build.
    """
    matches=[]
    def actor(address):
        raw=reader.process.read(address,0x25c)
        if not raw:return None
        vt,kind,owner=(struct.unpack_from('<I',raw,o)[0] for o in (0,0x90,0xb8))
        if kind!=273 or owner!=scene or not 0x400000<=vt-reader.delta<0x4000000:return None
        ptr=struct.unpack_from('<I',raw,0x258)[0]
        value=reader.process.read(ptr,64) if ptr else None
        if not value or value.decode('utf-16le',errors='replace').split('\0',1)[0]!=name:return None
        xyz=struct.unpack_from('<3f',raw,0x18c)
        if not all(math.isfinite(v) and abs(v)<100000 for v in xyz) or xyz==(0.,0.,0.):return None
        return {'name':name,'base':address,'type':vt-reader.delta,'xyz':xyz}
    for address in set(reader.object_addresses(scene) or ()):
        value=actor(address)
        if value:matches.append(value)
    if len(matches)!=1:return None
    value=matches[0]
    if value['base'] not in (reader.object_addresses(scene) or ()):return None
    latest=actor(value['base'])
    return latest if latest and latest['type']==value['type'] else None


class PartyReader(SoloReader):
    def __init__(self,reader,partner):
        super().__init__(reader);self.partner=partner
    def sample(self):
        result=super().sample()
        if result is None:return None
        result['party']=read_partner(self.reader,result['scene'],self.partner)
        if self.uint(self.local_root)!=result['self_base'] or self.uint(result['self_base']+0xb8)!=result['scene']:
            return None
        return result


def connect_party(pid,profile):
    return PartyReader(connect_verified(pid,profile),profile['party_name'])


def gate_ready(own,partner,door,linked=True):
    """Approach the door, then wait for a fresh partner before pushing through."""
    if not linked or not partner:return False
    target=(door['x'],door['y'])
    return math.dist(own[:2],target)>170 or (
        abs(partner['xyz'][0]-own[0])<100 and abs(partner['xyz'][1]-own[1])<65)


def close_to_partner(own,partner):
    return abs(own[0]-partner['xyz'][0])<=12 and abs(own[1]-partner['xyz'][1])<=8


def follower_decision(own,partner,linked):
    if not linked or not partner:return Decision('waiting_partner')
    if close_to_partner(own,partner):return Decision('following_close')
    return Decision('following',destination=tuple(partner['xyz'][:2]))
