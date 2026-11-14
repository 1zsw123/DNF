import unittest
from dungeon_farm.town_entry import EntranceAlignment

class EntranceAlignmentTests(unittest.TestCase):
    def test_moving_right_never_triggers_vertical_probe(self):
        a=EntranceAlignment()
        for x in (100,150,200,250):self.assertEqual(a.direction((x,250,0)),'right')

    def test_edge_uses_bounded_alignment_with_right_retry_between_probes(self):
        a=EntranceAlignment()
        self.assertEqual([a.direction((849,250,0)) for _ in range(9)],
                         ['right','up','right','down','right','down','right','right','right'])

    def test_invalid_sample_cannot_create_false_stall(self):
        a=EntranceAlignment()
        self.assertEqual(a.direction(None),'right')
        self.assertEqual(a.direction((float('nan'),250,0)),'right')
        self.assertIsNone(a.previous)


class HellDifficultySelectionTests(unittest.TestCase):
    """Town selection steps right from 普通 up to the chosen 地狱 then enters."""
    def select(self,start,target):
        import threading
        from unittest.mock import MagicMock,patch
        levels=['普通','冒险','勇士','王者','地狱']
        state={'level':levels.index(start)};pressed=[]
        control=MagicMock();control.stop=threading.Event();control.paused=threading.Event()
        control.cancelled=lambda:False
        class Screen:
            def poll(self,*a,**k):
                return {'exhausted':False,'overlay':False,'finished':False,'dead':False,'selection':True,
                        'dungeon_option':(1,1),'target_selected':True,'difficulty':levels[state['level']],'texts':[]}
            def close(self):pass
        class Keys:
            def key(self,name,hwnd,cancelled):
                pressed.append(name)
                if name=='difficulty_right':state['level']=min(4,state['level']+1)
                if name=='difficulty_left':state['level']=max(0,state['level']-1)
                if name=='enter':control.stop.set()
                return True
        conn=MagicMock();conn.sample.return_value=None;conn.reader=None
        control.stop.wait=lambda *_:False
        with patch('dungeon_farm.town_entry.Windows'),patch('dungeon_farm.town_entry.Path'), \
             patch('dungeon_farm.town_entry.ScreenSignals',return_value=Screen()), \
             patch('dungeon_farm.town_entry.CycleInputs',return_value=Keys()), \
             patch('dungeon_farm.town_entry.CoordinateConnection',return_value=conn), \
             patch('dungeon_farm.characters.selected_profile',return_value={'self_name':'上头狂战'}):
            from dungeon_farm.town_entry import prepare
            prepare(control,lambda update:None,allow_town_entry=True,dungeon='追击歼灭战',difficulty=target)
        return pressed,levels[state['level']]

    def test_steps_up_to_hell_and_enters(self):
        pressed,final=self.select('普通','地狱级')
        self.assertEqual(pressed,['difficulty_right']*4+['enter'])
        self.assertEqual(final,'地狱')

    def test_steps_down_from_hell_to_king(self):
        pressed,final=self.select('地狱','王者级')
        self.assertEqual(pressed,['difficulty_left','enter'])
        self.assertEqual(final,'王者')
