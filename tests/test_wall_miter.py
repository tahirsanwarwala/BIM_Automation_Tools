# -*- coding: utf-8 -*-
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LIB = os.path.join(_ROOT, "Revit API", "pyRevit-Tools.extension", "lib")
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

from BG import wall_miter as wm


class TestLineIntersection2D(unittest.TestCase):

    def test_perpendicular_lines_meet(self):
        p = wm.line_intersection_2d((0.0, -1.0), (1.0, 0.0),
                                    (11.0, 0.0), (0.0, 1.0))
        self.assertIsNotNone(p)
        self.assertAlmostEqual(p[0], 11.0)
        self.assertAlmostEqual(p[1], -1.0)

    def test_parallel_lines_return_none(self):
        p = wm.line_intersection_2d((0.0, 0.0), (1.0, 0.0),
                                    (0.0, 5.0), (1.0, 0.0))
        self.assertIsNone(p)

    def test_collinear_lines_return_none(self):
        p = wm.line_intersection_2d((0.0, 0.0), (1.0, 0.0),
                                    (5.0, 0.0), (1.0, 0.0))
        self.assertIsNone(p)

    def test_oblique_lines_meet(self):
        p = wm.line_intersection_2d((0.0, 0.0), (1.0, 1.0),
                                    (0.0, 4.0), (1.0, -1.0))
        self.assertAlmostEqual(p[0], 2.0)
        self.assertAlmostEqual(p[1], 2.0)


class TestMiterChain(unittest.TestCase):
    """An L-shaped chain, offset outward, must close at the corner.

    Original walls:  (0,0)->(10,0)  and  (10,0)->(10,10)
    Skin offsets  :  (0,-1)->(10,-1) and (11,0)->(11,10)
    The offset lines cross at (11,-1) -- that is the mitred corner.
    """

    ORIGINALS = [((0.0, 0.0), (10.0, 0.0)),
                 ((10.0, 0.0), (10.0, 10.0))]
    OFFSETS = [((0.0, -1.0), (10.0, -1.0)),
               ((11.0, 0.0), (11.0, 10.0))]

    def test_shared_corner_is_mitred(self):
        out = wm.miter_chain(self.ORIGINALS, self.OFFSETS)
        # wall 0's end point and wall 1's start point both move to (11,-1)
        self.assertAlmostEqual(out[0][1][0], 11.0)
        self.assertAlmostEqual(out[0][1][1], -1.0)
        self.assertAlmostEqual(out[1][0][0], 11.0)
        self.assertAlmostEqual(out[1][0][1], -1.0)

    def test_free_ends_are_untouched(self):
        out = wm.miter_chain(self.ORIGINALS, self.OFFSETS)
        self.assertAlmostEqual(out[0][0][0], 0.0)
        self.assertAlmostEqual(out[0][0][1], -1.0)
        self.assertAlmostEqual(out[1][1][0], 11.0)
        self.assertAlmostEqual(out[1][1][1], 10.0)

    def test_disconnected_walls_are_unchanged(self):
        originals = [((0.0, 0.0), (10.0, 0.0)),
                     ((50.0, 50.0), (60.0, 50.0))]
        offsets = [((0.0, -1.0), (10.0, -1.0)),
                   ((50.0, 49.0), (60.0, 49.0))]
        out = wm.miter_chain(originals, offsets)
        self.assertEqual(out, offsets)

    def test_collinear_neighbours_are_unchanged(self):
        # Two straight-on segments: no corner to mitre, lines are parallel.
        originals = [((0.0, 0.0), (10.0, 0.0)),
                     ((10.0, 0.0), (20.0, 0.0))]
        offsets = [((0.0, -1.0), (10.0, -1.0)),
                   ((10.0, -1.0), (20.0, -1.0))]
        out = wm.miter_chain(originals, offsets)
        self.assertEqual(out, offsets)

    def test_three_wall_chain_mitres_both_corners(self):
        originals = [((0.0, 0.0), (10.0, 0.0)),
                     ((10.0, 0.0), (10.0, 10.0)),
                     ((10.0, 10.0), (0.0, 10.0))]
        offsets = [((0.0, -1.0), (10.0, -1.0)),
                   ((11.0, 0.0), (11.0, 10.0)),
                   ((10.0, 11.0), (0.0, 11.0))]
        out = wm.miter_chain(originals, offsets)
        # corner A between wall 0 and 1
        self.assertAlmostEqual(out[0][1][0], 11.0)
        self.assertAlmostEqual(out[0][1][1], -1.0)
        self.assertAlmostEqual(out[1][0][0], 11.0)
        self.assertAlmostEqual(out[1][0][1], -1.0)
        # corner B between wall 1 and 2
        self.assertAlmostEqual(out[1][1][0], 11.0)
        self.assertAlmostEqual(out[1][1][1], 11.0)
        self.assertAlmostEqual(out[2][0][0], 11.0)
        self.assertAlmostEqual(out[2][0][1], 11.0)

    def test_reversed_neighbour_still_mitres(self):
        # Second wall drawn toward the shared corner rather than away from it,
        # so the coincident endpoints are 1 and 1 rather than 1 and 0.
        originals = [((0.0, 0.0), (10.0, 0.0)),
                     ((10.0, 10.0), (10.0, 0.0))]
        offsets = [((0.0, -1.0), (10.0, -1.0)),
                   ((11.0, 10.0), (11.0, 0.0))]
        out = wm.miter_chain(originals, offsets)
        self.assertAlmostEqual(out[0][1][0], 11.0)
        self.assertAlmostEqual(out[0][1][1], -1.0)
        self.assertAlmostEqual(out[1][1][0], 11.0)
        self.assertAlmostEqual(out[1][1][1], -1.0)

    def test_does_not_mutate_its_inputs(self):
        originals = [t for t in self.ORIGINALS]
        offsets = [t for t in self.OFFSETS]
        wm.miter_chain(originals, offsets)
        self.assertEqual(offsets, self.OFFSETS)


class TestTeeJunctions(unittest.TestCase):
    """A wall ending partway along another, not at its end.

    miter_chain only ever matched coincident ENDPOINTS, so a wall that
    T-ed into another's middle was left running through it.  These cover
    the trim that fixes that.
    """

    # The through wall along y = 0, and a spur running up from its middle.
    THROUGH = ((0.0, 0.0), (20.0, 0.0))
    SPUR = ((10.0, 0.0), (10.0, 8.0))

    def test_spur_end_is_pulled_onto_the_offset_of_the_through_wall(self):
        # Both offset out by 1.  The spur's offset runs up x = 11, and
        # the through wall's offset runs along y = 1, so the spur must
        # end at (11, 1) -- not at (11, 0), where it would stop a foot
        # short, nor at (11, -1), through the other wall.
        originals = [self.THROUGH, self.SPUR]
        offsets = [((0.0, 1.0), (20.0, 1.0)), ((11.0, 0.0), (11.0, 8.0))]
        out = wm.miter_chain(originals, offsets, tees=True)

        self.assertEqual(out[0], ((0.0, 1.0), (20.0, 1.0)))   # untouched
        self.assertAlmostEqual(out[1][0][0], 11.0)
        self.assertAlmostEqual(out[1][0][1], 1.0)
        self.assertEqual(out[1][1], (11.0, 8.0))              # far end kept

    def test_the_through_wall_is_never_shortened_by_a_spur(self):
        originals = [self.THROUGH, self.SPUR]
        offsets = [((0.0, 1.0), (20.0, 1.0)), ((11.0, 0.0), (11.0, 8.0))]
        out = wm.miter_chain(originals, offsets, tees=True)
        self.assertEqual(out[0], ((0.0, 1.0), (20.0, 1.0)))

    def test_a_spur_meeting_the_far_end_is_mitred_not_teed(self):
        # Touching an ENDPOINT is a corner, and both walls move.
        originals = [self.THROUGH, ((20.0, 0.0), (20.0, 8.0))]
        offsets = [((0.0, 1.0), (20.0, 1.0)), ((21.0, 0.0), (21.0, 8.0))]
        out = wm.miter_chain(originals, offsets)
        self.assertAlmostEqual(out[0][1][0], 21.0)
        self.assertAlmostEqual(out[0][1][1], 1.0)
        self.assertAlmostEqual(out[1][0][0], 21.0)
        self.assertAlmostEqual(out[1][0][1], 1.0)

    def test_a_spur_that_misses_is_left_alone(self):
        originals = [self.THROUGH, ((10.0, 3.0), (10.0, 8.0))]
        offsets = [((0.0, 1.0), (20.0, 1.0)), ((11.0, 3.0), (11.0, 8.0))]
        out = wm.miter_chain(originals, offsets)
        self.assertEqual(out[0], ((0.0, 1.0), (20.0, 1.0)))
        self.assertEqual(out[1], ((11.0, 3.0), (11.0, 8.0)))

    def test_a_spur_teeing_from_the_other_side_still_trims(self):
        originals = [self.THROUGH, ((10.0, 0.0), (10.0, -8.0))]
        offsets = [((0.0, 1.0), (20.0, 1.0)), ((9.0, 0.0), (9.0, -8.0))]
        out = wm.miter_chain(originals, offsets, tees=True)
        self.assertAlmostEqual(out[1][0][0], 9.0)
        # Approaching from below a skin that sits above: stops at the
        # centreline rather than being driven through the host wall.
        self.assertAlmostEqual(out[1][0][1], 0.0)

    def test_a_spur_teeing_by_its_far_end_trims_that_end(self):
        # Drawn away from the through wall, so it is end 1 that touches.
        originals = [self.THROUGH, ((10.0, 8.0), (10.0, 0.0))]
        offsets = [((0.0, 1.0), (20.0, 1.0)), ((11.0, 8.0), (11.0, 0.0))]
        out = wm.miter_chain(originals, offsets, tees=True)
        self.assertEqual(out[1][0], (11.0, 8.0))
        self.assertAlmostEqual(out[1][1][0], 11.0)
        self.assertAlmostEqual(out[1][1][1], 1.0)

    def test_a_colinear_spur_is_not_a_tee(self):
        # Same line: there is no intersection to trim to.
        originals = [self.THROUGH, ((10.0, 0.0), (16.0, 0.0))]
        offsets = [((0.0, 1.0), (20.0, 1.0)), ((10.0, 1.0), (16.0, 1.0))]
        out = wm.miter_chain(originals, offsets)
        self.assertEqual(out[1], ((10.0, 1.0), (16.0, 1.0)))

    def test_two_spurs_on_one_wall_each_trim_independently(self):
        originals = [self.THROUGH,
                     ((5.0, 0.0), (5.0, 8.0)),
                     ((15.0, 0.0), (15.0, 8.0))]
        offsets = [((0.0, 1.0), (20.0, 1.0)),
                   ((6.0, 0.0), (6.0, 8.0)),
                   ((16.0, 0.0), (16.0, 8.0))]
        out = wm.miter_chain(originals, offsets, tees=True)
        self.assertEqual(out[0], ((0.0, 1.0), (20.0, 1.0)))
        self.assertAlmostEqual(out[1][0][1], 1.0)
        self.assertAlmostEqual(out[2][0][1], 1.0)

    def test_an_inside_corner_shortens_both_walls(self):
        # Offsets converge, so the crossing sits back from the corner and
        # both ends must come back to it rather than running past.
        originals = [((0.0, 0.0), (10.0, 0.0)), ((10.0, 0.0), (10.0, 10.0))]
        offsets = [((0.0, -1.0), (10.0, -1.0)),
                   ((11.0, 0.0), (11.0, 10.0))]
        out = wm.miter_chain(originals, offsets)
        self.assertAlmostEqual(out[0][1][0], 11.0)
        self.assertAlmostEqual(out[0][1][1], -1.0)
        self.assertAlmostEqual(out[1][0][0], 11.0)
        self.assertAlmostEqual(out[1][0][1], -1.0)


class TestJunctionPairs(unittest.TestCase):

    def test_a_corner_is_a_pair(self):
        originals = [((0.0, 0.0), (10.0, 0.0)), ((10.0, 0.0), (10.0, 8.0))]
        self.assertEqual(wm.junction_pairs(originals), [(0, 1)])

    def test_a_tee_is_a_pair(self):
        originals = [((0.0, 0.0), (20.0, 0.0)), ((10.0, 0.0), (10.0, 8.0))]
        self.assertEqual(wm.junction_pairs(originals), [(0, 1)])

    def test_walls_that_never_meet_are_not_a_pair(self):
        originals = [((0.0, 0.0), (10.0, 0.0)), ((0.0, 5.0), (10.0, 5.0))]
        self.assertEqual(wm.junction_pairs(originals), [])

    def test_each_pair_appears_once_low_index_first(self):
        originals = [((0.0, 0.0), (10.0, 0.0)),
                     ((10.0, 0.0), (10.0, 8.0)),
                     ((10.0, 8.0), (0.0, 8.0))]
        self.assertEqual(wm.junction_pairs(originals), [(0, 1), (1, 2)])


class TestTeesAreOptIn(unittest.TestCase):
    """Tee trimming must not reach tools that never asked for it.

    wall_miter is shared. SplitWalls mitres every picked wall in one
    ungrouped call, so switching tees on by default would start trimming
    any interior wall whose end lands on an exterior wall's mid-span --
    a change nobody asked it for.
    """

    THROUGH = ((0.0, 0.0), (20.0, 0.0))
    SPUR = ((10.0, 0.0), (10.0, 8.0))
    OFFSETS = [((0.0, 1.0), (20.0, 1.0)), ((11.0, 0.0), (11.0, 8.0))]

    def test_off_by_default(self):
        out = wm.miter_chain([self.THROUGH, self.SPUR], self.OFFSETS)
        self.assertEqual(out[1], ((11.0, 0.0), (11.0, 8.0)))

    def test_on_when_asked_for(self):
        out = wm.miter_chain([self.THROUGH, self.SPUR], self.OFFSETS,
                             tees=True)
        self.assertAlmostEqual(out[1][0][1], 1.0)

    def test_corners_still_work_with_tees_off(self):
        originals = [self.THROUGH, ((20.0, 0.0), (20.0, 8.0))]
        offsets = [((0.0, 1.0), (20.0, 1.0)), ((21.0, 0.0), (21.0, 8.0))]
        out = wm.miter_chain(originals, offsets)
        self.assertAlmostEqual(out[0][1][0], 21.0)
        self.assertAlmostEqual(out[0][1][1], 1.0)


class TestTeeGuards(unittest.TestCase):

    THROUGH = ((0.0, 0.0), (20.0, 0.0))

    def test_a_spur_is_never_trimmed_through_the_wall_it_meets(self):
        # Spur runs DOWN from the through wall, whose skin is UP at
        # y = +1.  Trimming to that offset line would bury a foot of
        # spur in the host wall and push it out the far face.  The spur
        # must stop at the through wall's centreline instead.
        spur = ((10.0, 0.0), (10.0, -10.0))
        offsets = [((0.0, 1.0), (20.0, 1.0)), ((11.0, 0.0), (11.0, -10.0))]
        out = wm.miter_chain([self.THROUGH, spur], offsets, tees=True)
        self.assertAlmostEqual(out[1][0][0], 11.0)
        self.assertAlmostEqual(out[1][0][1], 0.0)

    def test_a_spur_on_the_same_side_still_reaches_the_offset(self):
        spur = ((10.0, 0.0), (10.0, 8.0))
        offsets = [((0.0, 1.0), (20.0, 1.0)), ((11.0, 0.0), (11.0, 8.0))]
        out = wm.miter_chain([self.THROUGH, spur], offsets, tees=True)
        self.assertAlmostEqual(out[1][0][1], 1.0)

    def test_a_shallow_tee_is_left_alone(self):
        # Two degrees off parallel: the offset lines cross 57 ft away.
        # That is a wall running alongside another, not into it.
        import math
        angle = math.radians(2.0)
        far = (10.0 + 30.0 * math.cos(angle), 30.0 * math.sin(angle))
        spur = ((10.0, 0.0), far)
        offsets = [((0.0, 1.0), (20.0, 1.0)),
                   ((10.0, 1.0), (far[0], far[1] + 1.0))]
        out = wm.miter_chain([self.THROUGH, spur], offsets, tees=True)
        self.assertEqual(out[1][0], (10.0, 1.0))

    def test_a_square_tee_is_well_inside_the_angle_guard(self):
        spur = ((10.0, 0.0), (10.0, 8.0))
        offsets = [((0.0, 1.0), (20.0, 1.0)), ((11.0, 0.0), (11.0, 8.0))]
        out = wm.miter_chain([self.THROUGH, spur], offsets, tees=True)
        self.assertAlmostEqual(out[1][0][1], 1.0)

    def test_a_forty_five_degree_tee_still_trims(self):
        spur = ((10.0, 0.0), (18.0, 8.0))
        offsets = [((0.0, 1.0), (20.0, 1.0)), ((10.0, 0.0), (18.0, 8.0))]
        out = wm.miter_chain([self.THROUGH, spur], offsets, tees=True)
        self.assertAlmostEqual(out[1][0][1], 1.0)
        self.assertAlmostEqual(out[1][0][0], 11.0)


class TestTeeReach(unittest.TestCase):
    """A wall modelled to the through wall's FACE, not its centreline."""

    THROUGH = ((0.0, 0.0), (20.0, 0.0))

    def test_a_spur_stopping_short_is_missed_at_the_default_tolerance(self):
        spur = ((10.0, 0.4), (10.0, 8.0))
        offsets = [((0.0, 1.0), (20.0, 1.0)), ((11.0, 0.4), (11.0, 8.0))]
        out = wm.miter_chain([self.THROUGH, spur], offsets, tees=True)
        self.assertEqual(out[1][0], (11.0, 0.4))

    def test_a_wider_reach_catches_it(self):
        spur = ((10.0, 0.4), (10.0, 8.0))
        offsets = [((0.0, 1.0), (20.0, 1.0)), ((11.0, 0.4), (11.0, 8.0))]
        out = wm.miter_chain([self.THROUGH, spur], offsets,
                             tees=True, tee_reach=0.6)
        self.assertAlmostEqual(out[1][0][1], 1.0)

    def test_reach_does_not_drag_in_a_wall_that_is_simply_far_away(self):
        spur = ((10.0, 3.0), (10.0, 8.0))
        offsets = [((0.0, 1.0), (20.0, 1.0)), ((11.0, 3.0), (11.0, 8.0))]
        out = wm.miter_chain([self.THROUGH, spur], offsets,
                             tees=True, tee_reach=0.6)
        self.assertEqual(out[1][0], (11.0, 3.0))

    def test_junction_pairs_takes_the_same_reach(self):
        spur = ((10.0, 0.4), (10.0, 8.0))
        self.assertEqual(wm.junction_pairs([self.THROUGH, spur]), [])
        self.assertEqual(
            wm.junction_pairs([self.THROUGH, spur], tee_reach=0.6),
            [(0, 1)])


class TestSegmentsMeet(unittest.TestCase):
    """Do two finished wall centrelines actually touch?

    Joining is what produced "elements joined but do not intersect":
    junction_pairs reports a junction on the SOURCE centrelines, which
    is right for deciding what to mitre, but says nothing about whether
    the finished walls ended up touching.  This is the test for that.
    """

    def test_shared_endpoint_meets(self):
        a = ((0.0, 0.0), (10.0, 0.0))
        b = ((10.0, 0.0), (10.0, 8.0))
        self.assertTrue(wm.segments_meet(a, b))

    def test_endpoints_a_hair_apart_meet(self):
        a = ((0.0, 0.0), (10.0, 0.0))
        b = ((10.0 + 0.5 * wm.TOL_JOIN, 0.0), (10.0, 8.0))
        self.assertTrue(wm.segments_meet(a, b))

    def test_a_visible_gap_does_not_meet(self):
        # The coping corner: both walls stopped short of the corner.
        a = ((0.0, 0.0), (9.0, 0.0))
        b = ((10.0, 1.0), (10.0, 8.0))
        self.assertFalse(wm.segments_meet(a, b))

    def test_crossing_segments_meet(self):
        a = ((0.0, 0.0), (10.0, 0.0))
        b = ((5.0, -5.0), (5.0, 5.0))
        self.assertTrue(wm.segments_meet(a, b))

    def test_a_tee_landing_on_the_middle_meets(self):
        a = ((0.0, 0.0), (20.0, 0.0))
        b = ((10.0, 0.0), (10.0, 8.0))
        self.assertTrue(wm.segments_meet(a, b))

    def test_parallel_apart_do_not_meet(self):
        a = ((0.0, 0.0), (10.0, 0.0))
        b = ((0.0, 3.0), (10.0, 3.0))
        self.assertFalse(wm.segments_meet(a, b))

    def test_colinear_abutting_meet(self):
        a = ((0.0, 0.0), (10.0, 0.0))
        b = ((10.0, 0.0), (20.0, 0.0))
        self.assertTrue(wm.segments_meet(a, b))

    def test_lines_that_would_cross_beyond_their_ends_do_not_meet(self):
        # The infinite lines cross at (10, 0); neither segment reaches.
        a = ((0.0, 0.0), (5.0, 0.0))
        b = ((10.0, 3.0), (10.0, 8.0))
        self.assertFalse(wm.segments_meet(a, b))

    def test_a_degenerate_segment_does_not_meet(self):
        a = ((5.0, 5.0), (5.0, 5.0))
        b = ((0.0, 0.0), (10.0, 0.0))
        self.assertFalse(wm.segments_meet(a, b))


class TestMitreTolerance(unittest.TestCase):
    """An obtuse corner where both runs stop short of it.

    A sweep is mitred back from a corner by roughly how far it stands
    off the wall, so the two runs measured off its solid do not reach
    the corner and their ends are nowhere near each other.  At the
    default 1/64 inch no corner is seen and both walls are built short
    -- which is the coping corner that was still failing.
    """

    # Ends a foot short of the corner at (10, 0).
    A = ((0.0, 0.0), (9.0, 0.0))
    B = ((10.0, 1.0), (10.0, 9.0))
    OFFSETS = [((0.0, -1.0), (9.0, -1.0)), ((11.0, 1.0), (11.0, 9.0))]

    def test_default_tolerance_sees_no_corner(self):
        out = wm.miter_chain([self.A, self.B], self.OFFSETS)
        self.assertEqual(out[0], ((0.0, -1.0), (9.0, -1.0)))

    def test_a_tolerance_at_the_scale_of_the_shortfall_mitres_it(self):
        out = wm.miter_chain([self.A, self.B], self.OFFSETS, tol=2.0)
        # Both ends land on where the two offset lines cross.
        self.assertAlmostEqual(out[0][1][0], 11.0)
        self.assertAlmostEqual(out[0][1][1], -1.0)
        self.assertAlmostEqual(out[1][0][0], 11.0)
        self.assertAlmostEqual(out[1][0][1], -1.0)

    def test_the_far_ends_are_left_alone(self):
        out = wm.miter_chain([self.A, self.B], self.OFFSETS, tol=2.0)
        self.assertEqual(out[0][0], (0.0, -1.0))
        self.assertEqual(out[1][1], (11.0, 9.0))


if __name__ == "__main__":
    unittest.main()
