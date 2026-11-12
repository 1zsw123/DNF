import unittest
from unittest.mock import patch
from dungeon_farm.characters import selected_profile, character_planner, validate_character, decode_role_name


class CharacterTests(unittest.TestCase):
    def test_role_name_ignores_invalid_bytes_after_aligned_terminator(self):
        self.assertEqual(decode_role_name('上头枪'.encode('utf-16le')+b'\0\0\0\xd8'),'上头枪')
        with self.assertRaises(UnicodeDecodeError):decode_role_name(b'\0\xd8\0\0')
        with self.assertRaises(ValueError):decode_role_name(b'A\0B\0')
    def test_selected_role_replaces_previous_role_without_mutating_source(self):
        original={'self_name':'旧角色','leader_name':'队友','role_types':{'旧角色':0x16f972c,'队友':0x16fc11c},'client_sha256':'test'}
        entry={'name':'新角色','role_type':0x16fc11c,'rotation':'通用全技能'}
        with patch('dungeon_farm.characters.base_profile',return_value=dict(original)):
            profile=selected_profile(entry)
        self.assertEqual(profile['self_name'],'新角色')
        self.assertEqual(profile['role_types']['新角色'],0x16fc11c)
        self.assertEqual(set(profile['role_types']),{profile['self_name'],profile['leader_name']})
        self.assertEqual(original['self_name'],'旧角色')

    def test_generic_uses_all_slots_without_berserker_toggle_or_awakening(self):
        planner=character_planner({'rotation':'通用全技能'})
        self.assertEqual({s.key for s in planner.skills},set('qwertyasdfgh'))
        self.assertTrue(all(s.mode=='attack' for s in planner.skills))

    def test_berserker_keeps_its_toggle(self):
        planner=character_planner({'rotation':'狂战士'},True)
        self.assertIn('h',planner.toggle_active)

    def test_invalid_role_cannot_start_with_an_arbitrary_address(self):
        with self.assertRaises(ValueError):
            validate_character({'name':'玩家','role_type':123,'rotation':'通用全技能'})
