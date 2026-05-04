using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using System;
using System.Collections.Generic;
using System.Linq;

namespace CSharp_Tools.Commands
{
    [Transaction(TransactionMode.Manual)]
    public class TestScript : IExternalCommand
    {
        // max gap we'll try to close automatically, in feet (~30mm)
        const double GapAllowance = 0.1;

        public Result Execute(ExternalCommandData commandData, ref string message, ElementSet elements)
        {
            UIApplication uiApp = commandData.Application;
            UIDocument uiDoc = uiApp.ActiveUIDocument;
            Document doc = uiDoc.Document;

            var walls = new FilteredElementCollector(doc, uiDoc.ActiveView.Id)
                .OfClass(typeof(Wall))
                .Cast<Wall>()
                .Where(w => w.Location is LocationCurve)
                .ToList();

            if (walls.Count == 0)
            {
                TaskDialog.Show("Wall Cleanup", "No walls found in the model.");
                return Result.Cancelled;
            }

            int joined = 0;
            int extended = 0;
            int skipped = 0;

            using (Transaction tx = new Transaction(doc, "Wall Junction Cleanup"))
            {
                tx.Start();

                for (int i = 0; i < walls.Count; i++)
                {
                    Wall wallA = walls[i];
                    LocationCurve locA = wallA.Location as LocationCurve;
                    if (locA == null) continue;

                    for (int j = i + 1; j < walls.Count; j++)
                    {
                        Wall wallB = walls[j];
                        LocationCurve locB = wallB.Location as LocationCurve;
                        if (locB == null) continue;

                        if (wallA.LevelId != wallB.LevelId) continue;
                        if (JoinGeometryUtils.AreElementsJoined(doc, wallA, wallB)) continue;
                        if (!WallsShouldBeJoined(wallA, wallB, locA, locB)) continue;

                        try
                        {
                            bool gapClosed = TryCloseGap(wallA, wallB, locA, locB);

                            if (gapClosed)
                            {
                                // re-fetch curves since we may have moved a wall
                                locA = wallA.Location as LocationCurve;
                                locB = wallB.Location as LocationCurve;
                            }

                            JoinGeometryUtils.JoinGeometry(doc, wallA, wallB);

                            // only count here - after the join actually succeeded
                            joined++;
                            if (gapClosed) extended++;
                        }
                        catch
                        {
                            // geometry issues Revit won't let us fix automatically
                            skipped++;
                        }
                    }
                }

                tx.Commit();
            }

            string report = $"Done.\n\nJoined: {joined}\nGaps closed: {extended}\nSkipped: {skipped}";
            TaskDialog.Show("Wall Junction Cleanup", report);

            return Result.Succeeded;
        }

        // before joining, physically close gaps so walls actually intersect.
        // without this, Revit joins them but flags a warning about non-intersecting elements.
        private bool TryCloseGap(Wall wallA, Wall wallB, LocationCurve locA, LocationCurve locB)
        {
            double hwA = wallA.Width / 2.0;
            double hwB = wallB.Width / 2.0;

            XYZ a0 = locA.Curve.GetEndPoint(0);
            XYZ a1 = locA.Curve.GetEndPoint(1);
            XYZ b0 = locB.Curve.GetEndPoint(0);
            XYZ b1 = locB.Curve.GetEndPoint(1);

            // T-junction: extend the incoming wall endpoint to touch the other wall's face
            if (ExtendToFace(locA, 0, a0, locB.Curve, hwB)) return true;
            if (ExtendToFace(locA, 1, a1, locB.Curve, hwB)) return true;
            if (ExtendToFace(locB, 0, b0, locA.Curve, hwA)) return true;
            if (ExtendToFace(locB, 1, b1, locA.Curve, hwA)) return true;

            // end-to-end: snap both endpoints to their midpoint
            XYZ[] ptA = { a0, a1 };
            XYZ[] ptB = { b0, b1 };
            for (int ia = 0; ia < 2; ia++)
                for (int ib = 0; ib < 2; ib++)
                    if (ptA[ia].DistanceTo(ptB[ib]) < GapAllowance)
                    {
                        XYZ mid = (ptA[ia] + ptB[ib]) / 2.0;
                        XYZ otherA = locA.Curve.GetEndPoint(ia == 0 ? 1 : 0);
                        XYZ otherB = locB.Curve.GetEndPoint(ib == 0 ? 1 : 0);
                        locA.Curve = ia == 0 ? Line.CreateBound(mid, otherA) : Line.CreateBound(otherA, mid);
                        locB.Curve = ib == 0 ? Line.CreateBound(mid, otherB) : Line.CreateBound(otherB, mid);
                        return true;
                    }

            return false;
        }

        // extends one end of a wall so it touches the face of the receiving wall.
        // Project() returns distance to the centreline, so we subtract the half-width
        // to get the actual gap between the endpoint and the wall face.
        private bool ExtendToFace(LocationCurve loc, int epIdx, XYZ endpt, Curve otherCurve, double halfWidth)
        {
            var proj = otherCurve.Project(endpt);
            if (proj == null) return false;

            double gap = proj.Distance - halfWidth;
            if (gap <= 0 || gap > GapAllowance) return false;

            // reject if the projection is past either end of the receiving wall
            double p = proj.Parameter;
            if (p <= otherCurve.GetEndParameter(0) + 0.01 || p >= otherCurve.GetEndParameter(1) - 0.01)
                return false;

            XYZ dir    = (endpt - proj.XYZPoint).Normalize();
            XYZ target = proj.XYZPoint + dir * halfWidth;
            XYZ other  = loc.Curve.GetEndPoint(epIdx == 0 ? 1 : 0);

            loc.Curve = epIdx == 0 ? Line.CreateBound(target, other) : Line.CreateBound(other, target);
            return true;
        }

        private bool WallsShouldBeJoined(Wall wallA, Wall wallB, LocationCurve locA, LocationCurve locB)
        {
            if (wallA.WallType.Kind == WallKind.Curtain || wallB.WallType.Kind == WallKind.Curtain)
                return false;

            XYZ a0 = locA.Curve.GetEndPoint(0);
            XYZ a1 = locA.Curve.GetEndPoint(1);
            XYZ b0 = locB.Curve.GetEndPoint(0);
            XYZ b1 = locB.Curve.GetEndPoint(1);

            // don't try to join walls that are clearly on different elevations
            if (Math.Abs(a0.Z - b0.Z) > GapAllowance * 2) return false;

            // end-to-end corners
            if (a0.DistanceTo(b0) < GapAllowance || a0.DistanceTo(b1) < GapAllowance ||
                a1.DistanceTo(b0) < GapAllowance || a1.DistanceTo(b1) < GapAllowance)
                return true;

            // T-junctions - endpoint near or touching the face of the other wall
            double hwA = wallA.Width / 2.0;
            double hwB = wallB.Width / 2.0;

            if (PointNearCurve(a0, locB.Curve, hwB + GapAllowance)) return true;
            if (PointNearCurve(a1, locB.Curve, hwB + GapAllowance)) return true;
            if (PointNearCurve(b0, locA.Curve, hwA + GapAllowance)) return true;
            if (PointNearCurve(b1, locA.Curve, hwA + GapAllowance)) return true;

            return false;
        }

        private bool PointNearCurve(XYZ point, Curve curve, double tolerance)
        {
            var result = curve.Project(point);
            if (result == null || result.Distance > tolerance) return false;

            double p = result.Parameter;
            return p > curve.GetEndParameter(0) + 0.01 && p < curve.GetEndParameter(1) - 0.01;
        }
    }
}