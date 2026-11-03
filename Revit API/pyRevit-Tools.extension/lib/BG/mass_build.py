# -*- coding: utf-8 -*-
"""The Revit half of Element To Mass.

Each picked element -- in this model or in a link -- becomes a
conceptual mass of its own, standing where the element stands, built
from the element's finished solid geometry.

The element's solids are copied into a new mass family as free-form
solids, the family is saved, loaded into this model and placed so the
mass sits exactly on the element.  The original element and any link
are never modified.

The names and the report text are in mass_plan, which imports no
Revit.  This module is verified by running the tool.
"""

import os
import tempfile

import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

from Autodesk.Revit.DB import (
    Element,
    ElementTransformUtils,
    Family,
    FamilyInstance,
    FilteredElementCollector,
    FreeFormElement,
    GeometryInstance,
    Options,
    RevitLinkInstance,
    SaveAsOptions,
    Solid,
    SolidUtils,
    SubTransaction,
    Transaction,
    Transform,
    ViewDetailLevel,
    XYZ,
)
from Autodesk.Revit.DB.Structure import StructuralType
from Autodesk.Revit.Exceptions import OperationCanceledException
from Autodesk.Revit.UI.Selection import ObjectType

from BG import mass_plan

HOST = "In this model"
LINK = "In a link"

MASS_TEMPLATE = (r"C:\ProgramData\Autodesk\RVT 2025\Family Templates"
                 r"\English-Imperial\Conceptual Mass\Mass.rft")


# ===========================================================================
# PICKING
# ===========================================================================

def selected_sources(uidoc):
    """The pre-selected host elements, as (element, doc, link transform).

    A selected link instance does not count: it is the whole link, not
    an element in it.  An empty list means the user is asked to pick.
    """
    doc = uidoc.Document
    sources = []
    for eid in uidoc.Selection.GetElementIds():
        elem = doc.GetElement(eid)
        if elem is None or isinstance(elem, RevitLinkInstance):
            continue
        sources.append((elem, doc, Transform.Identity))
    return sources


def pick_sources(uidoc, where):
    """The picked elements, as (element, doc, link transform) tuples.

    PickObjects, so the user can click or box-select as many as they
    like and then click Finish.  For linked elements, a box only catches
    them while Revit's "Select links" toggle is on; clicking works
    either way.  Elements from several links can be mixed in one pick.
    The link transform is identity for an element in this model.
    """
    doc = uidoc.Document
    try:
        if where == HOST:
            refs = uidoc.Selection.PickObjects(
                ObjectType.Element,
                "Select the elements to turn into masses, then click Finish")
        else:
            refs = uidoc.Selection.PickObjects(
                ObjectType.LinkedElement,
                "Select the linked elements to turn into masses, then "
                "click Finish")
    except OperationCanceledException:
        return []

    sources = []
    seen = set()
    for ref in refs or []:
        if where == HOST:
            key = (_id_text(ref.ElementId), None)
        else:
            key = (_id_text(ref.ElementId), _id_text(ref.LinkedElementId))
        if key in seen:
            continue        # a box and a click on the same element
        seen.add(key)

        if where == HOST:
            elem = doc.GetElement(ref.ElementId)
            if elem is not None and not isinstance(elem, RevitLinkInstance):
                sources.append((elem, doc, Transform.Identity))
            continue

        link = doc.GetElement(ref.ElementId)
        link_doc = link.GetLinkDocument() if link is not None else None
        if link_doc is None:
            continue
        elem = link_doc.GetElement(ref.LinkedElementId)
        if elem is not None:
            sources.append((elem, link_doc, link.GetTotalTransform()))
    return sources


def source_label(element):
    """How an element is named in the report: its name and id."""
    return "{} [{}]".format(source_name(element) or "Element",
                            _id_text(element.Id))


def _id_text(element_id):
    """An ElementId as text, whichever Revit version this is."""
    for attr in ("Value", "IntegerValue"):
        try:
            return str(getattr(element_id, attr))
        except Exception:
            continue
    return str(element_id)


def source_name(element):
    """What the mass family is named after."""
    if isinstance(element, FamilyInstance):
        return element.Symbol.Family.Name
    try:
        return Element.Name.GetValue(element)
    except Exception:
        return ""


# ===========================================================================
# THE SOLID
# ===========================================================================

def _options():
    opt = Options()
    opt.DetailLevel = ViewDetailLevel.Fine
    return opt


def _walk_solids(geom):
    """Every solid with volume in a geometry element, nested ones too.

    GetInstanceGeometry is already in the owning document's
    coordinates, so a nested family or a family instance's symbol
    geometry needs no transform of its own here.
    """
    for obj in geom or []:
        if isinstance(obj, Solid):
            if obj.Volume > mass_plan.VOLUME_EPS:
                yield obj
        elif isinstance(obj, GeometryInstance):
            for solid in _walk_solids(obj.GetInstanceGeometry()):
                yield solid


def element_solids(element, transform):
    """The element's solids, COPIED through transform.

    CreateTransformed always makes a new solid, so nothing returned
    belongs to the element's document.
    """
    geom = element.get_Geometry(_options())
    return [SolidUtils.CreateTransformed(s, transform)
            for s in _walk_solids(geom)]


# ===========================================================================
# THE MASS FAMILY
# ===========================================================================

def origin_of(solids):
    """Where the family's own origin goes: the XY minimum of every piece,
    at Z = 0.

    Built around this point instead of the project origin, so a mass for
    an element miles from the origin does not sit miles from its own.
    It need not be exact -- the pieces are shifted by it and the
    instance placed at it -- so edge points are enough.
    """
    xs, ys = [], []
    for solid in solids:
        for edge in solid.Edges:
            for p in edge.Tessellate():
                xs.append(p.X)
                ys.append(p.Y)
    if not xs:
        return XYZ.Zero
    return XYZ(min(xs), min(ys), 0.0)


def build_mass_family(app, template, solids, name, origin):
    """Make, save and close the mass family.

    Returns (rfa path, solids made, failure notes).  A piece
    FreeFormElement refuses is noted and the rest go on; if no piece at
    all could be made, it raises.
    """
    shift = Transform.CreateTranslation(origin.Negate())
    failed = []
    fam_doc = app.NewFamilyDocument(template)
    try:
        t = Transaction(fam_doc, "Element To Mass - build")
        t.Start()
        try:
            made = _create_forms(fam_doc, solids, shift, failed)
            t.Commit()
        except Exception:
            t.RollBack()
            raise
        if made == 0:
            raise Exception("Revit refused every piece: {}".format(
                "; ".join(failed)))

        path = os.path.join(tempfile.gettempdir(), name + ".rfa")
        opts = SaveAsOptions()
        opts.OverwriteExistingFile = True
        fam_doc.SaveAs(path, opts)
    finally:
        fam_doc.Close(False)
    return path, made, failed


def _create_forms(fam_doc, solids, shift, failed):
    """One FreeFormElement per solid; returns how many were made.

    Each in its own SubTransaction, so a refused piece is undone cleanly
    and does not spoil the ones around it.
    """
    made = 0
    for i, solid in enumerate(solids):
        st = SubTransaction(fam_doc)
        st.Start()
        try:
            FreeFormElement.Create(
                fam_doc, SolidUtils.CreateTransformed(solid, shift))
            st.Commit()
            made += 1
        except Exception as ex:
            st.RollBack()
            failed.append("solid piece {} refused by Revit ({})".format(
                i + 1, ex))
    return made


# ===========================================================================
# LOAD AND PLACE
# ===========================================================================

def load_and_place(doc, rfa_path, name, origin):
    """Load the family, place it at origin, and make sure it is there.

    Revit may place a mass relative to a level or work plane; comparing
    the placed instance's transform origin with where it was meant to
    go, and moving it by the difference, makes the result right however
    it was placed.  One transaction: a failure leaves the host as it was.
    """
    t = Transaction(doc, "Element To Mass")
    t.Start()
    try:
        doc.LoadFamily(rfa_path)
        family = None
        for fam in FilteredElementCollector(doc).OfClass(Family):
            if fam.Name == name:
                family = fam
                break
        if family is None:
            raise Exception("family '{}' did not load".format(name))

        symbol = doc.GetElement(list(family.GetFamilySymbolIds())[0])
        if not symbol.IsActive:
            symbol.Activate()
            doc.Regenerate()

        inst = doc.Create.NewFamilyInstance(origin, symbol,
                                            StructuralType.NonStructural)
        doc.Regenerate()
        delta = origin.Subtract(inst.GetTotalTransform().Origin)
        if delta.GetLength() > mass_plan.PLACE_TOL:
            ElementTransformUtils.MoveElement(doc, inst.Id, delta)
        t.Commit()
    except Exception:
        t.RollBack()
        raise
    finally:
        try:
            os.remove(rfa_path)
        except Exception:
            pass
    return inst
