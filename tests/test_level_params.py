# -*- coding: utf-8 -*-
"""The table pairing a level parameter with its offset parameter.

Re-pointing an element at another level is only safe when its offset
can absorb the change, so every entry here is a PAIR: the parameter
naming the level, and the one holding the distance from it.  Half a
pair is an element that would move, which is the one thing this feature
must never do.

The module imports Revit, so the table is read out of its source, as in
test_wall_bind_skips.  What cannot be checked here is whether a given
BuiltInParameter exists in this Revit release -- but it does not need
to be: wall_bind.bip returns None for a name the release has never
heard of, and an incomplete pair simply never matches.  A wrong name
costs an element that is skipped and reported, never one written
wrongly.
"""

import ast
import io
import os
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEVEL_PARAMS = os.path.join(
    _ROOT, "Revit API", "pyRevit-Tools.extension", "lib", "BG",
    "level_params.py")


def _source():
    with io.open(LEVEL_PARAMS, encoding="utf-8") as handle:
        return handle.read()


def _assigned(name):
    for node in ast.parse(_source()).body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return ast.literal_eval(node.value)
    raise AssertionError("{0} not found".format(name))


class TestThePairingTable(unittest.TestCase):

    def setUp(self):
        self.pairs = _assigned("PAIRS")

    def test_every_entry_is_a_pair_of_names(self):
        for entry in self.pairs:
            self.assertEqual(len(entry), 2, entry)
            for name in entry:
                self.assertTrue(name and name.isupper(), entry)

    def test_no_level_parameter_is_left_without_an_offset(self):
        # Half a pair is an element that would move when re-pointed.
        for level_name, offset_name in self.pairs:
            self.assertTrue(offset_name.strip(), level_name)

    def test_the_categories_agreed_on_are_all_covered(self):
        levels = [pair[0] for pair in self.pairs]
        for expected in ("LEVEL_PARAM",                      # floors, ceilings
                         "ROOF_BASE_LEVEL_PARAM",            # roofs
                         "FAMILY_LEVEL_PARAM",               # instances
                         "INSTANCE_REFERENCE_LEVEL_PARAM",
                         "FAMILY_BASE_LEVEL_PARAM",          # two-level
                         "STAIRS_BASE_LEVEL_PARAM",
                         "RBS_START_LEVEL_PARAM"):           # MEP
            self.assertIn(expected, levels)

    def test_floors_and_ceilings_are_told_apart_by_their_offsets(self):
        # They share LEVEL_PARAM, so the offset is the only thing that
        # distinguishes them -- and the one that does not exist on the
        # element is what makes the wrong pair fall through.
        offsets = [off for lvl, off in self.pairs if lvl == "LEVEL_PARAM"]
        self.assertIn("FLOOR_HEIGHTABOVELEVEL_PARAM", offsets)
        self.assertIn("CEILING_HEIGHTABOVELEVEL_PARAM", offsets)

    def test_walls_are_not_in_the_table(self):
        # They have their own path, which also does tops and splitting.
        self.assertNotIn("WALL_BASE_CONSTRAINT",
                         [pair[0] for pair in self.pairs])


class TestItDecidesNothing(unittest.TestCase):

    def test_the_arithmetic_is_not_copied_here(self):
        source = _source()
        for owned_elsewhere in ("def rebase", "def needs_rebase",
                                "def reference_z"):
            self.assertNotIn(owned_elsewhere, source)

    def test_it_reads_the_arithmetic_from_level_ref(self):
        self.assertIn("level_ref", _source())

    def test_a_write_is_checked_by_reading_it_back(self):
        # The feature's whole risk is moving geometry; it must prove it
        # did not rather than argue that it cannot.
        self.assertIn("def verify", _source())


class TestHostedElementsAreNotRepointed(unittest.TestCase):
    """An element placed by a host is not placed by a level.

    A curtain panel sits where its curtain grid puts it; a door sits
    where its wall puts it; a light sits where its ceiling puts it.
    Their level parameter is a label, not a placement, and a door panel
    whose label said Level 01 with an offset of -13'-0" was re-pointed
    at the basement because that label was read as a position.

    Whether the label is WRITABLE turns out not to be the test -- the
    curtain panel's was -- so having a host is.
    """

    def test_there_is_a_host_test(self):
        self.assertIn("def host_reason", _source())

    def test_the_reader_consults_it(self):
        reader = None
        for node in ast.walk(ast.parse(_source())):
            if (isinstance(node, ast.FunctionDef)
                    and node.name == "reference_of"):
                reader = node
        self.assertIsNotNone(reader, "there is no reference_of")
        self.assertIn("host_reason", ast.dump(reader),
                      "reference_of hands back a reference for a hosted "
                      "element, whose level is not where it sits")

    def test_the_extent_is_checked_against_the_reference(self):
        # The general net under the specific fix: level + offset has to
        # land somewhere near the element it claims to place.
        source = _source()
        self.assertIn("describes", source)

    def test_the_extent_rule_is_not_copied_here(self):
        self.assertNotIn("def describes", _source())


if __name__ == "__main__":
    unittest.main()
