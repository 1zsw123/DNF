"""All twelve user-authorized hotbar keys; conservative scheduling intervals."""
from dungeon_farm.planner import FarmPlanner,Skill

def make_planner(dual_blades_active=True):
    # Intervals are scheduler estimates, not a claim of reading in-game cooldowns.
    skills=[
        Skill('h',99999,.5,0,0,0,'toggle'),
        Skill('f',25,.6,0,0,0,'buff'),Skill('g',120,.8,0,0,0,'buff'),
        Skill('y',130,1.2,210,55,5,'awakening',12),
        Skill('r',45,1.4,200,45,2),Skill('t',50,1.2,160,55,2),
        Skill('w',20,.7,155,18,1),Skill('e',40,2.8,230,25,1),
        Skill('d',15,.8,105,35,1),Skill('s',6,.55,115,20,0),
        Skill('a',3.5,.4,90,10,0),Skill('q',8,.7,180,10,0),
    ]
    return FarmPlanner(skills,allow_all_skills=True,toggle_active={'h'} if dual_blades_active else ())
