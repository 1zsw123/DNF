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


def follower_scene_preset(presets,title):
    """Only the current HUD title selects map-specific friendly identities."""
    from dungeon_farm.screen_signals import normalize
    text=normalize(title)
    names=[name for name in presets if normalize(name) in text]
    import copy
    name=names[0] if len(names)==1 else None
    result=copy.deepcopy(presets[name]) if name else {'monster_types':[]}
    # This user-summoned helper is independent of the dungeon. Keep exact
    # type AND name matching; other APCs still require their own map profile.
    friends=result.setdefault('friendly_apcs',{})
    friends['0x16fe0e4']=list(dict.fromkeys([*friends.get('0x16fe0e4',[]),'偉大的杜爾夫']))
    return name,result


def follower_link_ready(remote,partner):
    # remote() already enforces the authenticated heartbeat freshness. The
    # leader's active bit also drops during manual input; fresh local actor
    # coordinates plus a combat phase are sufficient for door rendezvous.
    return bool(remote and remote.get('phase')=='combat' and partner)


def gate_ready(own,partner,door,linked=True):
    """Approach the door, then wait for a fresh partner before pushing through."""
    if not linked or not partner:return False
    target=(door['x'],door['y'])
    return math.dist(own[:2],target)>170 or (
        abs(partner['xyz'][0]-own[0])<100 and abs(partner['xyz'][1]-own[1])<65)


def close_to_partner(own,partner):
    return abs(own[0]-partner['xyz'][0])<=12 and abs(own[1]-partner['xyz'][1])<=8


def follower_reentered(signals,sample,old_scene,remote,round_id):
    """A follower validates its local party and authenticated round, not a map preset."""
    return bool(sample and sample.get('scene') and sample['scene']!=old_scene
                and sample.get('party') and remote and round_id
                and remote.get('active') and remote.get('phase') in ('entering','combat')
                and remote.get('session')==round_id[0]
                and remote.get('round') in (round_id[1],round_id[1]+1)
                and not any(signals.get(k) for k in ('retry','finished','exhausted','dead')))


def follower_decision(own,partner,linked,*,room_clear=False,doors=(),door_approach=None):
    """Wait through combat, then rendezvous only at the leader's current exit.

    Door objects are geometry, not a verified lock-state flag: the caller must
    also supply a continuously observed empty-room confirmation.
    """
    if not linked or not partner:return Decision('waiting_partner')
    if not room_clear:return Decision('waiting_room_clear',reason='原地等待清怪与补刷确认')
    # Only verified exit geometry can define a rendezvous, never a player.
    doors=[d for d in doors if d.get('direction') in ('left','right','up','down')
           and all(isinstance(d.get(k),(int,float)) and math.isfinite(d[k]) for k in ('x','y'))]
    ranked=sorted((math.dist(partner['xyz'][:2],(d['x'],d['y'])),i)
                  for i,d in enumerate(doors))
    if (not ranked or ranked[0][0]>200 or
            (len(ranked)>1 and ranked[1][0]-ranked[0][0]<40)):
        return Decision('waiting_leader_door',reason='房间已清，等待大号到明确的出口旁')
    door=doors[ranked[0][1]];direction=door['direction']
    dx,dy={'left':(-1,0),'right':(1,0),'up':(0,-1),'down':(0,1)}[direction]
    # The leader must be in the exit lane, not merely inside a broad radius.
    lateral=abs(partner['xyz'][1]-door['y']) if dx else abs(partner['xyz'][0]-door['x'])
    if lateral>65:return Decision('waiting_leader_door',reason='大号尚未对齐已确认出口')
    from dungeon_farm.door_approach import DoorApproach
    approach=door_approach if door_approach is not None else DoorApproach()
    identity=(direction,round(door['x']),round(door['y']))
    if approach.identity is not None and approach.identity!=identity:
        approach.escape.clear();approach.escaped.clear()
        approach.identity=None;approach.aligned=False
    target=approach.target(door,own,doors)
    # The inside waypoint is only alignment, never proof of a transition.
    # Keep the controller alive until runtime observes a different scene.
    return Decision('following_entering' if approach.aligned else 'following',destination=target,
                    reason='已对齐出口，继续跨过触发线' if approach.aligned else '前往已确认出口，先对齐门内侧')
