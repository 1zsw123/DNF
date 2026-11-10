import threading,unittest
import cv2,numpy as np
from follow import Tracker
from name_rescue import NameRescue


class RescueTests(unittest.TestCase):
    def setUp(self):
        self.rescue=NameRescue.__new__(NameRescue)
        self.rescue.lock=threading.Lock();self.rescue.epoch=0
        patch=np.zeros((20,100,3),np.uint8)
        cv2.putText(patch,'ROLE 37',(2,16),0,.55,(255,255,255),1)
        self.patch=patch
        self.rescue.templates={'self':(Tracker(patch,(0,120)),10)}

    def test_requires_current_name_pixels_and_follows_their_new_position(self):
        frame=np.zeros((614,819,3),np.uint8)
        self.assertEqual(self.rescue.locate(frame,11,{'self'}),{})
        frame[220:240,500:600]=self.patch
        found=self.rescue.locate(frame,11,{'self'})['self']['foot']
        self.assertAlmostEqual(found[0],550)
        self.assertAlmostEqual(found[1],350)

    def test_expiration_and_reset_prevent_old_scene_matches(self):
        frame=np.zeros((614,819,3),np.uint8);frame[220:240,500:600]=self.patch
        self.assertEqual(self.rescue.locate(frame,26,{'self'}),{})
        self.rescue.reset()
        self.assertEqual(self.rescue.epoch,1)
        self.assertEqual(self.rescue.locate(frame,11,{'self'}),{})


if __name__=='__main__':unittest.main()
