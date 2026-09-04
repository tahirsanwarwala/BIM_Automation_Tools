# -*- coding: utf-8 -*-
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LIB = os.path.join(_ROOT, "Revit API", "pyRevit-Tools.extension", "lib")
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

from Tahir import wall_naming as wn


class TestFeetToImperial(unittest.TestCase):

    def test_whole_inches(self):
        self.assertEqual(wn.feet_to_imperial(0.666667), "0' 8\"")

    def test_fractional_inches(self):
        self.assertEqual(wn.feet_to_imperial(0.302083), "0' 3 5/8\"")

    def test_whole_feet_and_inches(self):
        self.assertEqual(wn.feet_to_imperial(1.5), "1' 6\"")

    def test_zero(self):
        self.assertEqual(wn.feet_to_imperial(0.0), "0' 0\"")

    def test_fraction_reduces(self):
        # 2/16 must print as 1/8, not 2/16
        self.assertEqual(wn.feet_to_imperial(0.0104167), "0' 1/8\"")


class TestShortMaterialCode(unittest.TestCase):
    """The library's real material names, from the user's screenshot."""

    def test_standard_name(self):
        self.assertEqual(
            wn.short_material_code("_ST-03 - Masonry - Brick  - Common Bond (FNS-B4)"),
            "COMMON BOND (FNS-B4)")

    def test_code_without_brackets(self):
        self.assertEqual(
            wn.short_material_code(
                "_ST-03 - Masonry - Brick - Common Bond(Beige Dragfaced) FNS-B6"),
            "COMMON BOND(BEIGE DRAGFACED) FNS-B6")

    def test_missing_space_before_separator(self):
        self.assertEqual(
            wn.short_material_code("_ST-03 -Masonry - Brick - English Bond (FNS-B1)"),
            "ENGLISH BOND (FNS-B1)")

    def test_two_materials_sharing_a_code_stay_distinct(self):
        a = wn.short_material_code(
            "_ST-03 - Masonry - Brick Header - Soldier Course (FNS-B3)")
        b = wn.short_material_code(
            "_ST-03 - Masonry - Brick Header - Soldier Course (FNS-B3)(sides)")
        self.assertEqual(a, "SOLDIER COURSE (FNS-B3)")
        self.assertEqual(b, "SOLDIER COURSE (FNS-B3)(SIDES)")
        self.assertNotEqual(a, b)

    def test_material_with_no_code(self):
        self.assertEqual(
            wn.short_material_code("_ST-05 - Large Format"), "LARGE FORMAT")

    def test_name_without_any_separator(self):
        self.assertEqual(wn.short_material_code("Brick"), "BRICK")

    def test_empty_name_is_safe(self):
        self.assertEqual(wn.short_material_code(""), "UNKNOWN")
        self.assertEqual(wn.short_material_code(None), "UNKNOWN")


class TestExtractTypeTag(unittest.TestCase):

    def test_brick(self):
        self.assertEqual(
            wn.extract_type_tag('Exterior - Brick_Insul_6" Stud_Gyp'), "BRICK")

    def test_adhered_stone(self):
        self.assertEqual(
            wn.extract_type_tag("Exterior - Adhered Stone_CMU_Stone"),
            "ADHERED STONE")

    def test_large_stone(self):
        self.assertEqual(
            wn.extract_type_tag('Exterior - Large Stone_Insul_6" Stud_Large Stone'),
            "LARGE STONE")

    def test_eifs_with_stud(self):
        self.assertEqual(
            wn.extract_type_tag('Exterior - EIFS Ash Grey_3 5/8" Stud_Gyp'),
            "EIFS ASH GREY")

    def test_no_underscore(self):
        self.assertEqual(
            wn.extract_type_tag('Exterior - 12" Concrete'), '12" CONCRETE')

    def test_no_exterior_prefix(self):
        self.assertEqual(wn.extract_type_tag("Brick_Insul"), "BRICK")


class TestSkinTypeName(unittest.TestCase):

    def test_assembles_all_three_parts(self):
        self.assertEqual(
            wn.skin_type_name("BRICK", "COMMON BOND (FNS-B4)", "0' 3 5/8\""),
            "SKIN_BRICK_COMMON BOND (FNS-B4)_0' 3 5/8\"")

    def test_does_not_contain_ext(self):
        name = wn.skin_type_name("LARGE STONE", "LARGE FORMAT", "0' 2\"")
        self.assertNotIn("EXT", name)
        self.assertTrue(name.startswith("SKIN_"))

    def test_is_upper_case(self):
        name = wn.skin_type_name("brick", "common bond (fns-b4)", "0' 3 5/8\"")
        self.assertEqual(name, "SKIN_BRICK_COMMON BOND (FNS-B4)_0' 3 5/8\"")

    def test_same_material_different_thickness_gives_different_names(self):
        a = wn.skin_type_name("BRICK", "COMMON BOND (FNS-B4)", "0' 3 5/8\"")
        b = wn.skin_type_name("BRICK", "COMMON BOND (FNS-B4)", "0' 4\"")
        self.assertNotEqual(a, b)


# One sixteenth of an inch, in feet.  wall_materials.NAME_THICKNESS_TOL
# is the same number, and the tests below are why it is that number: a
# generated name states its thickness to the nearest sixteenth, so a
# type already carrying the name a plan wants is that plan's type as
# long as it is within a sixteenth of the wanted thickness.  Reusing it
# is what stops the tools leaving "... (2)", "... (3)" behind.
NAME_TOL = 1.0 / 12.0 / 16.0


class TestThicknessNamingResolution(unittest.TestCase):

    def test_thicknesses_a_hair_apart_share_a_name(self):
        # 0.025 in apart -- more than wall_materials.TYPE_THICKNESS_TOL,
        # so these are two separate PLANS, yet one name.  That collision
        # is what produced the duplicate wall types.
        a = wn.feet_to_imperial(3.625 / 12.0)
        b = wn.feet_to_imperial(3.650 / 12.0)
        self.assertEqual(a, b)
        self.assertEqual(a, "0' 3 5/8\"")

    def test_sharing_a_name_bounds_the_thickness_difference(self):
        # The invariant NAME_THICKNESS_TOL relies on: anything sharing a
        # name is within a sixteenth of an inch.  Swept across a range
        # at a step far finer than the naming resolution.
        by_name = {}
        step = 1.0 / 12.0 / 256.0
        value = 3.0 / 12.0
        while value <= 5.0 / 12.0:
            by_name.setdefault(wn.feet_to_imperial(value), []).append(value)
            value += step

        self.assertGreater(len(by_name), 20)     # the sweep really varied
        for name, values in by_name.items():
            spread = max(values) - min(values)
            self.assertLessEqual(
                spread, NAME_TOL + 1e-9,
                "{!r} covers a spread of {:.5f} ft, more than a "
                "sixteenth".format(name, spread))

    def test_a_sixteenth_apart_gives_different_names(self):
        # The other side of it: a real thickness change is never hidden.
        a = wn.feet_to_imperial(3.625 / 12.0)
        b = wn.feet_to_imperial((3.625 + 1.0 / 16.0) / 12.0)
        self.assertNotEqual(a, b)


if __name__ == "__main__":
    unittest.main()
