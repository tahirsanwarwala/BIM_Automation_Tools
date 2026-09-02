# -*- coding: utf-8 -*-
"""Resolution and creation of the generated SKIN materials and wall types.

Shared by the SplitWalls and SweepToWall tools so both behave identically.

Wall types are resolved from the source finish material's MARK, never from
any name:

  1. read the Mark of the linked wall's finish material;
  2. find the host material whose name is 'SKIN_<MARK> - ...';
  3. among the SKIN wall types using that material, take the one at the
     required thickness, or duplicate one at that thickness;
  4. with no Mark, no matching material, or an ambiguous match, ask the user
     to pick a SKIN wall type instead.

Matching on the Mark rather than on a name means wall types and materials
that were named by hand are found and reused, whatever they are called.

A generated SKIN material:

  - keeps the SURFACE patterns of the material it was derived from, so the
    new wall hatches the way the original finish did in elevation.  The
    source material may live in a linked document, in which case its fill
    patterns are recreated in the host document on demand.

  - gets its own distinct SHADING colour, so the generated materials can be
    told apart from one another in the host model.  The colour is derived
    from the material name by hash rather than by a random draw, so a name
    always maps to the same colour: re-running a tool, or running the two
    tools against the same finish, will not recolour anything.

  - keeps a solid CUT pattern in the shading colour, so it reads clearly in
    section.
"""

import clr
clr.AddReference("RevitAPI")

from Autodesk.Revit.DB import (
    BuiltInParameter,
    Color,
    CompoundStructureLayer,
    ElementId,
    FillPatternElement,
    FilteredElementCollector,
    Material,
    MaterialFunctionAssignment,
    ShellLayerType,
    WallKind,
    WallType,
)
from System.Collections.Generic import List as NetList
from pyrevit import forms

from Tahir import wall_naming

SKIN_PREFIX = wall_naming.SKIN_PREFIX

# Two wall types count as the same thickness within this tolerance, in feet
# (about 0.6 mm).  Layer widths come back as exact doubles, so this only has
# to absorb rounding, not real differences in thickness.
TYPE_THICKNESS_TOL = 0.002

# Fixed grey used for surface patterns when the source material has none.
DEFAULT_SURFACE_RGB = (120, 120, 120)

# Generated shading colours are drawn from a coarse grid rather than the full
# colour wheel.  Hashing straight to one of 360 hues looks well spread on
# paper but regularly puts two materials within a few degrees of each other,
# which is indistinguishable on screen.  Twelve hues at 30 degree spacing,
# crossed with three saturations and two values, give 72 combinations that
# are all actually tellable apart.
SHADING_HUE_STEPS   = 12
SHADING_SATURATIONS = (0.45, 0.70, 0.95)
SHADING_VALUES      = (0.90, 0.65)


def skin_material_name(mark, descriptor):
    """SKIN_<MARK> - <Descriptor>."""
    return wall_naming.skin_material_name(mark, descriptor)


def element_name(element):
    """Safely read an element's name, returning "" when it cannot be read.

    Element.Name is not dependable from IronPython -- on wall types the
    binder can fail to resolve it against the base Element property and
    raise -- so every name read goes through here.  The Type Name parameter
    is the fallback, the same one the tools' own get_element_name() uses.
    """
    if element is None:
        return ""
    try:
        return element.Name or ""
    except Exception:
        pass
    try:
        p = element.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
        if p and p.HasValue:
            return p.AsString() or ""
    except Exception:
        pass
    try:
        p = element.LookupParameter("Type Name")
        if p and p.HasValue:
            return p.AsString() or ""
    except Exception:
        pass
    return ""


def wall_type_width(wall_type):
    """Safely read a wall type's total width, or None."""
    try:
        return wall_type.Width
    except Exception:
        return None


def _hash_text(text):
    """Stable 32-bit hash.

    Python's own hash() is salted per process, so it would give a material a
    different colour on every Revit session.
    """
    h = 2166136261
    for ch in text or "":
        h = ((h ^ ord(ch)) * 16777619) & 0xFFFFFFFF
    return h


def _hsv_to_rgb(hue, sat, val):
    """Convert HSV (hue 0-360, sat/val 0-1) to an (r, g, b) 0-255 tuple."""
    c = val * sat
    h = (hue % 360) / 60.0
    x = c * (1 - abs(h % 2 - 1))
    m = val - c

    if   h < 1: r, g, b = c, x, 0
    elif h < 2: r, g, b = x, c, 0
    elif h < 3: r, g, b = 0, c, x
    elif h < 4: r, g, b = 0, x, c
    elif h < 5: r, g, b = x, 0, c
    else:       r, g, b = c, 0, x

    return (int(round((r + m) * 255)),
            int(round((g + m) * 255)),
            int(round((b + m) * 255)))


def shading_palette():
    """Return the ordered list of candidate shading colours."""
    palette = []
    for val in SHADING_VALUES:
        for sat in SHADING_SATURATIONS:
            for i in range(SHADING_HUE_STEPS):
                # Offset the ring by half a step so the hues do not land on
                # pure primaries.
                hue = i * (360.0 / SHADING_HUE_STEPS) + 15.0
                palette.append(_hsv_to_rgb(hue, sat, val))
    return palette


# Step used to walk the palette.  Coprime with the palette length, so the walk
# visits every entry, and large enough that consecutive tries are far apart.
PALETTE_STRIDE = 31


def _rgb_distance(a, b):
    """Straight-line distance between two RGB triples."""
    return ((a[0] - b[0]) ** 2
            + (a[1] - b[1]) ** 2
            + (a[2] - b[2]) ** 2) ** 0.5


def distinct_shading_rgb(seed_text, used=None):
    """Return a shading colour for *seed_text* that avoids *used*.

    The starting point is hashed from the name, so the choice looks arbitrary
    and is stable for a given name and a given set of colours already in use.
    From there the palette is walked until an unused colour turns up, which
    keeps every generated material a different colour until the palette is
    exhausted.  Past that point the colour furthest from everything already
    in use is returned.
    """
    palette = shading_palette()
    count   = len(palette)
    start   = _hash_text(seed_text) % count
    taken   = set(used or ())

    order = [palette[(start + k * PALETTE_STRIDE) % count]
             for k in range(count)]

    for rgb in order:
        if rgb not in taken:
            return rgb

    return max(order, key=lambda rgb: min(_rgb_distance(rgb, t)
                                          for t in taken))


def type_match_key(mark, thickness):
    """Identity of a generated wall type: its Mark and its thickness.

    This is what 'have we already resolved / approved this' is tracked by,
    so one dialog covers every wall needing the same type.
    """
    return (mark, round(thickness / TYPE_THICKNESS_TOL))


def material_mark(material):
    """Return the Mark of *material*, or None when it is blank or absent."""
    if material is None:
        return None

    getters = (
        lambda m: m.get_Parameter(BuiltInParameter.ALL_MODEL_MARK),
        lambda m: m.LookupParameter("Mark"),
    )
    for getter in getters:
        try:
            p = getter(material)
        except Exception:
            continue
        if p is None:
            continue
        try:
            if not p.HasValue:
                continue
            value = p.AsString()
        except Exception:
            continue
        if value and value.strip():
            return value.strip()
    return None


def find_host_materials_by_mark(doc, mark):
    """Return every host material whose name is 'SKIN_<mark> - ...'.

    The comparison is against the Mark segment of the name, not a loose
    substring search, so 'ST-02' cannot match a 'ST-020' material.
    """
    if not mark:
        return []

    wanted = mark.strip().upper()
    found  = []
    for mat in FilteredElementCollector(doc).OfClass(Material):
        try:
            segment = wall_naming.mark_of_skin_material_name(
                element_name(mat))
        except Exception:
            continue
        if segment and segment.upper() == wanted:
            found.append(mat)
    return found


def wall_type_finish_material_name(doc, wall_type):
    """Return the name of *wall_type*'s outermost layer material, or None.

    Layer 0 is the exterior-most layer, which for a generated single-layer
    SKIN type is its only layer.
    """
    try:
        cs = wall_type.GetCompoundStructure()
        if cs is None or cs.LayerCount == 0:
            return None
        mat_id = cs.GetMaterialId(0)
    except Exception:
        return None

    if mat_id is None or mat_id == ElementId.InvalidElementId:
        return None
    return element_name(doc.GetElement(mat_id)) or None


def wall_type_finish_material_id(wall_type):
    """Return the ElementId of *wall_type*'s outermost layer material."""
    try:
        cs = wall_type.GetCompoundStructure()
        if cs is None or cs.LayerCount == 0:
            return ElementId.InvalidElementId
        return cs.GetMaterialId(0)
    except Exception:
        return ElementId.InvalidElementId


def iter_basic_wall_types(doc):
    """Yield every Basic wall type in *doc* that has a compound structure."""
    for wt in FilteredElementCollector(doc).OfClass(WallType):
        try:
            if wt.Kind != WallKind.Basic:
                continue
            if wt.GetCompoundStructure() is None:
                continue
        except Exception:
            continue
        yield wt


def find_skin_wall_types(doc):
    """Return every Basic wall type whose name marks it as a SKIN type."""
    return [wt for wt in iter_basic_wall_types(doc)
            if element_name(wt).startswith(SKIN_PREFIX)]


def find_wall_types_using_material(doc, material_id):
    """Return the Basic wall types whose outermost layer is *material_id*."""
    if material_id is None or material_id == ElementId.InvalidElementId:
        return []
    return [wt for wt in iter_basic_wall_types(doc)
            if wall_type_finish_material_id(wt) == material_id]


def find_base_host_type(doc):
    """Return any Basic wall type usable as a duplication base."""
    for wt in iter_basic_wall_types(doc):
        return wt
    return None


def _matches_thickness(wall_type, thickness, tol=TYPE_THICKNESS_TOL):
    width = wall_type_width(wall_type)
    if width is None:
        return False
    return abs(width - thickness) <= tol


def used_skin_shading_colors(doc):
    """Return the shading colours already taken by SKIN materials in *doc*."""
    used = set()
    for mat in FilteredElementCollector(doc).OfClass(Material):
        try:
            if not element_name(mat).startswith(SKIN_PREFIX):
                continue
            c = mat.Color
            if c is not None and c.IsValid:
                used.add((c.Red, c.Green, c.Blue))
        except Exception:
            continue
    return used


def _find_solid_fill_pattern(doc):
    """Return the ElementId of the '<Solid fill>' FillPatternElement in *doc*,
    or ElementId.InvalidElementId if there isn't one.
    """
    for fp in FilteredElementCollector(doc).OfClass(FillPatternElement):
        pat = fp.GetFillPattern()
        if pat and pat.IsSolidFill:
            return fp.Id
    return ElementId.InvalidElementId


def _resolve_fill_pattern(doc, source_doc, pattern_id):
    """Return an ElementId for *pattern_id* usable in *doc*.

    Patterns are matched by name, and recreated in *doc* when the source
    pattern only exists in a linked document.  Returns
    ElementId.InvalidElementId when it cannot be resolved.
    """
    if pattern_id is None or pattern_id == ElementId.InvalidElementId:
        return ElementId.InvalidElementId
    if source_doc is None:
        return ElementId.InvalidElementId

    src = source_doc.GetElement(pattern_id)
    if src is None:
        return ElementId.InvalidElementId

    name = element_name(src)
    if not name:
        return ElementId.InvalidElementId

    for fp in FilteredElementCollector(doc).OfClass(FillPatternElement):
        if element_name(fp) == name:
            return fp.Id

    try:
        return FillPatternElement.Create(doc, src.GetFillPattern()).Id
    except Exception:
        return ElementId.InvalidElementId


def _copy_surface_patterns(doc, target_mat, source_mat, source_doc):
    """Copy the surface fill patterns and their colours from *source_mat*.

    Returns True when at least one pattern was carried over.
    """
    if source_mat is None:
        return False

    copied = False
    pairs = (
        ("SurfaceForegroundPatternId", "SurfaceForegroundPatternColor"),
        ("SurfaceBackgroundPatternId", "SurfaceBackgroundPatternColor"),
    )
    for id_attr, color_attr in pairs:
        try:
            src_id = getattr(source_mat, id_attr)
        except Exception:
            continue

        host_id = _resolve_fill_pattern(doc, source_doc, src_id)
        if host_id == ElementId.InvalidElementId:
            continue

        try:
            setattr(target_mat, id_attr, host_id)
            copied = True
        except Exception:
            continue

        try:
            src_color = getattr(source_mat, color_attr)
            if src_color is not None and src_color.IsValid:
                setattr(target_mat, color_attr, src_color)
        except Exception:
            pass

    return copied


def _set_plain_surface_color(target_mat, rgb):
    """Set both surface pattern colours to *rgb*, leaving patterns alone."""
    try:
        target_mat.SurfaceForegroundPatternColor = Color(rgb[0], rgb[1], rgb[2])
        target_mat.SurfaceBackgroundPatternColor = Color(rgb[0], rgb[1], rgb[2])
    except Exception:
        pass


def _set_cut_appearance(doc, target_mat, rgb):
    """Give *target_mat* a solid cut pattern in *rgb*."""
    try:
        solid_id = _find_solid_fill_pattern(doc)
        if solid_id != ElementId.InvalidElementId:
            target_mat.CutForegroundPatternId = solid_id
        target_mat.CutForegroundPatternColor = Color(rgb[0], rgb[1], rgb[2])
        target_mat.CutBackgroundPatternColor = Color(120, 120, 120)
    except Exception:
        pass


def get_or_create_skin_material(doc, name,
                                source_material=None, source_doc=None):
    """Return the ElementId of the SKIN material called *name* in *doc*.

    An existing material of that name is returned untouched.  A new one gets:
      - the surface patterns of *source_material* (recreated in *doc* if that
        material lives in a link), falling back to plain grey when the source
        has no surface pattern or was not supplied,
      - a distinct shading colour derived from its own name,
      - a solid cut pattern in that shading colour.

    *source_doc* is the document *source_material* belongs to; pass the linked
    document when the finish comes from a link.
    """
    for mat in FilteredElementCollector(doc).OfClass(Material):
        if element_name(mat) == name:
            return mat.Id

    # Read the colours already in use BEFORE the new material exists, so it
    # cannot collide with any SKIN material created earlier in this run.
    taken = used_skin_shading_colors(doc)

    new_id = Material.Create(doc, name)
    mat    = doc.GetElement(new_id)

    shading = distinct_shading_rgb(name, taken)
    try:
        mat.Color = Color(shading[0], shading[1], shading[2])
    except Exception:
        pass

    if not _copy_surface_patterns(doc, mat, source_material, source_doc):
        _set_plain_surface_color(mat, DEFAULT_SURFACE_RGB)

    _set_cut_appearance(doc, mat, shading)

    return new_id


# ===========================================================================
# WALL TYPE RESOLUTION
#
# Resolution is split in two so the dialogs never open inside a transaction:
# plan_skin_wall_type() decides what is needed and does all the asking, then
# execute_skin_wall_type_plan() does the writing.
# ===========================================================================

def _unique_type_name(doc, name):
    """Return *name*, or *name* with a numeric suffix if it is already taken."""
    taken = set()
    for wt in FilteredElementCollector(doc).OfClass(WallType):
        try:
            taken.add(element_name(wt))
        except Exception:
            continue

    if name not in taken:
        return name

    n = 2
    while "{} ({})".format(name, n) in taken:
        n += 1
    return "{} ({})".format(name, n)


def _apply_single_layer(new_type, thickness, material_id):
    """Give *new_type* one Structure layer of *thickness* in *material_id*."""
    cs = new_type.GetCompoundStructure()

    layers = NetList[CompoundStructureLayer]()
    layers.Add(CompoundStructureLayer(
        thickness, MaterialFunctionAssignment.Structure, material_id))

    cs.SetLayers(layers)
    cs.SetNumberOfShellLayers(ShellLayerType.Exterior, 0)
    cs.SetNumberOfShellLayers(ShellLayerType.Interior, 0)
    new_type.SetCompoundStructure(cs)
    return new_type


def duplicate_type_at_thickness(doc, template, thickness, name):
    """Duplicate *template* as *name*, resized to *thickness*.

    The duplicate keeps the template's material.  A template that is already
    a single layer just has that layer resized; anything else is rebuilt as a
    single layer, so the result is a clean SKIN type either way.
    """
    new_type = template.Duplicate(_unique_type_name(doc, name))
    mat_id   = wall_type_finish_material_id(template)

    cs = new_type.GetCompoundStructure()
    if cs is not None and cs.LayerCount == 1:
        try:
            cs.SetLayerWidth(0, thickness)
            new_type.SetCompoundStructure(cs)
            return new_type
        except Exception:
            pass

    return _apply_single_layer(new_type, thickness, mat_id)


def create_type_with_new_material(doc, plan, source_material, source_doc):
    """Create the SKIN material and single-layer wall type *plan* describes."""
    mat_id = get_or_create_skin_material(
        doc, plan["material_name"], source_material, source_doc)

    base = find_base_host_type(doc)
    if base is None:
        raise RuntimeError("No Basic wall type in the host model to duplicate")

    new_type = base.Duplicate(_unique_type_name(doc, plan["name"]))
    return _apply_single_layer(new_type, plan["thickness"], mat_id)


def _skip(reason):
    return {"action": "skip", "reason": reason}


def _confirm(message, tool_title):
    return bool(forms.alert(message, title=tool_title, yes=True, no=True))


def _plan_from_picked_type(doc, picked, thickness, thk_text, tool_title):
    """Turn a user-picked wall type into a plan, re-thicknessing if needed."""
    picked_name = element_name(picked)

    if _matches_thickness(picked, thickness):
        return {"action": "use", "type": picked, "name": picked_name}

    name       = wall_naming.swap_thickness_token(picked_name, thk_text)
    picked_thk = wall_type_width(picked)
    if not _confirm(
            "'{}' is {}, not {}.\n\nCreate '{}' at {}?".format(
                picked_name,
                wall_naming.feet_to_imperial(picked_thk or 0.0),
                thk_text, name, thk_text),
            tool_title):
        return _skip("declined new wall type '{}'".format(name))

    return {"action": "duplicate", "template": picked,
            "thickness": thickness, "name": name}


def pick_skin_wall_type(doc, reason, source_name, thk_text):
    """Ask the user to choose a SKIN wall type; return it, or None.

    The prompt names the linked finish material and its thickness, which is
    what the choice has to be made on.  None means either that the user
    cancelled or that there was nothing to choose from -- callers that need
    to tell those apart should check find_skin_wall_types() first.
    """
    by_name = {}
    for wt in find_skin_wall_types(doc):
        name = element_name(wt)
        if name:
            by_name[name] = wt

    if not by_name:
        return None

    picked_name = forms.SelectFromList.show(
        sorted(by_name.keys()),
        title="{}  |  Linked finish: {}  ({})".format(
            reason, source_name, thk_text),
        button_name="Use this wall type",
        multiselect=False)

    if not picked_name:
        return None
    return by_name[picked_name]


def _plan_from_user_pick(doc, reason, source_name, thk_text, thickness,
                         tool_title):
    """Ask the user to pick a SKIN wall type, and plan from their choice."""
    if not find_skin_wall_types(doc):
        return _skip("{} - and no SKIN wall types exist to pick from"
                     .format(reason))

    picked = pick_skin_wall_type(doc, reason, source_name, thk_text)
    if picked is None:
        return _skip("{} - no wall type picked".format(reason))

    return _plan_from_picked_type(
        doc, picked, thickness, thk_text, tool_title)


def plan_skin_wall_type(doc, source_material, source_doc, thickness,
                        tool_title):
    """Work out which wall type to use for a linked finish, asking as needed.

    *thickness* is what the new wall must be: the linked finish layer's own
    thickness for SplitWalls, a fixed default for SweepToWall.

    Returns a plan dict whose "action" is use / duplicate / create / skip.
    Every dialog this needs is raised here, so callers must run it before
    opening a transaction.
    """
    thk_text = wall_naming.feet_to_imperial(thickness)
    src_name = element_name(source_material) or "<none>"
    mark     = material_mark(source_material)

    if not mark:
        return _plan_from_user_pick(
            doc, "Linked finish material has no Mark",
            src_name, thk_text, thickness, tool_title)

    matches = find_host_materials_by_mark(doc, mark)

    if len(matches) > 1:
        return _plan_from_user_pick(
            doc, "{} host materials share Mark '{}'".format(len(matches), mark),
            src_name, thk_text, thickness, tool_title)

    if len(matches) == 1:
        host_mat = matches[0]
        types    = find_wall_types_using_material(doc, host_mat.Id)

        for wt in types:
            if _matches_thickness(wt, thickness):
                return {"action": "use", "type": wt,
                        "name": element_name(wt)}

        if types:
            template      = types[0]
            template_name = element_name(template)
            template_thk  = wall_type_width(template)
            name = wall_naming.swap_thickness_token(template_name, thk_text)
            if not _confirm(
                    "Material '{}' is used by '{}' at {}, but {} is needed."
                    "\n\nCreate '{}'?".format(
                        element_name(host_mat), template_name,
                        wall_naming.feet_to_imperial(template_thk or 0.0),
                        thk_text, name),
                    tool_title):
                return _skip("declined new wall type '{}'".format(name))

            return {"action": "duplicate", "template": template,
                    "thickness": thickness, "name": name}

        return _plan_from_user_pick(
            doc, "No wall type uses material '{}'".format(
                element_name(host_mat)),
            src_name, thk_text, thickness, tool_title)

    # Nothing carries this Mark yet: make the material and its wall type.
    # They are inseparable -- a material with no type is of no use -- so one
    # confirmation covers both.
    descriptor = wall_naming.finish_descriptor(src_name)
    mat_name   = wall_naming.skin_material_name(mark, descriptor)
    type_name  = wall_naming.skin_type_name_from_mark(mark, descriptor, thk_text)

    if not _confirm(
            "No host material carries Mark '{}'.\n\n"
            "Create material '{}'\nand wall type '{}'?".format(
                mark, mat_name, type_name),
            tool_title):
        return _skip("declined new material '{}'".format(mat_name))

    return {"action": "create", "name": type_name,
            "material_name": mat_name, "thickness": thickness,
            "mark": mark, "descriptor": descriptor}


def execute_skin_wall_type_plan(doc, plan, source_material=None,
                                source_doc=None):
    """Carry out a plan from plan_skin_wall_type and return the WallType.

    Returns None for a "skip" plan.  Must run inside a transaction.
    """
    action = plan.get("action")

    if action == "use":
        return plan["type"]
    if action == "duplicate":
        return duplicate_type_at_thickness(
            doc, plan["template"], plan["thickness"], plan["name"])
    if action == "create":
        return create_type_with_new_material(
            doc, plan, source_material, source_doc)
    return None
