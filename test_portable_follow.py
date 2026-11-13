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
                profile = configure_follow.make_profile(client,'新小号','新大号')
            self.assertEqual(profile['self_name'], '新小号')
            self.assertEqual(profile['leader_name'], '新大号')
            self.assertEqual(profile['role_types'], {})
            self.assertTrue(profile['automatic_role_types'])
            self.assertFalse(profile['self_yolo_compatible'])
            with self.assertRaises(ValueError):
                configure_follow.make_profile(client,'新小号','新大号')

    def test_worker_switch_closes_old_readers_and_replaces_name_cache_while_paused(self):
        f=yolo_follow.Follower.__new__(yolo_follow.Follower)
        old={'self_name':'旧小号','leader_name':'旧大号','self_yolo_compatible':False,'leader_yolo_compatible':False}
        new={**old,'self_name':'新小号','leader_name':'新大号'}
        f.session=old;f.win=Mock();f.closed=Mock();f.enabled=threading.Event();f.switch_pending=threading.Event()
        def first_wait(_):f.session=new;f.switch_pending.set();f.closed.wait.side_effect=None;f.closed.wait.return_value=True;return False
        f.closed.wait.side_effect=first_wait
        old_conn,new_conn,old_rescue,new_rescue=[Mock() for _ in range(4)]
        with patch('yolo_follow.CoordinateConnection',side_effect=[old_conn,new_conn]) as connection, \
             patch('yolo_follow.NameRescue',side_effect=[old_rescue,new_rescue]) as rescue,patch('yolo_follow.mss.mss'):
            f.work()
        old_conn.close.assert_called_once();old_rescue.close.assert_called_once()
        self.assertIs(connection.call_args_list[-1].args[0],new)
        self.assertEqual(rescue.call_args.args[0]['leader_names'],['新大号'])
        self.assertFalse(f.switch_pending.is_set());f.win.apply.assert_not_called()

    def test_profile_persistence_does_not_change_farming_session(self):
        import json
        from follow_profiles import load_profile,save_profile,with_names
        with tempfile.TemporaryDirectory() as folder:
            legacy=Path(folder)/'coordinate-session.json'
            legacy.write_text(json.dumps({'self_name':'旧小号','leader_name':'旧大号','role_types':{'旧小号':1,'旧大号':2}}),encoding='utf8')
            before=legacy.read_bytes()
            updated=with_names(load_profile(folder),' 新小号 ','新大号')
            save_profile(folder,updated)
            self.assertEqual(load_profile(folder)['self_name'],'新小号')
            self.assertEqual(legacy.read_bytes(),before)
            for own,leader in (('','大号'),('同名','同名'),('坏\n名字','大号')):
                with self.assertRaises(ValueError):with_names(updated,own,leader)


if __name__ == '__main__': unittest.main()
