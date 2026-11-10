"""Reconnect read-only telemetry after a game restart, verifying the client build."""
import hashlib
import os
import struct
import time
from memory_access import ReadOnlyProcess
from dungeon_telemetry import DungeonTelemetry


def file_sha256(path):
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def connect_verified(pid, profile):
    process = ReadOnlyProcess(pid)
    try:
        path = process.image_path()
        if os.path.normcase(os.path.abspath(path)) != os.path.normcase(os.path.abspath(profile['client_path'])):
            raise ValueError('客户端路径与已验证版本不同')
        if file_sha256(path) != profile['client_sha256']:
            raise ValueError('客户端已更新，坐标结构需要重新验证')
        base = process.image_base(path)
        header = process.read(base, 64)
        if not header or header[:2] != b'MZ':
            raise ValueError('客户端加载尚未完成')
        pe = process.read(base + struct.unpack_from('<I', header, 0x3c)[0], 26)
        if not pe or pe[:4] != b'PE\0\0' or struct.unpack_from('<H', pe, 4)[0] != 0x14c or struct.unpack_from('<H', pe, 24)[0] != 0x10b:
            raise ValueError('客户端模块格式不匹配')
        return DungeonTelemetry(pid, process=process, module_base=base,
                                self_name=profile.get('self_name','上头影刃'),
                                leader_name=profile.get('leader_name','上头狂战'),
                                role_types=profile.get('role_types'))
    except BaseException:
        process.close()
        raise


class CoordinateConnection:
    def __init__(self, profile, connector=connect_verified, clock=time.monotonic):
        self.profile = profile
        self.connector = connector
        self.clock = clock
        self.reader = None
        self.target_pid = None
        self.retry_at = 0
        self.status = '等待游戏进程'
        self.generation = 0

    def close(self):
        if self.reader is not None:
            self.reader.close()
            self.reader = None

    def sample(self, pid):
        now = self.clock()
        if pid != self.target_pid:
            self.close()
            self.target_pid = pid
            self.retry_at = 0
        if self.reader is not None and not self.reader.process.alive():
            self.close()
            self.retry_at = 0
        if not pid or not self.profile.get('enabled'):
            self.status = '等待游戏进程' if not pid else '坐标模式已关闭'
            return None
        if self.reader is None:
            if now < self.retry_at:
                return None
            self.retry_at = now + 3
            try:
                self.reader = self.connector(pid, self.profile)
                self.generation += 1
            except (OSError, ValueError, KeyError) as exc:
                self.status = '坐标连接等待：' + str(exc)
                return None
        try:
            result = self.reader.sample()
        except (OSError, ValueError):
            self.close()
            self.status = '坐标读取中断，等待重新连接'
            self.retry_at = now + 1
            return None
        self.status = '坐标已连接' if result else '已连接客户端，等待有效副本角色'
        if result:
            result['connection_generation'] = self.generation
        return result
