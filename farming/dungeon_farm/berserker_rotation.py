"""All twelve user-authorized hotbar keys for the berserker.

Default (spam=True), cooldown estimates below are ignored:
- Q/W/E/R/T/A/S/D go in least-recently-pressed order whenever a target is
  roughly in reach, with two basic X attacks woven between skills when the
  target is within X reach.
- F/G buffs are re-pressed about every 8 s.
- Y awakening is retried about every 20 s but keeps press -> wait 12 s ->
  release, so it is not cut short.
- H is a toggle: pressed only while off, because a second press switches it
  off.
A key still on its real cooldown simply does nothing in the client.

spam=False restores the earlier conservative cooldown-estimate scheduling.
"""
from dungeon_farm.planner import FarmPlanner,Skill

def make_planner(dual_blades_active=False,spam=True):
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
    toggles={'h'} if dual_blades_active else ()
    if not spam:
        return FarmPlanner(skills,allow_all_skills=True,toggle_active=toggles)
    # Wider lanes so the character swings instead of endlessly re-aligning.
    return FarmPlanner(skills,allow_all_skills=True,toggle_active=toggles,
                       attack_range=(80,15),spam=True)
