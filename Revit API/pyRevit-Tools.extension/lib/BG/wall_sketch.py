# -*- coding: utf-8 -*-
"""Re-sketching a wall's elevation profile with a new set of curves.

Extracted from CurtainWallTrim so WindowToCurtainWall - and now Multi
Wall Creation - can share it rather than carry a second copy.  Behaviour
is unchanged from those scripts; the only differences are that *doc* is
now passed in rather than read off a module global, and apply_profile
takes the transaction and scope names as parameters instead of hard-
coding one caller's wording.

Those two names stay parameters on purpose.  CurtainWallTrim's undo
stack should read "Create trim profile sketch" / "Cut the source wall
out of the trim" and WindowToCurtainWall's should read "Create wall
profile sketch" / "Reshape curtain wall to the window" - unifying them
would rename what each tool shows in Revit's Edit > Undo menu, which is
a visible behaviour change this refactor must not make.
"""

import clr
clr.AddReference("RevitAPI")

from Autodesk.Revit.DB import (
    CurveElement,
    ElementId,
    FailureProcessingResult,
    FailureSeverity,
    IFailuresPreprocessor,
    Sketch,
    SketchEditScope,
    Transaction,
)
from pyrevit import script

logger = script.get_logger()


def as_element_id(thing):
    """Return an ElementId for *thing*, whether it is one or an element.

    Some API calls hand back the element they made and others hand back
    its id, and which one you get varies by version.
    """
    if thing is None:
        return None
    if isinstance(thing, ElementId):
        return thing
    try:
        return thing.Id
    except Exception:
        return None


class SketchFailureSwallower(IFailuresPreprocessor):
    """Keep Revit's failure dialog out of the way.

    Warnings are dropped outright.  Errors are resolved by deleting the
    elements that failed - in practice mullions Revit could not keep on a
    reshaped wall - so the edit commits instead of stopping on a dialog
    the script cannot answer.
    """

    def PreprocessFailures(self, failures_accessor):
        try:
            failures_accessor.DeleteAllWarnings()
        except Exception:
            pass

        removed = False
        try:
            for failure in failures_accessor.GetFailureMessages():
                if failure.GetSeverity() != FailureSeverity.Error:
                    continue
                ids = list(failure.GetFailingElementIds())
                if not ids:
                    continue
                if failures_accessor.IsElementsDeletionPermitted(ids):
                    failures_accessor.DeleteElements(ids)
                    removed = True
        except Exception as ex:
            logger.debug("Could not resolve a failure: {}".format(ex))

        if removed:
            return FailureProcessingResult.ProceedWithCommit
        return FailureProcessingResult.Continue


def sketch_curve_ids(doc, sketch):
    """Return the element ids of a sketch's profile curves.

    A sketch owns more than its curves - reference planes and dimensions
    live there too - so the ids are filtered down to CurveElements before
    anything gets deleted.

    *doc* was a module global in both source scripts; here it is passed
    in like everywhere else in this module, since this function has no
    other way to reach it.
    """
    ids = []
    try:
        for cid in sketch.GetAllElements():
            if isinstance(doc.GetElement(cid), CurveElement):
                ids.append(cid)
    except Exception:
        pass
    if ids:
        return ids

    try:
        for arr in sketch.Profile:
            for curve in arr:
                ref = curve.Reference
                if ref is not None:
                    ids.append(ref.ElementId)
    except Exception:
        pass
    return ids


def apply_profile(doc, wall, curves, sketch_name, scope_name):
    """Re-sketch *wall*'s elevation profile.  Returns None, or a reason.

    Runs outside any open transaction: SketchEditScope refuses to start
    inside one.
    """
    t = Transaction(doc, sketch_name)
    try:
        t.Start()
        sketch_id = wall.SketchId
        if sketch_id is None or sketch_id == ElementId.InvalidElementId:
            # CreateProfileSketch hands back the Sketch itself, not its id.
            sketch_id = as_element_id(wall.CreateProfileSketch())
        t.Commit()
    except Exception as ex:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        return "profile sketch unavailable on this wall ({})".format(ex)

    if sketch_id is None:
        return "profile sketch could not be created"

    sketch = doc.GetElement(sketch_id)
    if not isinstance(sketch, Sketch):
        return "profile sketch could not be read back"

    scope = SketchEditScope(doc, scope_name)
    try:
        scope.Start(sketch.Id)
    except Exception as ex:
        return "profile sketch could not be opened ({})".format(ex)

    inner = Transaction(doc, "Replace profile curves")
    try:
        inner.Start()
        try:
            opts = inner.GetFailureHandlingOptions()
            opts.SetFailuresPreprocessor(SketchFailureSwallower())
            inner.SetFailureHandlingOptions(opts)
        except Exception as ex:
            logger.debug("Could not set failure handling: {}".format(ex))
        plane = sketch.SketchPlane
        for cid in sketch_curve_ids(doc, sketch):
            try:
                doc.Delete(cid)
            except Exception:
                continue
        for curve in curves:
            doc.Create.NewModelCurve(curve, plane)
        inner.Commit()
    except Exception as ex:
        if inner.HasStarted() and not inner.HasEnded():
            inner.RollBack()
        try:
            scope.Cancel()
        except Exception:
            pass
        return "profile could not be re-sketched ({})".format(ex)

    try:
        scope.Commit(SketchFailureSwallower())
    except Exception as ex:
        try:
            scope.Cancel()
        except Exception:
            pass
        return "profile edit was rejected ({})".format(ex)
    return None
