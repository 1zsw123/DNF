import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import configure_follow
import yolo_follow


class PortableTests(unittest.TestCase):
    def test_coordinate_and_name_mode_needs_no_body_model(self):
        follower = yolo_follow.Follower.__new__(yolo_follow.Follower)
        follower.session = {'self_yolo_compatible': False, 'leader_yolo_compatible': False,
                            'self_name': '上头召唤师', 'leader_name': '上头狂战'}
        follower.win = Mock()
        follower.closed = Mock()
        follower.closed.wait.return_value = True
        follower.enabled = threading.Event()
        with patch('yolo_follow.RoleDetector') as detector, \
             patch('yolo_follow.NameRescue'), patch('yolo_follow.CoordinateConnection'), \
             patch('yolo_follow.mss.mss'):
            follower.work()
        detector.assert_not_called()
        self.assertIn('坐标和名字识别已就绪', follower.message)

    def test_setup_keeps_second_pc_direction_and_verified_hash(self):
        with tempfile.TemporaryDirectory() as folder:
            client = Path(folder)/'DNF.exe'
            client.write_bytes(b'fixture')
            digest = Mock()
            digest.hexdigest.return_value = configure_follow.VERIFIED_BUILD
            with patch('configure_follow.hashlib.file_digest',return_value=digest):
                profile = configure_follow.make_profile(client)
            self.assertEqual(profile['self_name'], '上头召唤师')
            self.assertEqual(profile['leader_name'], '上头狂战')
            self.assertEqual(profile['role_types'][profile['self_name']], 0x016FC11C)
            self.assertFalse(profile['self_yolo_compatible'])
            with self.assertRaises(ValueError):
                configure_follow.make_profile(client)


if __name__ == '__main__': unittest.main()
