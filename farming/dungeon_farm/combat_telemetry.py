"""Read-only, build-verified Lava Cave combat candidates.

Enemy identity is restricted to the monster types inspected in this client.
Absence of candidates does NOT assert room clear or authorize an exit.
"""
import math
import struct
import time
from dungeon_farm.planner import Enemy, Observation
from coordinate_connection import connect_verified

FIRST_ROOM_TYPES = {0x017930C4, 0x0179398C, 0x01794B1C, 0x016FFDD4, 0x0175927C, 0x0174E2D4, 0x0172EF2C,
                    0x0170069C, 0x0175A3EC, 0x0174EBA4, 0x0175ACA4}

# Read-only identities and owner link observed together with this character's
# G2/G3 transformations. Other players' robots never satisfy the prerequisite.
G_OBJECTS={0x1637074:'G-3 捕食者',0x163753c:'G-3 捕食者',
           0x16366e4:'G-2 旋雷者',0x1636bac:'G-2 旋雷者'}

def own_g_object(reader,address,raw,delta,self_base):
    vt,kind=(struct.unpack_from('<I',raw,off)[0] for off in (0,0x90))
    expected=G_OBJECTS.get(vt-delta)
    if kind!=33 or expected is None:return False
    if reader.uint(address+0x6d8)!=self_base:return False
    ptr=struct.unpack_from('<I',raw,0x258)[0]
    namebytes=reader.process.read(ptr,64) if ptr else None
    name=namebytes.decode('utf-16le',errors='replace').split('\0',1)[0] if namebytes else ''
    return name==expected
# Verified in this run: ghouls, throwers, zombies, lava ghouls, Goliath,
# fire spirits, Burning Hera, Atlas and Oil Barrel Olick.


class SoloReader:
    """Keep build verification and own-actor checks without requiring a party."""
    def __init__(self, reader):
        self.reader = reader

    def __getattr__(self, name):
        return getattr(self.reader, name)

    def sample(self):
        started = time.monotonic()
        r = self.reader
        base = r.uint(r.local_root)
        scene = r.uint(base+0xb8) if base else 0
        own = r.actor(base,scene) if scene else None
        if not own or own['name'] != r.self_name:
            return None
        members = r.object_addresses(scene)
        if not members or base not in members:
            return None
        own = r.actor(base,scene)
        mirror = r.process.xyz(r.local_xyz)
        if not own or own['name'] != r.self_name or not mirror:
            return None
        if any(not math.isfinite(b) or abs(a-b)>8 for a,b in zip(own['xyz'],mirror)):
            return None
        current_members = r.object_addresses(scene)
        if not current_members or base not in current_members:
            return None
        if r.uint(r.local_root)!=base or r.uint(base+0xb8)!=scene or time.monotonic()-started>.08:
            return None
        return {'self':own['xyz'],'self_name':r.self_name,'self_base':base,
                'scene':scene,'pid':r.pid,'time':time.monotonic(),'solo':True}


def connect_solo(pid, profile):
    return SoloReader(connect_verified(pid, profile))


def observe(connection, pid, facing=None, allowed_types=None, allowed_apcs=None, friendly_apcs=None, friendly_monsters=None, ignore_unknown=False, generic_monsters=False):
    sample = connection.sample(pid)
    if not sample:
        return None
    reader = connection.reader
    scene = sample['scene']
    addresses = reader.object_addresses(scene)
    if not addresses:
        return None
    enemies = []; unknown = set(); unknown_details=[];friendly_names=[];g_confirmed=False
    for address in set(addresses):
        raw = reader.process.read(address, 0x25c)
        if not raw:
            return None
        vt, kind, obj_scene = (struct.unpack_from('<I', raw, offset)[0] for offset in (0,0x90,0xb8))
        if obj_scene==scene and kind==33 and not g_confirmed:
            g_confirmed=own_g_object(reader,address,raw,reader.delta,sample['self_base'])
        if kind not in (529,273) or obj_scene != scene or address==sample['self_base']:
            continue
        if kind==273 and sample.get('party') and address==sample['party']['base']:
            continue
        name=''
        if kind==273:
            if allowed_apcs is None:continue
            ptr=struct.unpack_from('<I',raw,0x258)[0]
            namebytes=reader.process.read(ptr,96) if ptr else None
            name=namebytes.decode('utf-16le',errors='replace').split('\0',1)[0] if namebytes else ''
            if name in (reader.self_name,reader.leader_name):continue
            if name in (friendly_apcs or {}).get(vt-reader.delta,()):
                friendly_names.append(name);continue
            recognized=name in allowed_apcs.get(vt-reader.delta,())
        else:
            if vt-reader.delta in (friendly_monsters or {}):
                ptr=struct.unpack_from('<I',raw,0x258)[0]
                rawname=reader.process.read(ptr,96) if ptr else None
                name=rawname.decode('utf-16le',errors='replace').split('\0',1)[0] if rawname else ''
                if name in friendly_monsters[vt-reader.delta]:continue
            recognized=(generic_monsters and 0x400000<=vt-reader.delta<0x4000000) or vt-reader.delta in (FIRST_ROOM_TYPES if allowed_types is None else allowed_types)
        if not recognized:
            unknown.add(hex(vt-reader.delta))
            ptr=struct.unpack_from('<I',raw,0x258)[0]
            namebytes=reader.process.read(ptr,96) if ptr else None
            name=namebytes.decode('utf-16le',errors='replace').split('\0',1)[0] if namebytes else ''
            unknown_details.append({'type':hex(vt-reader.delta),'address':hex(address),'name':name,'kind':kind,
                                    'xyz':struct.unpack_from('<3f',raw,0x18c)})
            continue
        x,y,z = struct.unpack_from('<3f',raw,0x18c)
        if not all(math.isfinite(v) and abs(v)<100000 for v in (x,y,z)):
            return None
        if x==0 and y==0 and z==0:
            # Object-list membership can precede coordinate initialization.
            # Do not chase the origin and learn false walls while loading.
            return None
        enemies.append(Enemy(hex(address), x, y))
    if reader.uint(reader.local_root) != sample['self_base'] or reader.uint(sample['self_base']+0xb8) != scene:
        return None
    now = time.monotonic()
    if now-sample['time']>.1:
        return None
    sample['unverified_monsters'] = sorted(unknown)
    sample['friendly_apcs']=friendly_names
    sample['unverified_details'] = unknown_details
    sample['g_confirmed']=g_confirmed
    observation = Observation(now, scene=f'{pid}:{scene:x}', position=tuple(sample['self'][:2]),
                              facing=facing, enemies=tuple(enemies), perception_valid=ignore_unknown or not unknown,
                              g_confirmed=g_confirmed)
    return observation, sample
