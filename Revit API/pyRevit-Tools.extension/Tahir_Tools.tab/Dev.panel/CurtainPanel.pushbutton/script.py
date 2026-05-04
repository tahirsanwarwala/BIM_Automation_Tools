# -*- coding: utf-8 -*-
"""
Cladding System Area Calculator
Lets the user pick one or more levels, collects all curtain walls on plan
views associated with those levels, sums the area of all panels with type
name "Cladding System", and writes the total into the
"Cladding System Area" parameter on the parent curtain wall.
"""

from pyrevit import revit, DB, script, forms
from collections import defaultdict

doc    = revit.doc
output = script.get_output()
logger = script.get_logger()

# ─── 1. Build a level list and let the user pick ──────────────────────────────
all_levels = (
    DB.FilteredElementCollector(doc)
      .OfClass(DB.Level)
      .ToElements()
)
all_levels = sorted(all_levels, key=lambda l: l.Elevation)

level_map = {l.Name: l for l in all_levels}

selected_names = forms.SelectFromList.show(
    sorted(level_map.keys()),
    title="Select Levels",
    multiselect=True,
    button_name="Run Script",
)

if not selected_names:
    script.exit()

selected_levels = [level_map[n] for n in selected_names]
selected_level_ids = {l.Id for l in selected_levels}

# ─── 2. Find floor-plan views that are associated with the selected levels ────
all_views = (
    DB.FilteredElementCollector(doc)
      .OfClass(DB.ViewPlan)
      .ToElements()
)

# Map level id → list of plan views on that level
level_to_views = defaultdict(list)
for v in all_views:
    if v.IsTemplate:
        continue
    if v.GenLevel is not None and v.GenLevel.Id in selected_level_ids:
        level_to_views[v.GenLevel.Id].append(v)

# ─── 3. Collect curtain walls across all relevant plan views ──────────────────
# Use a set to avoid processing the same wall twice (it may appear in
# multiple views on the same level).
seen_wall_ids = set()
curtain_walls  = []

for level in selected_levels:
    views_on_level = level_to_views.get(level.Id, [])

    if not views_on_level:
        logger.warning("No floor-plan view found for level '{}'.".format(level.Name))
        continue

    for v in views_on_level:
        walls = (
            DB.FilteredElementCollector(doc, v.Id)
              .OfCategory(DB.BuiltInCategory.OST_Walls)
              .OfClass(DB.Wall)
              .ToElements()
        )
        for w in walls:
            if w.WallType.Kind == DB.WallKind.Curtain and w.Id not in seen_wall_ids:
                seen_wall_ids.add(w.Id)
                curtain_walls.append(w)

if not curtain_walls:
    forms.alert("No curtain walls found on the selected levels.", exitscript=True)

output.print_md(
    "Found **{}** unique curtain wall(s) across **{}** level(s).".format(
        len(curtain_walls), len(selected_levels)
    )
)

# ─── 4. Helper – get area of a panel in internal ft² ─────────────────────────
def get_panel_area(panel):
    area_param = panel.get_Parameter(DB.BuiltInParameter.HOST_AREA_COMPUTED)
    if area_param and area_param.HasValue:
        return area_param.AsDouble()
    for p in panel.Parameters:
        if p.Definition.Name == "Area" and p.StorageType == DB.StorageType.Double:
            return p.AsDouble()
    return 0.0

# ─── 5. Process each curtain wall ─────────────────────────────────────────────
TARGET_TYPE  = "Cladding System"
TARGET_PARAM = "Cladding System Area"

updated = 0
skipped = 0
errors  = []

with revit.Transaction("Set Cladding System Area"):
    for wall in curtain_walls:
        wall_id = wall.Id.IntegerValue

        cw_grid = wall.CurtainGrid
        if cw_grid is None:
            logger.debug("Wall {} has no CurtainGrid – skipped.".format(wall_id))
            skipped += 1
            continue

        panel_ids = cw_grid.GetPanelIds()

        total_area_ft2 = 0.0
        matched = 0

        for pid in panel_ids:
            panel = doc.GetElement(pid)
            if panel is None:
                continue

            type_elem = doc.GetElement(panel.GetTypeId())
            if type_elem is None:
                continue

            type_name_param = type_elem.get_Parameter(
                DB.BuiltInParameter.ALL_MODEL_TYPE_NAME
            )
            type_name_str = (
                type_name_param.AsString()
                if type_name_param is not None
                else type_elem.Name
            )

            if type_name_str == TARGET_TYPE:
                area = get_panel_area(panel)
                if area == 0.0:
                    continue
                total_area_ft2 += area
                matched += 1

        if matched == 0:
            logger.debug(
                "Wall {} – no '{}' panels found.".format(wall_id, TARGET_TYPE)
            )
            skipped += 1
            continue

        target_p = wall.LookupParameter(TARGET_PARAM)

        if target_p is None:
            msg = "Wall {} – parameter '{}' not found.".format(wall_id, TARGET_PARAM)
            logger.warning(msg)
            errors.append(msg)
            continue

        if target_p.IsReadOnly:
            msg = "Wall {} – parameter '{}' is read-only.".format(wall_id, TARGET_PARAM)
            logger.warning(msg)
            errors.append(msg)
            continue

        target_p.Set(total_area_ft2)
        updated += 1
        output.print_md(
            "✅ Wall `{}` → **{} panel(s)** · area = `{:.2f} m²`".format(
                wall_id, matched, total_area_ft2 * 0.0929
            )
        )

# ─── 6. Summary ───────────────────────────────────────────────────────────────
output.print_md("---")
output.print_md(
    "**Done.** {} wall(s) updated · {} skipped · {} error(s).".format(
        updated, skipped, len(errors)
    )
)
if errors:
    output.print_md("### Warnings")
    for e in errors:
        output.print_md("- " + e)