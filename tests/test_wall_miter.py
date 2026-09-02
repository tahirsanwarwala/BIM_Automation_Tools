# -*- coding: utf-8 -*-
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LIB = os.path.join(_ROOT, "Revit API", "pyRevit-Tools.extension", "lib")
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

from Tahir import wall_miter as wm


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


if __name__ == "__main__":
    unittest.main()
