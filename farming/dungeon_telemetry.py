"""Read-only positions from the current dungeon's live object list.

Offsets verified for the locally installed client only. Callers verify its build
and discover its module base before connecting to each new process.
"""
import math
import struct
import time
from memory_access import ReadOnlyProcess

LOCAL_ROOT = 0x01AB7CDC
LOCAL_XYZ = 0x01A60324
ROLE_TYPES = {'上头影刃': 0x016FC11C, '上头狂战': 0x016F972C}


class DungeonTelemetry:
    def __init__(self, pid, process=None, module_base=0x400000,
                 self_name='上头影刃', leader_name='上头狂战', role_types=None):
        types = ROLE_TYPES if role_types is None else role_types
        if self_name == leader_name or set(types) != {self_name, leader_name}:
            raise ValueError('角色配置必须包含不同的小号和大号')
        if not all(isinstance(v, int) and 0x400000 <= v < 0x4000000 for v in types.values()):
            raise ValueError('角色类型配置无效')
        self.self_name, self.leader_name = self_name, leader_name
        self.pid = pid
        self.process = process if process is not None else ReadOnlyProcess(pid)
        self.delta = module_base - 0x400000
        self.local_root = LOCAL_ROOT + self.delta
        self.local_xyz = LOCAL_XYZ + self.delta
        self.role_types = {name: value + self.delta for name, value in types.items()}

    def uint(self, address):
        raw = self.process.read(address, 4)
        return struct.unpack('<I', raw)[0] if raw else 0

    def actor(self, base, scene):
        raw = self.process.read(base, 0x25c) if base else None
        if not raw:
            return None
        vt = struct.unpack_from('<I', raw)[0]
        if vt not in self.role_types.values() or struct.unpack_from('<I', raw, 0xb8)[0] != scene:
            return None
        nameptr = struct.unpack_from('<I', raw, 0x258)[0]
        namebytes = self.process.read(nameptr, 64) if nameptr else None
        if not namebytes:
            return None
        name = namebytes.decode('utf-16le', errors='replace').split('\0', 1)[0]
        if self.role_types.get(name) != vt:
            return None
        xyz = struct.unpack_from('<3f', raw, 0x18c)
        if not all(math.isfinite(v) and abs(v) < 100000 for v in xyz):
            return None
        return {'name': name, 'base': base, 'xyz': xyz}

    def object_addresses(self, scene):
        header = self.process.read(scene + 0x10, 12)
        if not header:
            return None
        begin, end, capacity = struct.unpack('<3I', header)
        if not (0x10000 < begin <= end <= capacity) or (end - begin) % 4 or not 0 < end - begin <= 32768:
            return None
        raw = self.process.read(begin, end - begin)
        if not raw:
            return None
        return struct.unpack('<' + 'I' * (len(raw) // 4), raw)

    def sample(self):
        started = time.monotonic()
        local = self.uint(self.local_root)
        scene = self.uint(local + 0xb8) if local else 0
        own = self.actor(local, scene) if scene else None
        if not own or own['name'] != self.self_name:
            return None
        addresses = self.object_addresses(scene)
        if not addresses:
            return None
        if local not in addresses:
            return None
        roles = {}
        for address in set(addresses):
            actor = own if address == local else self.actor(address, scene)
            if actor:
                if actor['name'] in roles:
                    return None  # Ambiguous identities must not drive the follower.
                roles[actor['name']] = actor
        if set(roles) != set(self.role_types):
            return None
        # Combat effects add/remove unrelated objects every frame. Revalidate
        # membership of this pair in a fresh list instead of requiring the list
        # length and allocation to stay frozen throughout the entire scan.
        current_addresses = self.object_addresses(scene)
        leader_base = roles[self.leader_name]['base']
        if not current_addresses or local not in current_addresses or leader_base not in current_addresses:
            return None
        own = self.actor(local, scene)
        leader = self.actor(leader_base, scene)
        if not own or own['name'] != self.self_name or not leader or leader['name'] != self.leader_name:
            return None
        mirror = self.process.xyz(self.local_xyz)
        if not mirror or any(not math.isfinite(b) or abs(a - b) > 8 for a, b in zip(own['xyz'], mirror)):
            return None  # Town leftovers and transition snapshots fail this check.
        if self.uint(self.local_root) != local or self.uint(local + 0xb8) != scene:
            return None
        if time.monotonic() - started > .08:
            return None
        return {'self': own['xyz'], 'leader': leader['xyz'],
                'self_name': self.self_name, 'leader_name': self.leader_name,
                'self_base': local, 'leader_base': leader_base,
                'scene': scene, 'pid': self.pid, 'time': time.monotonic()}

    def close(self):
        self.process.close()


def follow_directions(sample):
    """World coordinates: close enough to join the leader at a room doorway."""
    dx = sample['leader'][0] - sample['self'][0]
    dy = sample['leader'][1] - sample['self'][1]
    keys = set()
    if abs(dx) > 12:
        keys.add('right' if dx > 0 else 'left')
    if abs(dy) > 8:
        keys.add('down' if dy > 0 else 'up')
    return keys, abs(dx) > 160
