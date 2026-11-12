"""Wind hotbar read from 不打团's client on 2026-11-12.

CD, MP and cube costs are panel values; animation locks/ranges are estimates.
"""
from dungeon_farm.planner import FarmPlanner, Skill

VERIFIED = (
    ('a','游离之风',6.3,117,0,.35),
    ('s','风鸣冲击',7.7,216,0,.55),
    ('d','朔风牵引',9,162,0,.65),
    ('f','双翼风刃',9,294,0,.55),
    ('g','刃风',10.8,570,0,.8),
    ('h','旋风瞬影闪',18,109,1,.8),
    ('q','风暴之眼',18,208,0,.75),
    ('w','真空旋风破',22.5,297,1,1.1),
    ('e','风卷残云',36,740,2,1.2),
    ('r','游龙惊风破',36,740,2,1.2),
    ('t','风暴之拳',40.5,818,2,1.2),
    ('y','万象风龙阵',76.5,1474,5,3.2),
)

def make_planner(entry_helper=False):
    skills=[Skill(k,cd,lock,180,25,cubes,name=name,mp_cost=mp)
            for k,name,cd,mp,cubes,lock in VERIFIED]
    skills.append(Skill('wind_buff',7.7,.5,0,0,0,'entry_buff',
                        name='流风诀',mp_cost=1108,
                        input_sequence=('right','down','right','z')))
    if entry_helper:
        skills.append(Skill('4',0,.6,0,0,0,'entry_helper',name='召唤帮手'))
    return FarmPlanner(skills,allow_all_skills=True)
