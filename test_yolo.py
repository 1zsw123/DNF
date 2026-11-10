import unittest
import numpy as np
from yolo_detector import RoleDetector


class DecodeTests(unittest.TestCase):
    def test_two_roles_and_letterbox_coordinates_are_kept_separate(self):
        r=640/819
        output=np.array([[
            [460*r,465*r+80,60*r,130*r,.95,.02],
            [735*r,447.5*r+80,70*r,135*r,.01,.91],
            [461*r,466*r+80,60*r,130*r,.75,.01],
            [100*r,35*r+80,50*r,30*r,.99,.01],
        ]],dtype=np.float32).transpose(0,2,1)
        roles,boxes=RoleDetector.decode(output,(614,819,3),r,(0,80))
        self.assertEqual(len(boxes),2)
        self.assertAlmostEqual(roles['self']['foot'][0],460,places=2)
        self.assertAlmostEqual(roles['self']['foot'][1],527,places=2)
        self.assertAlmostEqual(roles['leader']['foot'][0],735,places=2)

    def test_incompatible_model_is_rejected(self):
        with self.assertRaises(ValueError):
            RoleDetector.decode(np.zeros((1,15,8400),np.float32),(614,819,3),1,(0,0))


if __name__=='__main__':unittest.main()
