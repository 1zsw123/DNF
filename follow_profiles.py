"""Follower-only names and persistence; never alter the farming session."""
import json
from pathlib import Path

def with_names(profile, own, leader):
    own, leader = own.strip(), leader.strip()
    if any(not 1 <= len(n) <= 24 or not all(c.isprintable() for c in n) for n in (own,leader)) or own==leader:
        raise ValueError('请输入不同的完整小号、大号名字（1–24个字符）。')
    return {**profile,'self_name':own,'leader_name':leader,'role_types':{},
            'automatic_role_types':True,'self_yolo_compatible':False,'leader_yolo_compatible':False}

def load_profile(root):
    root=Path(root)
    path=root/'follow-session.json'
    if not path.exists():path=root/'coordinate-session.json'
    if not path.exists():return {}
    value=json.loads(path.read_text(encoding='utf-8'))
    return with_names(value,value.get('self_name',''),value.get('leader_name',''))

def save_profile(root, profile):
    target=Path(root)/'follow-session.json'
    temp=target.with_suffix('.new.json')
    temp.write_text(json.dumps(profile,ensure_ascii=False,indent=2),encoding='utf-8')
    temp.replace(target)
