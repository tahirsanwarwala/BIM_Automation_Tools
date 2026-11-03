# -*- coding: utf-8 -*-
"""The plain-Python half of Element To Mass.

Element To Mass turns one element into a conceptual mass standing where
the element stands, built from its finished solid geometry.  Reading
that geometry is Revit work and lives in mass_build.  What is left over
-- what the family is called and what the report says -- is here.

Deliberately free of any Revit import so it can be unit-tested outside
Revit.
"""

import re

MASS_SUFFIX = "_Mass"
FALLBACK_NAME = "Element"

# Cubic feet.  A solid smaller than this is a sliver, not a piece of
# the element.
VOLUME_EPS = 1e-6

# Feet.  A placed mass further than this from where it was meant to go
# is moved there.
PLACE_TOL = 1e-4

SHOW_MASS_NOTE = ("Masses show only where the Mass category is visible -- "
                  "turn on Show Mass if you cannot see it.")

# The characters Revit refuses in a family name.
_REFUSED = re.compile(r'[\\:{}\[\]|;<>?`~]')


def family_base_name(source_name):
    """'<source>_Mass', with the characters Revit refuses replaced by '_'."""
    cleaned = _REFUSED.sub("_", source_name or "").strip()
    return (cleaned or FALLBACK_NAME) + MASS_SUFFIX


def unique_name(base, taken):
    """base, or base_2, base_3 ... -- the first one not in taken."""
    name, n = base, 1
    while name in taken:
        n += 1
        name = "{}_{}".format(base, n)
    return name


def report_lines(results):
    """The closing report, one markdown line per element.

    results -- one dict per element: source (str), family (str, or None
               when no mass was made), solids (int), notes (list of str).
    """
    made = [r for r in results if r.get("family")]
    lines = ["Made {} mass(es) from {} element(s).".format(
        len(made), len(results))]
    for r in results:
        notes = "; ".join(r.get("notes", []))
        if r.get("family"):
            line = "- **{}** from {}: {} solid piece(s)".format(
                r["family"], r["source"], r["solids"])
            if notes:
                line += " -- {}".format(notes)
        else:
            line = "- {}: not made -- {}".format(
                r["source"], notes or "no reason given")
        lines.append(line)
    if made:
        lines.append(SHOW_MASS_NOTE)
    return lines
