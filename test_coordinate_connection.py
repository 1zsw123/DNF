import unittest
from unittest.mock import Mock, patch
from coordinate_connection import CoordinateConnection, connect_verified


def reader(pid):
    r=Mock(pid=pid)
    r.process.alive.return_value=True
    r.sample.side_effect=lambda:{'pid':pid,'self':(1,2,0),'leader':(3,4,0)}
    return r


class ReconnectTests(unittest.TestCase):
    def setUp(self):
        self.now=0
        self.created=[]
        def connect(pid,profile):
            r=reader(pid);self.created.append(r);return r
        self.connection=CoordinateConnection({'enabled':True},connect,lambda:self.now)
    def test_new_pid_closes_old_handle_and_reads_new_process(self):
        old=self.connection.sample(10)
        new=self.connection.sample(20)
        self.assertEqual(new['pid'],20)
        self.assertGreater(new['connection_generation'],old['connection_generation'])
        self.created[0].close.assert_called_once()
    def test_window_disappearing_clears_reader(self):
        self.connection.sample(10)
        self.assertIsNone(self.connection.sample(0))
        self.assertIsNone(self.connection.reader)
        self.created[0].close.assert_called_once()
    def test_reused_pid_does_not_keep_dead_handle(self):
        self.connection.sample(10)
        self.created[0].process.alive.return_value=False
        self.assertEqual(self.connection.sample(10)['connection_generation'],2)
        self.created[0].close.assert_called_once()
    def test_same_process_is_not_reopened_each_frame(self):
        for _ in range(10):self.connection.sample(10)
        self.assertEqual(len(self.created),1)
    def test_loading_process_is_retried_without_restarting_tool(self):
        connector=Mock(side_effect=[OSError('loading'),reader(10)])
        c=CoordinateConnection({'enabled':True},connector,lambda:self.now)
        self.assertIsNone(c.sample(10))
        self.now=1
        self.assertIsNone(c.sample(10))
        self.assertEqual(connector.call_count,1)
        self.now=4
        self.assertEqual(c.sample(10)['pid'],10)
    def test_changed_build_is_rejected_and_handle_closed(self):
        process=Mock();process.image_path.return_value='C:/game/dnf.exe'
        with patch('coordinate_connection.ReadOnlyProcess',return_value=process),patch('coordinate_connection.file_sha256',return_value='new'):
            with self.assertRaises(ValueError):
                connect_verified(99,{'client_path':'C:/game/dnf.exe','client_sha256':'old'})
        process.close.assert_called_once()
    def test_unready_actor_list_is_not_replaced_with_old_sample(self):
        self.connection.sample(10)
        self.created[0].sample.side_effect=lambda:None
        self.assertIsNone(self.connection.sample(10))


if __name__=='__main__':unittest.main()
