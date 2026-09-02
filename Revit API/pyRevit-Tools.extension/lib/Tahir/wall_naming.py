# -*- coding: utf-8 -*-
"""Naming rules for generated SKIN wall types.

Type names take the form:

    SKIN_<WALL TYPE>_<FINISH MATERIAL>_<THICKNESS>

for example:

    SKIN_BRICK_COMMON BOND (FNS-B4)_0' 3 5/8"

The thickness is part of the name on purpose.  Wall types are reused by
name, so two skins of the same material at different thicknesses must not
collapse onto one type -- the second would silently inherit the first
one's thickness.

Deliberately free of any Revit import so it can be unit-tested outside
Revit.
"""

import re

MATERIAL_SEPARATOR = " - "

# Generated materials and wall types both start with this.
SKIN_PREFIX = "SKIN_"

# A trailing library code in brackets, e.g. the '(FNS-B4)' in
# 'Common Bond (FNS-B4)'.  Dropped from generated descriptors because the
# code already appears as the Mark segment of the name.
_TRAILING_CODE_RE = re.compile(r'\s*\([A-Za-z]{2,}-[A-Za-z0-9]+\)\s*$')

# The thickness token at the end of a wall type name, e.g. the
# '_0\' 3 5/8"' in 'SKIN_FNS-B4_COMMON BOND_0\' 3 5/8"'.
_THICKNESS_TOKEN_RE = re.compile(r'_\d+\'[^_]*"\s*$')


def _gcd(a, b):
    """Greatest common divisor (integer)."""
    while b:
        a, b = b, a % b
    return a


def feet_to_imperial(feet):
    """Convert feet (float) to a feet-inches string, always showing feet.

    Examples:  0.666667 ft  ->  '0\' 8"'
               0.302083 ft  ->  '0\' 3 5/8"'
               1.5      ft  ->  '1\' 6"'
    """
    total_inches = abs(feet) * 12.0
    sixteenths   = int(round(total_inches * 16))

    ft_part   = sixteenths // (16 * 12)
    leftover  = sixteenths - ft_part * 16 * 12
    whole_in  = leftover // 16
    remainder = leftover % 16

    if remainder == 0:
        return "{}' {}\"".format(ft_part, whole_in)

    g   = _gcd(remainder, 16)
    num = remainder // g
    den = 16 // g

    if whole_in == 0:
        return "{}' {}/{}\"".format(ft_part, num, den)
    return "{}' {} {}/{}\"".format(ft_part, whole_in, num, den)


def short_material_code(material_name):
    """Shorten a library material name to its distinguishing tail.

    Library names are structured as a series of ' - ' separated parts,
    with the part that actually identifies the finish coming last:

        '_ST-03 - Masonry - Brick - Common Bond (FNS-B4)'
            ->  'COMMON BOND (FNS-B4)'
        '_ST-05 - Large Format'
            ->  'LARGE FORMAT'

    The whole tail is kept rather than just the bracketed code, because
    codes are not unique -- 'Soldier Course (FNS-B3)' and 'Soldier Course
    (FNS-B3)(sides)' are different materials sharing one code -- and some
    materials carry no code at all.
    """
    if not material_name:
        return "UNKNOWN"

    tail = material_name.split(MATERIAL_SEPARATOR)[-1].strip()
    if not tail:
        return "UNKNOWN"
    return tail.upper()


def extract_type_tag(wall_type_name):
    """Reduce a wall type name to the material family it describes.

    Examples:
      'Exterior - Brick_Insul_6" Stud_Gyp'  -> 'BRICK'
      'Exterior - Adhered Stone_CMU_Stone'  -> 'ADHERED STONE'
      'Exterior - 12" Concrete'             -> '12" CONCRETE'
    """
    if not wall_type_name:
        return "UNKNOWN"

    s = wall_type_name.strip()
    if s.lower().startswith("exterior"):
        dash_idx = s.find("-")
        if dash_idx != -1:
            s = s[dash_idx + 1:].strip()
        else:
            s = s[8:].strip()

    if "_" in s:
        s = s.split("_")[0].strip()

    return s.upper()


def skin_type_name(type_tag, material_short, thickness_text):
    """Assemble the full SKIN wall type name."""
    return "SKIN_{}_{}_{}".format(
        (type_tag or "UNKNOWN").upper(),
        (material_short or "UNKNOWN").upper(),
        thickness_text,
    )


# ---------------------------------------------------------------------------
# Mark-based naming
#
# Generated names are keyed on the source material's Mark rather than on any
# part of its name:
#
#     material   SKIN_<MARK> - <Descriptor>
#     wall type  SKIN_<MARK>_<DESCRIPTOR>_<THICKNESS>
#
# e.g. a linked material '_ST-03 - Masonry - Brick - Soldier Course (FNS-B4)'
# marked 'FNS-B4' gives 'SKIN_FNS-B4 - Soldier Course' and
# 'SKIN_FNS-B4_SOLDIER COURSE_0\' 3 5/8"'.
# ---------------------------------------------------------------------------

def finish_descriptor(material_name):
    """Reduce a source material name to the descriptor used in generated names.

    The tail after the last ' - ' is kept, less any trailing library code in
    brackets -- that code is what the Mark segment already carries.

        '_ST-03 - Masonry - Brick - Soldier Course (FNS-B4)' -> 'Soldier Course'
        '_ST-05 - Large Format'                              -> 'Large Format'

    A bracketed suffix that is not a code is left alone, so the two variants
    of 'Soldier Course (FNS-B3)' and 'Soldier Course (FNS-B3)(sides)' do not
    collapse onto one name.
    """
    if not material_name:
        return "Unknown"

    tail = material_name.split(MATERIAL_SEPARATOR)[-1].strip()
    tail = _TRAILING_CODE_RE.sub("", tail).strip()
    return tail or "Unknown"


def skin_material_name(mark, descriptor):
    """SKIN_<MARK> - <Descriptor>.

    The descriptor keeps the source material's own capitalisation; only the
    wall type name upper-cases it.
    """
    return "{}{} - {}".format(SKIN_PREFIX,
                              (mark or "UNKNOWN").strip(),
                              (descriptor or "Unknown").strip())


def mark_of_skin_material_name(name):
    """Return the Mark segment of a generated material name, or None.

    'SKIN_FNS-B4 - Common Bond' -> 'FNS-B4'.  Anything not shaped like a
    generated name returns None, so unrelated materials never match.
    """
    if not name or not name.startswith(SKIN_PREFIX):
        return None

    rest = name[len(SKIN_PREFIX):]
    if MATERIAL_SEPARATOR not in rest:
        return None

    mark = rest.split(MATERIAL_SEPARATOR)[0].strip()
    return mark or None


def skin_type_name_from_mark(mark, descriptor, thickness_text):
    """SKIN_<MARK>_<DESCRIPTOR>_<THICKNESS>."""
    return skin_type_name(mark, descriptor, thickness_text)


def swap_thickness_token(name, thickness_text):
    """Return *name* with its trailing thickness token set to *thickness_text*.

    Used when an existing wall type has the right material but the wrong
    thickness: the new type keeps the old name and only its thickness moves.
    A name with no recognisable thickness token gets one appended.
    """
    if _THICKNESS_TOKEN_RE.search(name or ""):
        return _THICKNESS_TOKEN_RE.sub("_" + thickness_text, name)
    return "{}_{}".format(name, thickness_text)
