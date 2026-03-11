# Datum Tools — Annotation Panel

Three tools for cleaning up how **Levels** and **Grids** look in your Revit views. Find them in the **Annotation** panel of the **CSharp_Tools** tab.

---

## Switch Bubbles

**What it does:** Turns datum bubbles on or off at either end of selected Levels or Grids — without having to click each one individually in the view.

**How to use:**
1. Select one or more Levels or Grids in the active view (you can also pre-select before clicking the button).
2. Click **Switch Bubbles**.
3. In the dialog, choose which end to toggle: **End 1**, **End 2**, or **Both**.
4. The bubbles are turned on or off based on their current state.

---

## Add Elbows

**What it does:** Adds a kink (elbow) to the leader line on Level heads, keeping annotations tidy and preventing overlaps.

**How to use:**
1. Select one or more Levels in the active view.
2. Click **Add Elbows**.
3. The tool finds which end of each Level has a visible bubble and adds an elbow there automatically. If an elbow already exists but is flat, it adjusts it.

> **Tip:** Works best in section or elevation views where Level heads are visible.

---

## Align Elbows

**What it does:** Copies the elbow position from one Level onto others, so all your Level leaders line up neatly.

**How to use:**
1. Click **Align Elbows**.
2. Click the **source** Level — the one whose elbow position you want to match.
3. Click one or more **target** Levels. Their leader elbows and ends are moved to match the source.

> Each target Level keeps its own elevation — only the horizontal leader geometry is adjusted.
