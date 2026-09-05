# -*- coding: utf-8 -*-
"""Reading a roof soffit as the height it stops a wall at.

A soffit is never built by these tools.  It is picked only to say where
a wall has to stop, so all that is wanted of it is two numbers: how low
its underside reaches and how high its top sits.

WHERE it sits in plan is deliberately not asked.  Picking a soffit IS
the statement that it governs the walls in this run -- the selection is
the answer, and working out which walls it happens to overhang would
only find a different one.  A soffit is taken as flat, and a wall under
it stops at its LOWEST point, so nothing pokes through whatever the
soffit turns out to be doing.
"""

import clr
clr.AddReference("RevitAPI")

from Autodesk.Revit.DB import (
    BuiltInCategory,
    ElementId,
    GeometryInstance,
    Options,
    Solid,
    ViewDetailLevel,
)
from pyrevit import script

logger = script.get_logger()


class SoffitShape(object):
    """One soffit, reduced to what a wall limit needs.

    *base_z* is the lowest point of the whole solid and *top_z* the
    highest, both in HOST coordinates.  A wall stopped by this soffit
    stops at *base_z*.
    """

    __slots__ = ("base_z", "top_z")

    def __init__(self):
        self.base_z = None
        self.top_z  = None


def is_soffit(elem):
    """True when *elem* is in the Roof Soffits category.

    The CATEGORY, not the class: which class Revit returns a soffit as
    is not something this tool should have an opinion about, and the
    category is what the user picks by in the first place.
    """
    if elem is None:
        return False
    try:
        cat = elem.Category
        if cat is None:
            return False
        return cat.Id == ElementId(BuiltInCategory.OST_RoofSoffit)
    except Exception:
        return False


def _solids(elem):
    """Yield *elem*'s solids, instance geometry included."""
    opts = Options()
    opts.ComputeReferences = False
    opts.IncludeNonVisibleObjects = False
    opts.DetailLevel = ViewDetailLevel.Medium

    try:
        geo_elem = elem.get_Geometry(opts)
    except Exception:
        return
    if geo_elem is None:
        return

    for gobj in geo_elem:
        if isinstance(gobj, Solid):
            candidates = [gobj]
        elif isinstance(gobj, GeometryInstance):
            try:
                candidates = [g for g in gobj.GetInstanceGeometry()
                              if isinstance(g, Solid)]
            except Exception:
                continue
        else:
            continue

        for sol in candidates:
            try:
                if sol.Volume <= 0:
                    continue
            except Exception:
                continue
            yield sol


def measure(elem, transform):
    """Measure a soffit.  Returns (SoffitShape or None, list of notes).

    Every tessellated vertex of every solid, and the lowest and highest
    of them.  Nothing finer is needed: the answer is one elevation, and
    the lowest point is the safe one whether the soffit is flat, dished
    or pitched.
    """
    zs = []
    for sol in _solids(elem):
        try:
            edges = sol.Edges
        except Exception:
            continue
        for edge in edges:
            try:
                pts = edge.Tessellate()
            except Exception:
                continue
            for p in pts:
                zs.append(transform.OfPoint(p).Z)

    if len(zs) < 2:
        return None, ["no usable soffit geometry (check the link's "
                      "view detail level)"]

    shape = SoffitShape()
    shape.base_z = min(zs)
    shape.top_z  = max(zs)
    return shape, []
