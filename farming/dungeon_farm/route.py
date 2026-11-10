"""Infer only an unambiguous onward exit from verified room objects."""
import math
import struct

OPPOSITE={'left':'right','right':'left','up':'down','down':'up'}

def configured_door(doors, entry_direction, rules):
    """Apply only a route with the same entry and verified door geometry."""
    for rule in rules:
        expected=rule['doors']
        entries=rule['entry'] if isinstance(rule['entry'],list) else [rule['entry']]
        if entry_direction not in entries or len(doors)!=len(expected):continue
        if all(sum(d['direction']==direction and math.hypot(d['x']-xy[0],d['y']-xy[1])<=8
                   for d in doors)==1 for direction,xy in expected.items()):
            return next((d for d in doors if d['direction']==rule['exit']),None)
    return None

def onward_door(doors, entry_direction):
    if entry_direction is None and len(doors)==1:
        return doors[0]
    if len(doors)!=2 or sum(d['direction']==entry_direction for d in doors)!=1:
        return None
    return next(d for d in doors if d['direction']!=entry_direction)

def infer_entry(doors, position):
    if len(doors)<2: return None
    nearest=min(doors,key=lambda d:math.hypot(d['x']-position[0],d['y']-position[1]))
    if math.hypot(nearest['x']-position[0],nearest['y']-position[1])<=260:
        return nearest['direction']
    return None

def read_doors(reader, scene):
    result=[]
    for address in reader.object_addresses(scene) or ():
        raw=reader.process.read(address,0x25c)
        if not raw or struct.unpack_from('<I',raw)[0]-reader.delta!=0x015E1BEC:
            continue
        if struct.unpack_from('<I',raw,0xb8)[0]!=scene: continue
        nameptr=struct.unpack_from('<I',raw,0x258)[0]
        namebytes=reader.process.read(nameptr,96) if nameptr else None
        if not namebytes: continue
        name=namebytes.decode('utf-16le',errors='replace').split('\0',1)[0]
        pursuit={'追擊殲滅戰左邊墻':'left','追擊殲滅戰右邊墻':'right'}
        if '門' not in name and name not in pursuit: continue
        direction=pursuit.get(name) or next((d for token,d in [('左側','left'),('左邊','left'),('右側','right'),('右邊','right'),('上側','up'),('上邊','up'),('下側','down'),('下邊','down')] if token in name),None)
        x,y,z=struct.unpack_from('<3f',raw,0x18c)
        if direction and (x!=0 or y!=0) and all(math.isfinite(v) and abs(v)<100000 for v in (x,y,z)):
            result.append({'direction':direction,'x':x,'y':y})
    return result
