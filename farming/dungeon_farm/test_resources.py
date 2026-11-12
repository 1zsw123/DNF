import unittest
import numpy as np
from dungeon_farm.resources import orb_fill,need_recovery,RecoveryBudget

class ResourceTests(unittest.TestCase):
    def test_one_potion_budget_even_if_health_stays_low(self):
        budget=RecoveryBudget()
        low={'hp_fill':.2,'mp_fill':.8}
        self.assertTrue(budget.available(low,.1))
        budget.sent()
        self.assertFalse(budget.available(low,.1))
        self.assertFalse(budget.available({'hp_fill':0,'mp_fill':.8},.1))
        self.assertTrue(RecoveryBudget().available(low,.1))
    def frame(self,hp,mp):
        frame=np.zeros((480,640,3),dtype=np.uint8)
        frame[460-round(hp*40):460,22:38,2]=150
        frame[460-round(mp*40):460,602:618,0]=150
        return frame
    def test_full_orbs_do_not_consume_item(self):
        self.assertFalse(need_recovery(orb_fill(self.frame(1,1)),.2))
    def test_only_health_below_fifty_percent_requests_recovery(self):
        for hp in (.275,.4,.475):
            self.assertTrue(need_recovery(orb_fill(self.frame(hp,1)),.2))
        for hp,mp in ((.5,1),(.6,.1),(1,.1)):
            self.assertFalse(need_recovery(orb_fill(self.frame(hp,mp)),.2))
    def test_stale_resource_read_is_not_used(self):
        self.assertFalse(need_recovery(orb_fill(self.frame(.2,.1)),3))
    def test_black_loading_frame_never_requests_recovery(self):
        self.assertFalse(need_recovery(orb_fill(self.frame(0,0)),.2))
