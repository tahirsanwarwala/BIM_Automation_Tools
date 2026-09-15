# -*- coding: utf-8 -*-
"""The Wall Limits report's status vocabularies must line up.

The tool keeps two of them for the BG_LEVEL pass: the OUTCOMES that
wall_bind.set_bg_level returns ("written", "missing", ...) and the
STATUSES the report prints ("Level written", "Not applicable", ...).
ELEMENT_OUTCOMES maps one to the other and ELEMENT_QUIET_STATUSES says
which of the printed ones to keep quiet about.

Looking a status up in the outcome table -- or misspelling one of the
quiet statuses -- does not raise.  It silently reports every element,
including the hundreds that were written exactly as asked, which is the
one thing this report is supposed to stay quiet about.

The script imports Revit, so the two collections are read out of its
source rather than imported.
"""

import ast
import io
import os
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPT = os.path.join(
    _ROOT, "Revit API", "pyRevit-Tools.extension", "BG_Tools.tab",
    "SKIN_Tools.panel", "Walls.stack", "WallConstraints.pushbutton",
    "script.py")

FAILED = "Failed"


def _tree():
    with io.open(_SCRIPT, encoding="utf-8") as handle:
        return ast.parse(handle.read())


def _key(node):
    """A dict key as text.  The tables are keyed by wall_bind.BG_* names."""
    if isinstance(node, ast.Attribute):
        return node.attr
    return ast.literal_eval(node)


def _literal_or_none(node):
    """A dict value, or None when it is built at run time.

    ELEMENT_REASONS interpolates the parameter name into its messages,
    so those values are calls rather than constants.  Only the keys of
    that table are under test.
    """
    try:
        return ast.literal_eval(node)
    except Exception:
        return None


def _assigned(name):
    """The value of a module-level assignment, as a Python object."""
    for node in _tree().body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == name:
                value = node.value
                if isinstance(value, ast.Dict):
                    return dict(
                        (_key(k), _literal_or_none(v))
                        for k, v in zip(value.keys, value.values))
                if isinstance(value, ast.Call):
                    value = value.args[0]
                return [ast.literal_eval(e) for e in value.elts]
    raise AssertionError("{0} not found in the script".format(name))


class TestElementStatusVocabularies(unittest.TestCase):

    def setUp(self):
        self.outcomes = _assigned("ELEMENT_OUTCOMES")
        self.quiet = _assigned("ELEMENT_QUIET_STATUSES")
        self.reasons = _assigned("ELEMENT_REASONS")

    def test_both_collections_are_present(self):
        self.assertTrue(self.outcomes)
        self.assertTrue(self.quiet)

    def test_every_printed_status_is_either_quiet_or_a_failure(self):
        # Anything else would be a status the report has no policy for.
        unclassified = sorted(set(
            s for s in self.outcomes.values()
            if s not in self.quiet and s != FAILED))
        self.assertEqual(
            unclassified, [],
            "these statuses are neither quiet nor Failed, so whether they "
            "print is an accident")

    def test_every_quiet_status_is_actually_produced(self):
        # A misspelled quiet status silently starts reporting its rows.
        produced = set(self.outcomes.values())
        orphans = sorted(s for s in self.quiet if s not in produced)
        self.assertEqual(
            orphans, [],
            "these are kept quiet but no outcome produces them - check the "
            "spelling against ELEMENT_OUTCOMES")

    def test_a_failure_is_never_quiet(self):
        self.assertNotIn(FAILED, self.quiet)

    def test_the_success_and_skip_statuses_are_quiet(self):
        # The three the user asked never to hear about.
        for status in ("Level written", "Already correct", "Not applicable"):
            self.assertIn(status, self.quiet)
            self.assertIn(status, set(self.outcomes.values()))

    def test_written_and_already_are_not_failures(self):
        self.assertNotEqual(self.outcomes["BG_WRITTEN"], FAILED)
        self.assertNotEqual(self.outcomes["BG_ALREADY"], FAILED)

    def test_the_three_real_failures_are_failures(self):
        for key in ("BG_READONLY", "BG_NOT_TEXT", "BG_REFUSED"):
            self.assertEqual(self.outcomes[key], FAILED)

    def test_missing_and_no_level_are_not_failures(self):
        # An element that never had the parameter is not an error.
        for key in ("BG_MISSING", "BG_NO_LEVEL"):
            self.assertNotEqual(self.outcomes[key], FAILED)
            self.assertIn(self.outcomes[key], self.quiet)

    def test_every_outcome_has_a_status(self):
        expected = ("BG_WRITTEN", "BG_ALREADY", "BG_MISSING", "BG_NO_LEVEL",
                    "BG_READONLY", "BG_NOT_TEXT", "BG_REFUSED")
        self.assertEqual(sorted(self.outcomes), sorted(expected))

    def test_every_reason_belongs_to_a_known_outcome(self):
        strays = sorted(k for k in self.reasons if k not in self.outcomes)
        self.assertEqual(strays, [], "a reason for an outcome that cannot "
                                     "happen is never printed")

    def test_every_failure_carries_a_reason(self):
        # process_element only notes a reason when the status is Failed,
        # so a failure without one prints an empty Notes cell.
        for key in ("BG_READONLY", "BG_NOT_TEXT", "BG_REFUSED"):
            self.assertIn(key, self.reasons)


class TestWallQuietStatuses(unittest.TestCase):

    def setUp(self):
        self.quiet = _assigned("QUIET_STATUSES")

    def test_the_wall_pass_stays_quiet_when_it_worked(self):
        for status in ("Fixed", "Already correct"):
            self.assertIn(status, self.quiet)

    def test_nothing_needing_attention_is_quiet(self):
        for status in ("Failed", "Not split", "Skipped", "To Check",
                       "Needs split"):
            self.assertNotIn(status, self.quiet)



def _function(name):
    """The ast node of a top-level function in the script."""
    for node in ast.walk(_tree()):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError("{0} not found in the script".format(name))


SKIP_STATUSES = ("Skipped", "Not applicable")


def _sets_a_skip_status(body):
    """True when a statement list directly sets res.status to a skip."""
    for statement in body:
        if not isinstance(statement, ast.Assign):
            continue
        if not any(isinstance(t, ast.Attribute) and t.attr == "status"
                   for t in statement.targets):
            continue
        # Either a plain string or the "quiet if ... else Skipped" form.
        candidates = [statement.value]
        if isinstance(statement.value, ast.IfExp):
            candidates = [statement.value.body, statement.value.orelse]
        for candidate in candidates:
            try:
                if ast.literal_eval(candidate) in SKIP_STATUSES:
                    return True
            except Exception:
                continue
    return False


def _returns(body):
    return any(isinstance(s, ast.Return) for s in body)


def _calls(body, name):
    for statement in body:
        for node in ast.walk(statement):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == name):
                return True
    return False


class TestSkippedWallsStillGetBgLevel(unittest.TestCase):
    """A wall the tool declines to change must still get BG_LEVEL.

    Refusing to touch a wall's CONSTRAINTS is not a reason to leave the
    parameter empty -- it records only the storey the wall already sits
    on.  Each refusal in _process_wall is its own early return, so it is
    easy to add a new one and silently reintroduce exactly the gap this
    guards: skipped walls skipping the parameter too.
    """

    WRITER = "bg_level_from_wall"

    def setUp(self):
        self.func = _function("_process_wall")
        self.blocks = []
        for node in ast.walk(self.func):
            for field in ("body", "orelse", "finalbody"):
                body = getattr(node, field, None)
                if not isinstance(body, list):
                    continue
                if _sets_a_skip_status(body) and _returns(body):
                    self.blocks.append(body)

    def test_the_skip_returns_are_found_at_all(self):
        # If this drops to zero the rest of the class proves nothing.
        self.assertGreaterEqual(len(self.blocks), 3)

    def test_every_skip_return_writes_bg_level_first(self):
        missing = [i for i, b in enumerate(self.blocks)
                   if not _calls(b, self.WRITER)]
        self.assertEqual(
            missing, [],
            "{0} of {1} skip paths in _process_wall return without calling "
            "{2}, so those walls get no {3}".format(
                len(missing), len(self.blocks), self.WRITER,
                "BG_LEVEL"))

    def test_the_writer_reads_the_base_constraint(self):
        writer = _function(self.WRITER)
        self.assertTrue(
            _calls(writer.body, "base_constraint_level_id"),
            "{0} must take the level from the wall's own Base "
            "Constraint".format(self.WRITER))

    def test_the_base_constraint_reader_asks_for_that_parameter(self):
        reader = _function("base_constraint_level_id")
        names = [n.attr for n in ast.walk(reader)
                 if isinstance(n, ast.Attribute)]
        self.assertIn("WALL_BASE_CONSTRAINT", names)


if __name__ == "__main__":
    unittest.main()
