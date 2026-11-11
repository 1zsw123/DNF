"""Local character presets and verified, read-only discovery of the active role."""
import copy
import json
import struct
from pathlib import Path
from ctypes import wintypes as W
from follow import Windows, C
from coordinate_connection import connect_verified
from dungeon_farm.planner import FarmPlanner, Skill

ROOT = Path(__file__).resolve().parents[1]
STORE = Path(__file__).with_name('characters.json')
ROTATIONS = ('通用全技能', '狂战士', '刃影冷却优先')
DUMMY = '__unused_solo_leader__'


def base_profile():
    profile = json.loads((ROOT/'coordinate-session.json').read_text(encoding='utf8'))
    own = profile['self_name']
    types = profile['role_types']
    if own not in types: raise ValueError('本机配置缺少角色类型')
    # SoloReader needs one real role; the shared reader requires two distinct
    # names. The unused entry is never searched for by the solo sample path.
    if set(types) != {own, profile.get('leader_name')}:
        profile.update(leader_name=DUMMY, role_types={own:types[own], DUMMY:types[own]})
    return profile


def initial_character(profile):
    name = profile['self_name']
    return {'name':name, 'role_type':profile['role_types'][name],
            'rotation':'狂战士' if name=='上头狂战' else '通用全技能',
            'auto_potion':name=='上头狂战'}


def load_characters():
    try:
        entries = json.loads(STORE.read_text(encoding='utf8'))
    except FileNotFoundError:
        entries = [initial_character(base_profile())]
    if not isinstance(entries,list): raise ValueError('角色配置格式错误')
    for entry in entries: validate_character(entry)
    return entries


def validate_character(entry):
    if not isinstance(entry.get('name'),str) or not entry['name'].strip() or entry['name']==DUMMY:
        raise ValueError('角色名无效')
    value=entry.get('role_type')
    if not isinstance(value,int) or not 0x400000<=value<0x4000000:
        raise ValueError('请用“读取当前角色”取得角色类型')
    if entry.get('rotation') not in ROTATIONS: raise ValueError('技能方案无效')
    if entry.get('potion_key','3') not in ('1','3'): raise ValueError('血药键须为 1 或 3')


def save_characters(entries):
    for entry in entries: validate_character(entry)
    pending=STORE.with_suffix('.new.json')
    pending.write_text(json.dumps(entries,ensure_ascii=False,indent=2),encoding='utf8')
    pending.replace(STORE)


def selected_profile(character=None):
    profile=base_profile()
    if character is not None:
        validate_character(character)
        own=character['name']; vt=character['role_type']
        profile.update(self_name=own,leader_name=DUMMY,role_types={own:vt,DUMMY:vt})
    return profile


def discover_current():
    win=Windows(); hwnd=win.game()
    if not hwnd: raise ValueError('请先打开游戏并登录角色')
    win.u.GetWindowThreadProcessId.argtypes=[W.HWND,C.POINTER(W.DWORD)]
    pid=W.DWORD();win.u.GetWindowThreadProcessId(hwnd,C.byref(pid))
    reader=connect_verified(pid.value,base_profile())
    try:
        address=reader.uint(reader.local_root)
        raw=reader.process.read(address,0x25c) if address else None
        if not raw: raise ValueError('角色尚未加载，请进城镇后再读取')
        vt,kind,ptr=(struct.unpack_from('<I',raw,off)[0] for off in (0,0x90,0x258))
        namebytes=reader.process.read(ptr,96) if ptr else None
        name=namebytes.decode('utf-16le').split('\0',1)[0] if namebytes else ''
        if kind!=273 or not 1<=len(name)<=24 or not all(c.isprintable() for c in name):
            raise ValueError('当前对象不是有效玩家角色')
        if reader.uint(reader.local_root)!=address or reader.uint(address)!=vt or reader.uint(address+0x258)!=ptr:
            raise ValueError('角色正在切换，请稍后读取')
        result={'name':name,'role_type':vt-reader.delta,'rotation':'通用全技能','auto_potion':False}
        validate_character(result)
        return result
    finally: reader.close()


def character_planner(character=None, dual_blades_active=True):
    if character and character['rotation']=='刃影冷却优先':
        from dungeon_farm.blade_rotation import make_planner
        return make_planner(entry_helper=character.get('entry_helper',False))
    if character is None or character['rotation']=='狂战士':
        from dungeon_farm.berserker_rotation import make_planner
        return make_planner(dual_blades_active)
    # Generic scheduling is deliberately independent of berserker H/Y logic.
    # Per-key cooldowns are estimates; all twelve slots are user-authorized.
    intervals={'q':8,'w':15,'e':20,'r':35,'t':45,'y':90,
               'a':5,'s':8,'d':12,'f':15,'g':20,'h':25}
    skills=[Skill(k,intervals[k],.65,180,25,2,'attack') for k in 'ytr ewq hgf dsa'.replace(' ','')]
    return FarmPlanner(skills,allow_all_skills=True)
