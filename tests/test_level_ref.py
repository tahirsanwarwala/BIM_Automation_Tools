# -*- coding: utf-8 -*-
"""Re-pointing a level-based element at the level below it.

A wall carries a base AND a top and can be cut in half; everything else
carries one level reference and an offset from it.  This is the
arithmetic for that one reference, and it has exactly one job beyond
choosing the level: the element must not move.  The new offset is
DEFINED as the difference between the element's reference elevation and
its new level, so conserving the elevation is not something the code
remembers to do -- it is the only thing it can do.
"""

import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LIB = os.path.join(_ROOT, "Revit API", "pyRevit-Tools.extension", "lib")
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

from BG import level_ref


IN = 1.0 / 12.0

LEVELS = [
    ("L1", 0.0),
    ("L2", 10.0),
    ("L3", 20.0),
]


class TestTheReferencePoint(unittest.TestCase):

    def test_it_is_the_level_plus_the_offset(self):
        self.assertAlmostEqual(level_ref.reference_z(10.0, 2.0), 12.0)

    def test_a_negative_offset_hangs_below_the_level(self):
        self.assertAlmostEqual(level_ref.reference_z(10.0, -2.0), 8.0)


class TestChoosingTheLevel(unittest.TestCase):
    """Always the level at or immediately below the reference point."""

    def test_an_element_between_levels_takes_the_one_below(self):
        level_id, offset = level_ref.rebase(13.0, LEVELS)
        self.assertEqual(level_id, "L2")
        self.assertAlmostEqual(offset, 3.0)

    def test_an_element_exactly_on_a_level_stays_there(self):
        level_id, offset = level_ref.rebase(10.0, LEVELS)
        self.assertEqual(level_id, "L2")
        self.assertAlmostEqual(offset, 0.0)

    def test_an_offset_within_tolerance_is_written_as_zero(self):
        _level_id, offset = level_ref.rebase(10.0 + 0.5 * level_ref.TOL,
                                             LEVELS)
        self.assertEqual(offset, 0.0)

    def test_a_dropped_slab_falls_to_the_storey_below(self):
        # The rule taken literally, as asked: two inches under L2 is
        # L1 plus very nearly a whole storey.
        level_id, offset = level_ref.rebase(20.0 - 2 * IN, LEVELS)
        self.assertEqual(level_id, "L2")
        self.assertAlmostEqual(offset, 10.0 - 2 * IN)

    def test_an_element_below_every_level_hangs_off_the_lowest(self):
        # The only case that yields a negative offset, and the same
        # answer wall_constraints gives a wall below everything.
        level_id, offset = level_ref.rebase(-4.0, LEVELS)
        self.assertEqual(level_id, "L1")
        self.assertAlmostEqual(offset, -4.0)

    def test_an_element_above_every_level_takes_the_highest(self):
        level_id, offset = level_ref.rebase(25.0, LEVELS)
        self.assertEqual(level_id, "L3")
        self.assertAlmostEqual(offset, 5.0)

    def test_no_levels_is_refused(self):
        with self.assertRaises(ValueError):
            level_ref.rebase(5.0, [])


class TestTheElementNeverMoves(unittest.TestCase):
    """The property the whole feature rests on."""

    def test_the_reference_elevation_survives_any_rebase(self):
        for z in (-9.0, 0.0, 0.5, 9.99, 10.0, 10.01, 19.5, 20.0, 31.25):
            level_id, offset = level_ref.rebase(z, LEVELS)
            elevation = dict(LEVELS)[level_id]
            self.assertAlmostEqual(
                level_ref.reference_z(elevation, offset), z,
                msg="rebasing moved an element referenced at {0}".format(z))


class TestWhetherAnythingNeedsDoing(unittest.TestCase):

    def test_an_element_already_on_the_right_level_needs_nothing(self):
        self.assertFalse(level_ref.needs_rebase("L2", 3.0, LEVELS))

    def test_an_element_on_the_wrong_level_needs_rebasing(self):
        # Referenced from L1 but standing at 13 ft: L2 + 3 is right.
        self.assertTrue(level_ref.needs_rebase("L1", 13.0, LEVELS))

    def test_a_hair_of_offset_drift_is_not_worth_rewriting(self):
        self.assertFalse(
            level_ref.needs_rebase("L2", 3.0 + 0.5 * level_ref.TOL, LEVELS))

    def test_an_unknown_level_needs_rebasing(self):
        # Its elevation cannot be read, so it cannot be judged correct.
        self.assertTrue(level_ref.needs_rebase("gone", 3.0, LEVELS))


class TestTheReferencePointMustDescribeTheElement(unittest.TestCase):
    """Does level + offset actually say where this element IS?

    For most categories it does -- it is the point Revit places them
    from.  For a CURTAIN PANEL it does not: the panel is placed by the
    curtain grid, and its level and elevation parameters are left
    saying something else entirely.  A door panel standing at 13'-0"
    reported Level 01 with an offset of -13'-0", making a reference
    point of 0'-0"; that is below every level in the building, so it
    was rebased onto the lowest one and its BG_LEVEL came out as the
    basement.

    Nothing about that is wrong arithmetic -- 0'-0" really is below
    everything.  The input was never a position.  So a reference point
    is now checked against the element's own vertical extent before it
    is believed, which catches this for every category, including the
    ones nobody has thought of yet.
    """

    def test_a_point_inside_the_element_is_believed(self):
        self.assertTrue(level_ref.describes(13.0, 13.0, 20.0))

    def test_a_point_at_the_very_bottom_is_believed(self):
        # A family instance placed at its own base.
        self.assertTrue(level_ref.describes(13.0, 13.0, 20.0))

    def test_a_point_at_the_very_top_is_believed(self):
        # A floor, whose reference is the top of the slab.
        self.assertTrue(level_ref.describes(20.0, 13.0, 20.0))

    def test_a_point_just_outside_is_still_believed(self):
        # Slack, because a reference point is allowed to sit a little
        # off the solid -- a fitting hung below its insertion point.
        self.assertTrue(level_ref.describes(12.5, 13.0, 20.0))

    def test_the_curtain_panel_case_is_refused(self):
        # The door in the report: reference point 0'-0", panel at 13.
        self.assertFalse(level_ref.describes(0.0, 13.0, 20.0))

    def test_a_point_far_above_is_refused(self):
        self.assertFalse(level_ref.describes(40.0, 13.0, 20.0))

    def test_an_unknown_extent_is_believed(self):
        # Not being able to measure an element is not evidence against
        # its parameters; it just means this check cannot help.
        self.assertTrue(level_ref.describes(0.0, None, None))

    def test_the_slack_can_be_set(self):
        self.assertFalse(level_ref.describes(10.0, 13.0, 20.0, slack=1.0))
        self.assertTrue(level_ref.describes(10.0, 13.0, 20.0, slack=5.0))


if __name__ == "__main__":
    unittest.main()
