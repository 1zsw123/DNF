"""Blade hotbar values read from this client's learned-skill panel.

Cooldown/MP/cube costs are observed values. Animation locks and ranges remain
controller estimates; sending input alone does not prove the server cast it.
"""
from dungeon_farm.planner import FarmPlanner,Skill

# key, name, cooldown seconds, MP, cubes, animation lock estimate
VERIFIED=(
    ('a','鬼缚钉',7,75,0,.35),
    ('s','利刃旋风',6,147,0,.55),
    ('d','白牙落斩',10,184,0,.75),
    ('f','薄暮利刃',10,845,0,.55),
    ('g','黑夜之花',15,936,0,.8),
    ('h','回旋十字斩',18,1123,1,1.1),
    ('q','夜之风',20,765,1,.75),
    ('w','瞬影碎魂击',25,370,1,1.1),
    ('e','秘术·心斩',40,860,2,.8),
    ('r','秘术·曜夜斩',40,580,3,1.2),
    ('t','追命索魂丝',50,798,2,1.4),
    ('y','决裁之狱',145,1753,5,3.2),
)

def make_planner(entry_helper=False):
    skills=[Skill(k,cd,lock,180,25,cubes,name=name,mp_cost=mp) for k,name,cd,mp,cubes,lock in VERIFIED]
    skills.append(Skill('tracking_buff',5,.5,0,0,0,'entry_buff',name='追踪术',mp_cost=528,
                        input_sequence=('right','right','space')))
    if entry_helper:skills.append(Skill('4',0,.6,0,0,0,'entry_helper',name='召唤帮手'))
    return FarmPlanner(skills,allow_all_skills=True)
