# -*- coding: utf-8 -*-
"""The two skip lists in BG.wall_bind must describe the same parameters.

copy_instance_params keeps a wall's vertical constraints from being
cloned onto another wall.  It matches on BuiltInParameter, and falls
back to matching on the parameter's display name when Revit will not
hand a Definition its BuiltInParameter -- which it does by throwing,
not by returning INVALID.

A BuiltInParameter listed without its display name therefore has a hole
in it: the fallback copies the parameter the list exists to keep out.
Writing a source wall's Top Constraint onto a band that sits above it
makes a wall whose top is below its base, which Revit posts at commit
as an error it will not let anyone ignore.

wall_bind imports Revit, so it cannot be imported here.  The lists are
read out of its source instead.
"""

import ast
import io
import os
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_WALL_BIND = os.path.join(
    _ROOT, "Revit API", "pyRevit-Tools.extension", "lib", "BG", "wall_bind.py")

# What Revit calls each of the parameters wall_bind refuses to copy.
DISPLAY_NAME = {
    "WALL_BASE_CONSTRAINT":       "Base Constraint",
    "WALL_BASE_OFFSET":           "Base Offset",
    "WALL_HEIGHT_TYPE":           "Top Constraint",
    "WALL_TOP_OFFSET":            "Top Offset",
    "WALL_USER_HEIGHT_PARAM":     "Unconnected Height",
    "WALL_BOTTOM_IS_ATTACHED":    "Base is Attached",
    "WALL_TOP_IS_ATTACHED":       "Top is Attached",
    "WALL_KEY_REF_PARAM":         "Location Line",
    "ELEM_FAMILY_PARAM":          "Family",
    "ELEM_TYPE_PARAM":            "Type",
    "ELEM_FAMILY_AND_TYPE_PARAM": "Family and Type",
    "ALL_MODEL_MARK":             "Mark",
}


def _literal(module_name):
    """The value of a module-level string-collection assignment."""
    with io.open(_WALL_BIND, encoding="utf-8") as handle:
        tree = ast.parse(handle.read())
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == module_name:
                value = node.value
                # frozenset((...)) / set((...)) wrap the literal.
                if isinstance(value, ast.Call):
                    value = value.args[0]
                return [ast.literal_eval(e) for e in value.elts]
    raise AssertionError("{0} not found in wall_bind".format(module_name))


class TestSkipListsAgree(unittest.TestCase):

    def setUp(self):
        self.bip_names = _literal("SKIP_BIP_NAMES")
        self.param_names = _literal("SKIP_PARAM_NAMES")

    def test_both_lists_are_present_and_not_empty(self):
        self.assertTrue(self.bip_names)
        self.assertTrue(self.param_names)

    def test_every_builtin_parameter_is_also_skipped_by_name(self):
        missing = [
            "{0} ({1})".format(n, DISPLAY_NAME.get(n, "display name unknown"))
            for n in self.bip_names
            if DISPLAY_NAME.get(n) not in self.param_names
        ]
        self.assertEqual(
            missing, [],
            "these BuiltInParameters are skipped by id but not by name, so "
            "the name fallback in copy_instance_params would copy them")

    def test_the_test_knows_a_display_name_for_every_entry(self):
        unknown = [n for n in self.bip_names if n not in DISPLAY_NAME]
        self.assertEqual(
            unknown, [],
            "add these to DISPLAY_NAME so the check above can cover them")

    def test_no_name_is_skipped_without_a_reason_to_be(self):
        expected = set(DISPLAY_NAME[n] for n in self.bip_names)
        self.assertEqual(set(self.param_names), expected)

    def test_the_vertical_constraints_are_all_covered(self):
        # The four that actually invert a wall when copied.
        for name in ("Base Constraint", "Base Offset",
                     "Top Constraint", "Top Offset"):
            self.assertIn(name, self.param_names)



class TestLevelLookupIsBaseOnly(unittest.TestCase):
    """base_level_id must never answer with a TOP level.

    An element's BG_LEVEL is the storey it belongs to, and for anything
    spanning two levels that is the lower one.  Both lists it consults
    resolve their entries to a Level, so a top-constraint or upper-limit
    entry would resolve just as happily and put the wrong storey in the
    parameter -- on a wall, the one above the one its own constraints
    were just corrected to.
    """

    FORBIDDEN = ("top", "upper", "head", "roof_level", "unconnected")

    def setUp(self):
        self.bip_names = _literal("LEVEL_BIP_NAMES")
        self.param_names = _literal("LEVEL_PARAM_NAMES")

    def test_both_lists_are_present_and_not_empty(self):
        self.assertTrue(self.bip_names)
        self.assertTrue(self.param_names)

    def test_no_builtin_parameter_names_a_top(self):
        offenders = [n for n in self.bip_names
                     if any(bad in n.lower() for bad in self.FORBIDDEN)]
        self.assertEqual(
            offenders, [],
            "these name a top or upper level, which is not the storey an "
            "element belongs to")

    def test_no_parameter_name_names_a_top(self):
        offenders = [n for n in self.param_names
                     if any(bad in n.lower() for bad in self.FORBIDDEN)]
        self.assertEqual(offenders, [], "same, for the name fallback")

    def test_parameter_names_are_lowercase(self):
        # base_level_id lowercases the parameter it reads before
        # comparing, so an entry with a capital could never match.
        self.assertEqual(self.param_names,
                         [n.lower() for n in self.param_names])

    def test_parameter_names_are_stripped(self):
        self.assertEqual(self.param_names, [n.strip() for n in self.param_names])

    def test_the_wall_base_constraint_is_consulted(self):
        # A wall reaching base_level_id should answer from its own base
        # constraint, not fall through to a generic guess.
        self.assertIn("WALL_BASE_CONSTRAINT", self.bip_names)


class TestBgOutcomesAreDistinct(unittest.TestCase):
    """The BG_* outcome constants must not collide.

    The script maps each to a status and a reason; two sharing a value
    would silently take the other's row.
    """

    NAMES = ("BG_WRITTEN", "BG_ALREADY", "BG_NO_LEVEL", "BG_MISSING",
             "BG_READONLY", "BG_NOT_TEXT", "BG_REFUSED")

    def test_every_outcome_is_defined_and_unique(self):
        with io.open(_WALL_BIND, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())

        values = {}
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in self.NAMES:
                    values[target.id] = ast.literal_eval(node.value)

        self.assertEqual(sorted(values), sorted(self.NAMES))
        self.assertEqual(len(set(values.values())), len(self.NAMES),
                         "two outcomes share a value: {0}".format(values))


if __name__ == "__main__":
    unittest.main()
