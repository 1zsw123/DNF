import unittest
from dungeon_farm.runtime import Control
from dungeon_farm.screen_signals import result_text
from dungeon_farm.route import onward_door,infer_entry,configured_door

class ControlTests(unittest.TestCase):
    def test_verified_branch_route_rejects_different_layout_or_entry(self):
        doors=[{'direction':'right','x':1329,'y':227},{'direction':'up','x':564,'y':169}]
        rules=[{'entry':'right','doors':{'right':[1329,227],'up':[564,169]},'exit':'up'}]
        self.assertEqual(configured_door(doors,'right',rules),doors[1])
        self.assertIsNone(configured_door(doors,'up',rules))
        self.assertIsNone(configured_door(doors+[{'direction':'down','x':500,'y':400}],'right',rules))

    def test_pause_and_stop_cancel_input(self):
        c=Control();self.assertFalse(c.cancelled())
        c.paused.set();self.assertTrue(c.cancelled())
        c.paused.clear();self.assertFalse(c.cancelled())
        c.stop.set();self.assertTrue(c.cancelled())
    def test_ghent_branch_handles_transition_entry_but_never_returns_up(self):
        from pathlib import Path
        import json
        rules=json.loads((Path(__file__).parent/'presets.json').read_text(encoding='utf8'))['根特东门']['route_rules']
        doors=[{'direction':direction,'x':xy[0],'y':xy[1]} for direction,xy in rules[0]['doors'].items()]
        for entry in ('right','left',None):
            self.assertEqual(configured_door(doors,entry,rules)['direction'],'up')
        self.assertIsNone(configured_door(doors,'up',rules))
    def test_initial_room_single_forward_door(self):
        d={'direction':'left','x':16,'y':227}
        self.assertEqual(onward_door([d],None),d)
        self.assertIsNone(onward_door([d],'left'))
    def test_entry_inference_requires_proximity(self):
        doors=[{'direction':'left','x':10,'y':200},{'direction':'right','x':1200,'y':200}]
        self.assertEqual(infer_entry(doors,(1150,200)),'right')
        self.assertIsNone(infer_entry(doors,(600,200)))
    def test_result_requires_result_context(self):
        self.assertTrue(result_text(['Result','经验值']))
        self.assertTrue(result_text(['再次挑戰','返回城鎮']))
        self.assertFalse(result_text(['Rank','SSS','连击']))
        self.assertFalse(result_text(['再次挑战者','上头狂战']))
