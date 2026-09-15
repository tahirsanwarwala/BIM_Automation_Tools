# -*- coding: utf-8 -*-
"""Do two walls occupy the same space, and does it matter?

Every case here is drawn in plan with numbers a person can check by
hand: an eight inch wall is 8/12 of a foot thick, so its face is 4/12
either side of the line it was drawn on.  If a test fails, draw it.
"""

import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LIB = os.path.join(_ROOT, "Revit API", "pyRevit-Tools.extension", "lib")
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

from BG import wall_overlap as wo


INCH = 1.0 / 12.0
T8 = 8.0 * INCH          # an ordinary eight inch wall
STOREY = 10.0            # ten feet, floor to floor


def wall(x0, y0, x1, y1, thickness=T8, z0=0.0, z1=STOREY, key="w"):
    """A straight wall drawn from one point to another, in feet."""
    return wo.straight_wall(key, (x0, y0), (x1, y1), thickness, z0, z1)


class TestSeparationDepth(unittest.TestCase):
    """The one number the tolerance is compared against."""

    def test_two_walls_end_to_end_overlapping_half_an_inch(self):
        # A runs 0 -> 10.  B starts half an inch before A ends.
        a = wall(0, 0, 10, 0)
        b = wall(10 - 0.5 * INCH, 0, 20, 0, key="b")
        hit = wo.check_walls(a, b, tol=0.0)
        self.assertIsNotNone(hit)
        self.assertAlmostEqual(hit.depth, 0.5 * INCH, places=9)

    def test_end_to_end_butt_joint_is_not_an_overlap(self):
        a = wall(0, 0, 10, 0)
        b = wall(10, 0, 20, 0, key="b")
        self.assertIsNone(wo.check_walls(a, b, tol=0.0))

    def test_walls_that_do_not_touch_are_not_an_overlap(self):
        a = wall(0, 0, 10, 0)
        b = wall(12, 0, 20, 0, key="b")
        self.assertIsNone(wo.check_walls(a, b, tol=0.0))

    def test_side_by_side_skins_biting_a_quarter_inch(self):
        # Faces would touch at y = 8/12.  Pull B a quarter inch closer.
        a = wall(0, 0, 10, 0)
        b = wall(0, T8 - 0.25 * INCH, 10, T8 - 0.25 * INCH, key="b")
        hit = wo.check_walls(a, b, tol=0.0)
        self.assertIsNotNone(hit)
        self.assertAlmostEqual(hit.depth, 0.25 * INCH, places=9)

    def test_side_by_side_skins_exactly_touching_are_clean(self):
        a = wall(0, 0, 10, 0)
        b = wall(0, T8, 10, T8, key="b")
        self.assertIsNone(wo.check_walls(a, b, tol=0.0))

    def test_depth_is_how_far_an_end_is_buried_past_the_face(self):
        # B runs east-west.  A comes up from the south and stops two
        # inches past B's centre line, so it is buried 4" + 2" = 6"
        # measured from the face it went in through.
        b = wall(-10, 0, 10, 0, key="b")
        a = wall(0, -10, 0, 2.0 * INCH)
        hit = wo.check_walls(a, b, tol=1.0 * INCH)
        self.assertIsNotNone(hit)
        self.assertAlmostEqual(hit.depth, 6.0 * INCH, places=9)


class TestVertical(unittest.TestCase):
    """Sharing a plan position is only half of being in the same place."""

    def test_same_plan_position_but_stacked_storeys_is_clean(self):
        a = wall(0, 0, 10, 0, z0=0.0, z1=10.0)
        b = wall(0, 0, 10, 0, z0=10.0, z1=20.0, key="b")
        self.assertIsNone(wo.check_walls(a, b, tol=0.0))

    def test_a_quarter_inch_of_vertical_bite_is_measured_vertically(self):
        a = wall(0, 0, 10, 0, z0=0.0, z1=10.0)
        b = wall(0, 0, 10, 0, z0=10.0 - 0.25 * INCH, z1=20.0, key="b")
        hit = wo.check_walls(a, b, tol=0.0)
        self.assertIsNotNone(hit)
        self.assertAlmostEqual(hit.depth, 0.25 * INCH, places=9)

    def test_and_a_quarter_inch_of_vertical_bite_passes_a_one_inch_tolerance(self):
        a = wall(0, 0, 10, 0, z0=0.0, z1=10.0)
        b = wall(0, 0, 10, 0, z0=10.0 - 0.25 * INCH, z1=20.0, key="b")
        self.assertIsNone(wo.check_walls(a, b, tol=1.0 * INCH))


class TestKind(unittest.TestCase):

    def test_two_walls_in_the_same_place_are_a_duplicate(self):
        a = wall(0, 0, 10, 0)
        b = wall(0, 0, 10, 0, key="b")
        hit = wo.check_walls(a, b, tol=0.0)
        self.assertEqual(hit.kind, wo.DUPLICATE)

    def test_a_duplicate_is_reported_however_loose_the_tolerance(self):
        a = wall(0, 0, 10, 0)
        b = wall(0, 0, 10, 0, key="b")
        self.assertIsNotNone(wo.check_walls(a, b, tol=10.0))

    def test_a_wall_of_another_thickness_in_the_same_place_is_still_flagged(self):
        a = wall(0, 0, 10, 0, thickness=T8)
        b = wall(0, 0, 10, 0, thickness=6.0 * INCH, key="b")
        self.assertIn(wo.check_walls(a, b, tol=10.0).kind,
                      (wo.DUPLICATE, wo.CONTAINED))

    def test_a_short_wall_sitting_inside_a_long_one_is_contained(self):
        a = wall(0, 0, 20, 0)
        b = wall(5, 0, 8, 0, key="b")
        hit = wo.check_walls(a, b, tol=0.0)
        self.assertEqual(hit.kind, wo.CONTAINED)

    def test_containment_is_reported_however_loose_the_tolerance(self):
        a = wall(0, 0, 20, 0)
        b = wall(5, 0, 8, 0, key="b")
        self.assertIsNotNone(wo.check_walls(a, b, tol=10.0))

    def test_an_overlapping_run_on_one_axis_is_collinear(self):
        a = wall(0, 0, 10, 0)
        b = wall(9, 0, 20, 0, key="b")
        self.assertEqual(wo.check_walls(a, b, tol=INCH).kind, wo.COLLINEAR)

    def test_a_collinear_pair_reports_how_long_the_shared_run_is(self):
        a = wall(0, 0, 10, 0)
        b = wall(9, 0, 20, 0, key="b")
        self.assertAlmostEqual(wo.check_walls(a, b, tol=INCH).run, 1.0, places=9)

    def test_a_wall_driven_through_the_middle_of_another_is_crossing(self):
        a = wall(-10, 0, 10, 0)
        b = wall(0, -10, 0, 10, key="b")
        self.assertEqual(wo.check_walls(a, b, tol=INCH).kind, wo.CROSSING)

    def test_a_wall_crossing_at_forty_five_degrees_is_crossing(self):
        a = wall(-10, 0, 10, 0)
        b = wall(-10, -10, 10, 10, key="b")
        self.assertEqual(wo.check_walls(a, b, tol=INCH).kind, wo.CROSSING)

    def test_walls_two_degrees_apart_still_count_as_parallel(self):
        import math
        a = wall(0, 0, 10, 0)
        r = math.radians(2.0)
        b = wall(0, 0, 10 * math.cos(r), 10 * math.sin(r), key="b")
        self.assertIn(wo.check_walls(a, b, tol=INCH).kind,
                      (wo.COLLINEAR, wo.DUPLICATE, wo.CONTAINED))


class TestCornerForgiveness(unittest.TestCase):
    """An L and a T are how buildings are drawn, not mistakes."""

    def test_an_l_corner_drawn_line_to_line_is_forgiven(self):
        a = wall(0, 0, 10, 0)
        b = wall(10, 0, 10, 10, key="b")
        self.assertIsNone(wo.check_walls(a, b, tol=INCH))

    def test_a_t_junction_stopping_on_the_centre_line_is_forgiven(self):
        b = wall(-10, 0, 10, 0, key="b")
        a = wall(0, -10, 0, 0)
        self.assertIsNone(wo.check_walls(a, b, tol=INCH))

    def test_a_t_junction_stopping_short_of_the_centre_line_is_forgiven(self):
        b = wall(-10, 0, 10, 0, key="b")
        a = wall(0, -10, 0, -3.0 * INCH)
        self.assertIsNone(wo.check_walls(a, b, tol=INCH))

    def test_a_t_junction_two_inches_past_the_centre_line_is_flagged(self):
        b = wall(-10, 0, 10, 0, key="b")
        a = wall(0, -10, 0, 2.0 * INCH)
        self.assertIsNotNone(wo.check_walls(a, b, tol=INCH))

    def test_an_overshoot_inside_the_tolerance_is_forgiven(self):
        b = wall(-10, 0, 10, 0, key="b")
        a = wall(0, -10, 0, 0.5 * INCH)
        self.assertIsNone(wo.check_walls(a, b, tol=INCH))

    def test_a_wall_passing_clean_through_another_is_never_forgiven(self):
        b = wall(-10, 0, 10, 0, key="b")
        a = wall(0, -10, 0, 10)
        self.assertIsNotNone(wo.check_walls(a, b, tol=INCH))

    def test_forgiveness_does_not_apply_to_a_collinear_overlap(self):
        # Two walls on one line overlapping an inch and a half.  Both
        # ends are involved, but an end-to-end joint should meet at
        # nothing, so there is no corner here to forgive.
        a = wall(0, 0, 10, 0)
        b = wall(10 - 1.5 * INCH, 0, 20, 0, key="b")
        self.assertIsNotNone(wo.check_walls(a, b, tol=INCH))

    def test_forgiveness_does_not_apply_to_side_by_side_skins(self):
        a = wall(0, 0, 10, 0)
        b = wall(0, T8 - 1.5 * INCH, 10, T8 - 1.5 * INCH, key="b")
        self.assertIsNotNone(wo.check_walls(a, b, tol=INCH))


class TestTolerance(unittest.TestCase):

    def test_a_bite_under_the_tolerance_is_not_reported(self):
        a = wall(0, 0, 10, 0)
        b = wall(10 - 0.5 * INCH, 0, 20, 0, key="b")
        self.assertIsNone(wo.check_walls(a, b, tol=1.0 * INCH))

    def test_a_bite_over_the_tolerance_is_reported(self):
        a = wall(0, 0, 10, 0)
        b = wall(10 - 2.0 * INCH, 0, 20, 0, key="b")
        self.assertIsNotNone(wo.check_walls(a, b, tol=1.0 * INCH))

    def test_a_bite_exactly_on_the_tolerance_is_not_reported(self):
        a = wall(0, 0, 10, 0)
        b = wall(10 - 1.0 * INCH, 0, 20, 0, key="b")
        self.assertIsNone(wo.check_walls(a, b, tol=1.0 * INCH))


class TestCurvedWalls(unittest.TestCase):
    """An arc is carried as the run of straight pieces it was drawn as."""

    def test_a_polyline_wall_overlapping_at_its_far_end_is_found(self):
        a = wo.polyline_wall("a", [(0, 0), (10, 0), (10, 10)], T8, 0.0, STOREY)
        b = wall(10, 9, 10, 20, key="b")
        hit = wo.check_walls(a, b, tol=0.0)
        self.assertIsNotNone(hit)
        self.assertAlmostEqual(hit.run, 1.0, places=9)

    def test_a_corner_inside_one_polyline_wall_is_not_its_own_end(self):
        # Something laid over the middle of a polyline is a real
        # overlap, even though it meets one piece at that piece's end.
        a = wo.polyline_wall("a", [(0, 0), (10, 0), (10, 10)], T8, 0.0, STOREY)
        b = wall(10, -5, 10, 5, key="b")
        self.assertIsNotNone(wo.check_walls(a, b, tol=INCH))


class TestSymmetry(unittest.TestCase):

    def test_the_answer_does_not_depend_on_the_order_of_the_pair(self):
        cases = [
            (wall(0, 0, 10, 0), wall(9, 0, 20, 0, key="b")),
            (wall(-10, 0, 10, 0), wall(0, -10, 0, 2.0 * INCH, key="b")),
            (wall(0, 0, 10, 0), wall(10, 0, 10, 10, key="b")),
            (wall(0, 0, 20, 0), wall(5, 0, 8, 0, key="b")),
        ]
        for a, b in cases:
            one = wo.check_walls(a, b, tol=INCH)
            two = wo.check_walls(b, a, tol=INCH)
            self.assertEqual(one is None, two is None)
            if one is not None:
                self.assertEqual(one.kind, two.kind)
                self.assertAlmostEqual(one.depth, two.depth, places=9)


if __name__ == "__main__":
    unittest.main()


class TestVolumeOverrulesTheFootprint(unittest.TestCase):
    """A wall standing in a hole cut in another wall is not swallowed.

    The arched opening case: a brick wall with an arch cut out of it,
    and an arched surround wall standing in the opening.  In plan they
    are the same rectangle, top to bottom, so the footprints say one ate
    the other.  The volumes say they barely touch.
    """

    def setUp(self):
        self.host = wall(0, 0, 20, 0)
        self.infill = wall(8, 0, 12, 0, key="b")
        self.hit = wo.check_walls(self.host, self.infill, tol=0.0)
        # box volumes, for talking about walls that are not hollow
        self.box_host = self.host.plan_area * self.host.height
        self.box_infill = self.infill.plan_area * self.infill.height

    def test_the_footprint_on_its_own_calls_it_contained(self):
        self.assertEqual(self.hit.kind, wo.CONTAINED)

    def test_sharing_no_real_volume_takes_the_label_away(self):
        out = wo.verify(self.hit, tol=INCH, shared=0.0,
                        vol_a=self.box_host, vol_b=self.box_infill)
        self.assertNotIn(wo.CONTAINED, [out.kind] if out else [])

    def test_a_wall_with_a_hole_in_it_cannot_swallow_anything(self):
        # No shared volume known -- the joined case -- but the host is
        # only half the volume its footprint claims, so it has a hole.
        out = wo.verify(self.hit, tol=INCH, shared=None,
                        vol_a=self.box_host * 0.5, vol_b=self.box_infill)
        self.assertTrue(out is None or out.kind != wo.CONTAINED)

    def test_two_solid_walls_keep_the_label(self):
        out = wo.verify(self.hit, tol=INCH, shared=None,
                        vol_a=self.box_host, vol_b=self.box_infill)
        self.assertEqual(out.kind, wo.CONTAINED)

    def test_a_shared_volume_that_does_cover_the_smaller_keeps_the_label(self):
        out = wo.verify(self.hit, tol=INCH, shared=self.box_infill,
                        vol_a=self.box_host, vol_b=self.box_infill)
        self.assertEqual(out.kind, wo.CONTAINED)

    def test_unknown_volumes_leave_the_footprint_its_word(self):
        out = wo.verify(self.hit, tol=INCH)
        self.assertEqual(out.kind, wo.CONTAINED)

    def test_a_demoted_pair_is_marked_as_second_guessed(self):
        out = wo.verify(self.hit, tol=0.0, shared=0.0,
                        vol_a=self.box_host, vol_b=self.box_infill)
        if out is not None:
            self.assertTrue(out.demoted)

    def test_a_demoted_pair_must_now_clear_the_tolerance(self):
        # Two walls a quarter inch into each other, wrongly called
        # contained: once demoted, an inch of tolerance clears them.
        a = wall(0, 0, 10, 0)
        b = wall(0, T8 - 0.25 * INCH, 10, T8 - 0.25 * INCH, key="b")
        hit = wo.check_walls(a, b, tol=0.0)
        hit.kind = wo.CONTAINED          # as the footprint would have it
        self.assertIsNone(wo.verify(hit, tol=INCH, shared=0.0,
                                    vol_a=1.0, vol_b=1.0))

    def test_a_demoted_crossing_faces_the_junction_rule_again(self):
        # A stub only three inches long, T-ing into a wall four inches
        # thick, sits almost wholly inside it -- so the footprint calls
        # it swallowed and the junction rule never gets a turn.  Take
        # the label away and it is a plain T again, not an overlap.
        host = wall(0, 0, 20, 0, key="b")
        stub = wall(10, -3.0 * INCH, 10, 0)
        hit = wo.check_walls(stub, host, tol=INCH)
        self.assertEqual(hit.kind, wo.CONTAINED)
        self.assertIsNone(wo.verify(hit, tol=INCH, shared=0.0,
                                    vol_a=1.0, vol_b=1.0))

    def test_verify_never_promotes_a_pair(self):
        a = wall(0, 0, 10, 0)
        b = wall(9, 0, 20, 0, key="b")
        hit = wo.check_walls(a, b, tol=INCH)
        out = wo.verify(hit, tol=INCH, shared=99.0, vol_a=1.0, vol_b=1.0)
        self.assertEqual(out.kind, wo.COLLINEAR)
