# -*- coding: utf-8 -*-
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LIB = os.path.join(_ROOT, "Revit API", "pyRevit-Tools.extension", "lib")
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

from BG import sweep_geom as sg


class TestEdgeKey(unittest.TestCase):

    def test_same_edge_either_way_round(self):
        a = sg.edge_key((0.0, 0.0, 0.0), (10.0, 0.0, 0.0), sg.EDGE_TOL)
        b = sg.edge_key((10.0, 0.0, 0.0), (0.0, 0.0, 0.0), sg.EDGE_TOL)
        self.assertEqual(a, b)

    def test_edges_a_foot_apart_differ(self):
        a = sg.edge_key((0.0, 0.0, 0.0), (10.0, 0.0, 0.0), sg.EDGE_TOL)
        b = sg.edge_key((0.0, 1.0, 0.0), (10.0, 1.0, 0.0), sg.EDGE_TOL)
        self.assertNotEqual(a, b)


class TestEdgeKeyCandidates(unittest.TestCase):
    """A lookup must find an edge that is there, grid cell or no.

    Rounding to a grid puts two points a hair apart in DIFFERENT cells
    when they happen to straddle a cell boundary.  The index is built
    with one key; the lookup tries every key the edge could have been
    filed under, which is what makes the straddle harmless.
    """

    def test_finds_edge_within_tolerance(self):
        index = {sg.edge_key((0.0, 0.0, 0.0), (10.0, 0.0, 0.0),
                             sg.EDGE_TOL): "ref"}
        drift = sg.EDGE_TOL / 4.0
        hits = [index[k] for k
                in sg.edge_key_candidates((drift, 0.0, 0.0),
                                          (10.0 + drift, 0.0, 0.0),
                                          sg.EDGE_TOL)
                if k in index]
        self.assertEqual(hits[:1], ["ref"])

    def test_finds_edge_across_a_grid_boundary(self):
        # 1.5 cells rounds to 2, a hair under it rounds to 1, so these
        # two points really do land in different cells.  This is the
        # case edge_key_candidates exists for; without it the lookup
        # below finds nothing.
        on_boundary = sg.EDGE_TOL * 1.5
        index = {sg.edge_key((on_boundary, 0.0, 0.0), (10.0, 0.0, 0.0),
                             sg.EDGE_TOL): "ref"}
        nudged = on_boundary - sg.EDGE_TOL / 1000.0
        hits = [index[k] for k
                in sg.edge_key_candidates((nudged, 0.0, 0.0),
                                          (10.0, 0.0, 0.0), sg.EDGE_TOL)
                if k in index]
        self.assertEqual(hits[:1], ["ref"])

    def test_does_not_find_an_edge_that_is_not_there(self):
        index = {sg.edge_key((0.0, 0.0, 0.0), (10.0, 0.0, 0.0),
                             sg.EDGE_TOL): "ref"}
        hits = [k for k in sg.edge_key_candidates((0.0, 1.0, 0.0),
                                                  (10.0, 1.0, 0.0),
                                                  sg.EDGE_TOL)
                if k in index]
        self.assertEqual(hits, [])


class TestPointsAndBoxes(unittest.TestCase):

    def test_points_match_inside_tolerance(self):
        self.assertTrue(sg.points_match((0.0, 0.0, 0.0),
                                        (0.0, 0.05, 0.0), sg.ROOF_TOL))

    def test_points_do_not_match_outside_tolerance(self):
        self.assertFalse(sg.points_match((0.0, 0.0, 0.0),
                                         (0.0, 1.0, 0.0), sg.ROOF_TOL))

    def test_box_of_encloses_every_point(self):
        low, high = sg.box_of([(1.0, 2.0, 3.0), (-1.0, 5.0, 0.0),
                               (0.0, 0.0, 9.0)])
        self.assertEqual(low, (-1.0, 0.0, 0.0))
        self.assertEqual(high, (1.0, 5.0, 9.0))

    def test_box_of_nothing_is_none(self):
        self.assertIsNone(sg.box_of([]))

    def test_boxes_match_accepts_an_inch_of_drift(self):
        a = ((0.0, 0.0, 0.0), (10.0, 10.0, 10.0))
        b = ((0.05, 0.0, 0.0), (10.0, 10.05, 10.0))
        self.assertTrue(sg.boxes_match(a, b, sg.ROOF_TOL))

    def test_boxes_do_not_match_a_foot_out(self):
        a = ((0.0, 0.0, 0.0), (10.0, 10.0, 10.0))
        b = ((0.0, 0.0, 0.0), (11.0, 10.0, 10.0))
        self.assertFalse(sg.boxes_match(a, b, sg.ROOF_TOL))

    def test_boxes_do_not_match_when_one_is_missing(self):
        self.assertFalse(sg.boxes_match(
            None, ((0.0, 0.0, 0.0), (1.0, 1.0, 1.0)), sg.ROOF_TOL))

    def test_centroid_of_a_square(self):
        c = sg.centroid([(0.0, 0.0, 0.0), (2.0, 0.0, 0.0),
                         (2.0, 2.0, 0.0), (0.0, 2.0, 0.0)])
        self.assertAlmostEqual(c[0], 1.0)
        self.assertAlmostEqual(c[1], 1.0)
        self.assertAlmostEqual(c[2], 0.0)

    def test_centroid_of_nothing_is_none(self):
        self.assertIsNone(sg.centroid([]))


class TestAlreadyThere(unittest.TestCase):
    """One shared edge, same type, is proof enough.  See the spec."""

    def setUp(self):
        self.index = {("Fascia", "6 inch"): set(["edgeA", "edgeB"])}

    def test_shared_edge_and_same_type_is_already_there(self):
        self.assertTrue(sg.already_there(
            self.index, ("Fascia", "6 inch"), ["edgeB", "edgeC"]))

    def test_shared_edge_but_other_type_is_not(self):
        self.assertFalse(sg.already_there(
            self.index, ("Fascia", "8 inch"), ["edgeB"]))

    def test_same_type_but_no_shared_edge_is_not(self):
        self.assertFalse(sg.already_there(
            self.index, ("Fascia", "6 inch"), ["edgeC", "edgeD"]))

    def test_no_edges_at_all_is_not(self):
        self.assertFalse(sg.already_there(
            self.index, ("Fascia", "6 inch"), []))


if __name__ == "__main__":
    unittest.main()
