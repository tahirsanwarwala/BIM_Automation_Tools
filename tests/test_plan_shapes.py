# -*- coding: utf-8 -*-
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LIB = os.path.join(_ROOT, "Revit API", "pyRevit-Tools.extension", "lib")
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

from Tahir import plan_shapes as ps


SQUARE = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]

# An L, cut out of the top right of a 10 x 10 square.
ELL = [(0.0, 0.0), (10.0, 0.0), (10.0, 4.0),
       (4.0, 4.0), (4.0, 10.0), (0.0, 10.0)]

# A 2 x 2 hole in the middle of SQUARE.
HOLE = [(4.0, 4.0), (6.0, 4.0), (6.0, 6.0), (4.0, 6.0)]


class TestPointInRing(unittest.TestCase):

    def test_centre_is_inside(self):
        self.assertTrue(ps.point_in_ring((5.0, 5.0), SQUARE))

    def test_far_outside(self):
        self.assertFalse(ps.point_in_ring((20.0, 5.0), SQUARE))

    def test_just_outside(self):
        self.assertFalse(ps.point_in_ring((10.5, 5.0), SQUARE))

    def test_on_an_edge_counts_as_inside(self):
        self.assertTrue(ps.point_in_ring((10.0, 5.0), SQUARE))

    def test_on_a_corner_counts_as_inside(self):
        self.assertTrue(ps.point_in_ring((0.0, 0.0), SQUARE))

    def test_notch_of_an_ell_is_outside(self):
        self.assertFalse(ps.point_in_ring((7.0, 7.0), ELL))

    def test_leg_of_an_ell_is_inside(self):
        self.assertTrue(ps.point_in_ring((2.0, 7.0), ELL))

    def test_ray_through_a_vertex_is_not_counted_twice(self):
        # A ray cast east from here grazes the vertex at (4, 4).
        self.assertTrue(ps.point_in_ring((1.0, 4.0), ELL))

    def test_degenerate_ring_is_never_inside(self):
        self.assertFalse(ps.point_in_ring((0.0, 0.0), [(1.0, 1.0)]))


class TestSegmentsCross(unittest.TestCase):

    def test_an_x_crosses(self):
        self.assertTrue(ps.segments_cross((0.0, 0.0), (10.0, 10.0),
                                          (0.0, 10.0), (10.0, 0.0)))

    def test_apart_does_not(self):
        self.assertFalse(ps.segments_cross((0.0, 0.0), (1.0, 0.0),
                                           (5.0, 5.0), (6.0, 5.0)))

    def test_parallel_does_not(self):
        self.assertFalse(ps.segments_cross((0.0, 0.0), (10.0, 0.0),
                                           (0.0, 1.0), (10.0, 1.0)))

    def test_touching_at_an_end_crosses(self):
        self.assertTrue(ps.segments_cross((0.0, 0.0), (5.0, 0.0),
                                          (5.0, 0.0), (5.0, 5.0)))

    def test_extensions_meeting_do_not_cross(self):
        self.assertFalse(ps.segments_cross((0.0, 0.0), (1.0, 0.0),
                                           (5.0, -5.0), (5.0, 5.0)))


class TestSegmentRingDistance(unittest.TestCase):

    def test_a_segment_clear_of_the_ring(self):
        d = ps.segment_ring_distance((13.0, 0.0), (13.0, 10.0), SQUARE)
        self.assertAlmostEqual(d, 3.0)

    def test_a_segment_touching_the_ring_is_zero(self):
        d = ps.segment_ring_distance((10.0, 2.0), (14.0, 2.0), SQUARE)
        self.assertAlmostEqual(d, 0.0)

    def test_distance_to_a_corner(self):
        d = ps.segment_ring_distance((13.0, 14.0), (13.0, 20.0), SQUARE)
        self.assertAlmostEqual(d, 5.0)


class TestSegmentMeetsOutline(unittest.TestCase):

    def test_a_segment_wholly_inside(self):
        self.assertTrue(ps.segment_meets_outline(
            (2.0, 5.0), (8.0, 5.0), SQUARE))

    def test_a_segment_wholly_outside(self):
        self.assertFalse(ps.segment_meets_outline(
            (20.0, 0.0), (20.0, 10.0), SQUARE))

    def test_a_segment_crossing_the_edge(self):
        self.assertTrue(ps.segment_meets_outline(
            (5.0, 5.0), (20.0, 5.0), SQUARE))

    def test_a_segment_passing_clean_through(self):
        self.assertTrue(ps.segment_meets_outline(
            (-5.0, 5.0), (20.0, 5.0), SQUARE))

    def test_a_segment_in_the_notch_of_an_ell(self):
        self.assertFalse(ps.segment_meets_outline(
            (5.0, 6.0), (9.0, 9.0), ELL))

    def test_a_segment_inside_a_hole(self):
        self.assertFalse(ps.segment_meets_outline(
            (4.5, 5.0), (5.5, 5.0), SQUARE, [HOLE]))

    def test_a_segment_leaving_a_hole(self):
        self.assertTrue(ps.segment_meets_outline(
            (5.0, 5.0), (9.0, 5.0), SQUARE, [HOLE]))

    def test_a_segment_inside_but_clear_of_the_hole(self):
        self.assertTrue(ps.segment_meets_outline(
            (1.0, 1.0), (2.0, 1.0), SQUARE, [HOLE]))

    def test_reach_pulls_in_a_segment_alongside(self):
        self.assertFalse(ps.segment_meets_outline(
            (10.25, 0.0), (10.25, 10.0), SQUARE))
        self.assertTrue(ps.segment_meets_outline(
            (10.25, 0.0), (10.25, 10.0), SQUARE, reach=0.5))

    def test_reach_does_not_reach_far_enough(self):
        self.assertFalse(ps.segment_meets_outline(
            (13.0, 0.0), (13.0, 10.0), SQUARE, reach=0.5))

    def test_reach_does_not_resurrect_a_segment_in_a_hole(self):
        # Dead centre of the hole, half an inch of reach: still nothing.
        self.assertFalse(ps.segment_meets_outline(
            (4.9, 5.0), (5.1, 5.0), SQUARE, [HOLE], reach=1.0 / 24.0))


class TestBboxRing(unittest.TestCase):

    def test_a_cloud_becomes_its_rectangle(self):
        ring = ps.bbox_ring([(1.0, 2.0), (5.0, 2.0), (3.0, 7.0)])
        self.assertEqual(ring, [(1.0, 2.0), (5.0, 2.0),
                                (5.0, 7.0), (1.0, 7.0)])

    def test_no_points_gives_nothing(self):
        self.assertIsNone(ps.bbox_ring([]))

    def test_a_degenerate_cloud_gives_nothing(self):
        self.assertIsNone(ps.bbox_ring([(1.0, 1.0), (1.0, 1.0)]))


if __name__ == "__main__":
    unittest.main()
