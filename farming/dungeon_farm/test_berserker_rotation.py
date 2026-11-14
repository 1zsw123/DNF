import unittest
from dataclasses import replace
from dungeon_farm.berserker_rotation import make_planner
from dungeon_farm.planner import Observation,Enemy,attack_still_valid,Decision

class RotationTests(unittest.TestCase):
    def simulate(self,active,spam=True,seconds=160,enemy=(150,200)):
        p=make_planner(active,spam=spam)
        obs=Observation(0,scene='room',position=(100,200),facing='right',enemies=(Enemy('enemy',*enemy),),perception_valid=True)
        sent=[]
        for i in range(int(seconds*10)):
            now=i*.1;d=p.step(replace(obs,timestamp=now),now)
            if d.tap:
                sent.append((now,d.tap,d.action));p.acknowledge(d,now,True)
        return sent

    # Conservative cooldown-estimate scheduling (spam=False) is unchanged.
    def test_conservative_mode_uses_all_hotbar_keys_and_toggle_is_not_spammed(self):
        sent=self.simulate(False,spam=False)
        self.assertEqual(set(k for _,k,_ in sent),set('qwertyasdfghx'))
        self.assertEqual(sum(k=='h' for _,k,_ in sent),1)
    def test_conservative_mode_waits_for_estimated_cooldowns(self):
        r=[t for t,k,_ in self.simulate(True,spam=False,seconds=60) if k=='r']
        self.assertTrue(all(b-a>=45 for a,b in zip(r,r[1:])))

    # Default berserker scheme: skills are spammed regardless of cooldown.
    def test_spam_mode_is_the_default(self):
        self.assertTrue(make_planner().spam)
    def test_spam_uses_every_attack_skill_repeatedly_ignoring_cooldowns(self):
        sent=self.simulate(True,seconds=20)
        counts={k:sum(key==k for _,key,_ in sent) for k in 'qwertasd'}
        # r/t/e have 40-50 s estimates; spam presses them several times in 20 s.
        self.assertTrue(all(n>=3 for n in counts.values()),counts)
    def test_spam_rotates_least_recently_used_key(self):
        attacks=[k for _,k,a in self.simulate(True,seconds=20) if k in 'qwertasd' and a is None]
        first=attacks[:8]
        self.assertEqual(len(set(first)),8,first)
        self.assertEqual(attacks[8:16],first)
    def test_spam_does_not_stand_idle_for_long_animation_estimates(self):
        sent=self.simulate(True,seconds=20)
        # Only the awakening keeps its longer animation lock.
        gaps=[b[0]-a[0] for a,b in zip(sent,sent[1:]) if a[1]!='y']
        self.assertLessEqual(max(gaps),.6)
    def test_spam_never_switches_dual_blades_off(self):
        self.assertFalse(any(k=='h' for _,k,_ in self.simulate(True)))
        self.assertEqual(sum(k=='h' for _,k,_ in self.simulate(False)),1)
    def test_spam_repeats_buffs_every_few_seconds(self):
        sent=self.simulate(True)
        for key in 'fg':
            times=[t for t,k,_ in sent if k==key]
            self.assertGreaterEqual(len(times),15)
            gaps=[b-a for a,b in zip(times,times[1:])]
            self.assertTrue(all(8<=g<=9 for g in gaps),gaps)
    def test_awakening_keeps_press_wait_release_rhythm(self):
        for spam,again in ((True,20),(False,130)):
            awaken=[(t,action) for t,key,action in self.simulate(True,spam=spam) if key=='y']
            self.assertEqual(awaken[1][1],'release')
            self.assertGreaterEqual(awaken[1][0]-awaken[0][0],12)
            self.assertIsNone(awaken[2][1])
            self.assertGreaterEqual(awaken[2][0]-awaken[0][0],again)
            if spam:self.assertLess(awaken[2][0]-awaken[0][0],again+3)
    def test_spam_weaves_two_basic_attacks_between_skills_in_reach(self):
        sent=[k for _,k,a in self.simulate(True,seconds=20) if a is None and k!='y']
        skills=[i for i,k in enumerate(sent) if k in 'qwertasd']
        for a,b in zip(skills,skills[1:]):
            self.assertEqual(sent[a+1:b],['x','x'])
    def test_spam_skips_basic_attacks_when_target_only_in_skill_reach(self):
        sent=self.simulate(True,seconds=20,enemy=(220,200))  # 120 away: past X reach
        self.assertFalse(any(k=='x' for _,k,_ in sent))
        self.assertGreater(sum(k in 'qwertsd' for _,k,_ in sent),15)
    def test_spam_attacks_enemy_slightly_off_lane_instead_of_realigning(self):
        p=make_planner(True)
        obs=Observation(0,scene='room',position=(100,200),facing='right',enemies=(Enemy('enemy',150,225),),perception_valid=True)
        p.step(obs,0)
        d=p.step(replace(obs,timestamp=1),1)
        self.assertIsNotNone(d.tap)
        self.assertFalse(d.move)
        skill=next(s for s in p.skills if s.key==d.tap)
        moved=replace(obs,timestamp=1.05)
        self.assertTrue(attack_still_valid(d,moved,'room',skill,p.attack_range,p.spam_lane))
    def test_spam_still_approaches_distant_enemy(self):
        p=make_planner(True)
        obs=Observation(0,scene='room',position=(100,200),facing='right',enemies=(Enemy('enemy',600,200),),perception_valid=True)
        p.step(obs,0)
        t=1
        d=p.step(replace(obs,timestamp=t),t)
        while d.action=='buff':  # F/G buffs go up first, as before
            p.acknowledge(d,t,True);t+=1
            d=p.step(replace(obs,timestamp=t),t)
        self.assertEqual(d.state,'approach')
        self.assertIsNone(d.tap)

if __name__=='__main__':unittest.main()


class DefaultStartTests(unittest.TestCase):
    def test_default_start_opens_dual_blades_once_then_buffs(self):
        p=make_planner()
        obs=Observation(0,scene='room',position=(100,200),facing='right',enemies=(Enemy('enemy',150,200),),perception_valid=True)
        sent=[]
        for i in range(1600):
            now=i*.1;d=p.step(replace(obs,timestamp=now),now)
            if d.tap:sent.append(d.tap);p.acknowledge(d,now,True)
        self.assertEqual(set(sent[:3]),{'h','f','g'})
        self.assertEqual(sent.count('h'),1)

    def test_dual_blades_wait_for_room_to_settle(self):
        p=make_planner()
        obs=Observation(0,scene='room',position=(100,200),facing='right',enemies=(Enemy('enemy',150,200),),perception_valid=True)
        times=[]
        for i in range(80):
            now=i*.05;d=p.step(replace(obs,timestamp=now),now)
            if d.tap:
                if d.tap=='h':times.append(now)
                p.acknowledge(d,now,True)
        self.assertEqual(len(times),1)
        self.assertGreaterEqual(times[0],1.0)
        # A new room does not re-press an already opened toggle.
        for i in range(40):
            now=5+i*.05;d=p.step(replace(obs,timestamp=now,scene='room2'),now)
            if d.tap:
                self.assertNotEqual(d.tap,'h');p.acknowledge(d,now,True)

    def test_blind_step_keeps_attacking_in_place(self):
        p=make_planner(True)
        keys=[]
        for i in range(100):
            now=i*.05;d=p.blind_step(now)
            if d:
                self.assertEqual(d.state,'blind');self.assertFalse(d.move)
                keys.append(d.tap);p.acknowledge(d,now,True)
        self.assertTrue(set('qwertasd')<=set(keys),keys)
        self.assertIn('x',keys)
        self.assertNotIn('h',keys)

    def test_blind_step_respects_cast_lock_and_releases_awakening(self):
        p=make_planner(True)
        p.casting_until=1
        self.assertIsNone(p.blind_step(.5))
        p.releases['y']=2
        d=p.blind_step(2.1)
        self.assertEqual((d.tap,d.action),('y','release'))
        p.acknowledge(d,2.1,True)
        self.assertNotIn('y',p.releases)
