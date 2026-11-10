import unittest
from dungeon_farm.inventory import quantities,disassemble_needed,cube_quantity

class InventoryTests(unittest.TestCase):
    def test_real_split_decimal_ocr_is_not_used_as_quantity(self):
        self.assertEqual(cube_quantity(['无色小晶块'],[['17.36',.85],['',0],['1736',.98],['1736',.985]]),1736)
        self.assertIsNone(cube_quantity(['无色小晶块'],[['17.36',.98],['17.36',.98]]))
        self.assertEqual(cube_quantity(['无色小晶块'],[['17.29',.94],['17.29',.91],['1729',.995]]),1729)
    def test_wrong_item_or_conflicting_counts_are_not_accepted(self):
        self.assertIsNone(cube_quantity(['蓝色小晶块'],[['1736',.98],['1736',.98]]))
        self.assertIsNone(cube_quantity(['无色小晶块'],[['1736',.98],['1736',.98],['36',.99],['36',.99]]))
    def test_exact_item_only(self):
        self.assertEqual(quantities(['1,630,483金币','1716 无色小晶块']),{'gold':1630483,'cubes':1716})
        self.assertIsNone(quantities(['1716白色小晶块','无色小晶块x34'])['cubes'])
    def test_stock_policy(self):
        self.assertFalse(disassemble_needed(1716))
        self.assertFalse(disassemble_needed(100))
        self.assertTrue(disassemble_needed(99))
        self.assertTrue(disassemble_needed(None))
