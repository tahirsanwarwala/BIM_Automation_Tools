# -*- coding: utf-8 -*-
"""
Revit Point Cloud Extraction Utilities.
Reads scan points from a PointCloudInstance using the Revit API.

Runs on pyRevit's IronPython engine, so this module is deliberately
NUMPY-FREE and returns plain Python lists of (x, y, z) tuples. Importing
numpy here would force the CPython engine to initialise inside Revit, which
in turn makes pyRevit's Reload fail: tearing that engine down walks its
tracked CLR wrappers and throws if any wrapped Document has gone invalid.
All array maths lives in the external engine venv or in pure Python.

Key API facts (verified against RevitAPI.xml, Revit 2025):
  - PointCloudFilter / PointCloudFilterFactory live in the nested namespace
    Autodesk.Revit.DB.PointClouds - NOT Autodesk.Revit.DB.
  - PointCloudFilterFactory.CreateMultiPlaneFilter(IList<Plane>) keeps points
    on the POSITIVE side of every plane, so plane normals must point INWARD,
    toward the interior of the volume of interest.
  - PointCloudInstance.GetPoints(filter, averageDistance, numPoints) has a
    single overload, and the filter must be expressed in MODEL coordinates.
    The returned CloudPoints, however, are in the instance's OWN coordinate
    system, so Instance.GetTransform() must be applied to get model coords.
    (PointCloudInstance derives from Instance, so GetTransform is inherited -
    it is absent from RevitAPI.xml, which lists only declared members.)
"""

try:
    import clr
    # Load the assembly here rather than relying on the calling script: this
    # module is imported by tools that never call AddReference themselves.
    clr.AddReference('RevitAPI')
    from Autodesk.Revit.DB import XYZ, Plane, Transform, BoundingBoxXYZ
    from Autodesk.Revit.DB.PointClouds import PointCloudFilterFactory
    HAS_REVIT = True
except ImportError as _import_exc:
    # Recorded so a missing/renamed Revit API type surfaces instead of
    # silently degrading into "no scan data" for every element.
    IMPORT_ERROR = str(_import_exc)
    HAS_REVIT = False


def _make_bbox_filter(bbox):
    """
    Create a PointCloudFilter for a BoundingBoxXYZ using 6 clipping planes.

    The Revit API has no CreateWithBoundingBox(); the box is expressed as the
    intersection of 6 positive half-spaces. Normals point INWARD, per
    CreateMultiPlaneFilter's documented behaviour.

    Args:
        bbox (BoundingBoxXYZ): Axis-aligned bounding box in model coordinates.

    Returns:
        PointCloudFilter for the given box volume.
    """
    min_pt = bbox.Min
    max_pt = bbox.Max

    planes = [
        # Plane x = max_x, interior lies toward -X
        Plane.CreateByNormalAndOrigin(XYZ(-1, 0, 0), XYZ(max_pt.X, 0, 0)),
        # Plane x = min_x, interior lies toward +X
        Plane.CreateByNormalAndOrigin(XYZ(1, 0, 0), XYZ(min_pt.X, 0, 0)),
        Plane.CreateByNormalAndOrigin(XYZ(0, -1, 0), XYZ(0, max_pt.Y, 0)),
        Plane.CreateByNormalAndOrigin(XYZ(0, 1, 0), XYZ(0, min_pt.Y, 0)),
        Plane.CreateByNormalAndOrigin(XYZ(0, 0, -1), XYZ(0, 0, max_pt.Z)),
        Plane.CreateByNormalAndOrigin(XYZ(0, 0, 1), XYZ(0, 0, min_pt.Z)),
    ]

    from System.Collections.Generic import List
    plane_list = List[Plane]()
    for p in planes:
        plane_list.Add(p)

    return PointCloudFilterFactory.CreateMultiPlaneFilter(plane_list)


def _points_to_list(point_collection, transform=None):
    """
    Convert a Revit PointCollection to a list of (x, y, z) tuples in model
    coordinates.

    The filter passed to GetPoints() is in model coordinates, but the returned
    CloudPoints are in the point cloud instance's own coordinate system. The
    instance transform (local -> model) must be applied, otherwise every point
    sits at the instance offset distance from the element and deviations come
    out in hundreds of feet.

    The transform is applied as a plain basis multiplication rather than
    per-point Transform.OfPoint() calls, which matters at 10k-100k points:
    OfPoint crosses the managed/native boundary every time.

    Args:
        point_collection: Result of PointCloudInstance.GetPoints().
        transform:        Revit Transform (local -> model), or None.

    Returns:
        list[tuple]: (x, y, z) tuples in Revit model coordinates.
    """
    if point_collection is None or point_collection.Count == 0:
        return []

    if transform is None or transform.IsIdentity:
        return [(p.X, p.Y, p.Z) for p in point_collection]

    bx, by, bz = transform.BasisX, transform.BasisY, transform.BasisZ
    org = transform.Origin
    bxx, bxy, bxz = bx.X, bx.Y, bx.Z
    byx, byy, byz = by.X, by.Y, by.Z
    bzx, bzy, bzz = bz.X, bz.Y, bz.Z
    ox, oy, oz = org.X, org.Y, org.Z

    # model = origin + lx*BasisX + ly*BasisY + lz*BasisZ
    out = []
    append = out.append
    for p in point_collection:
        lx, ly, lz = p.X, p.Y, p.Z
        append((
            ox + lx * bxx + ly * byx + lz * bzx,
            oy + lx * bxy + ly * byy + lz * bzy,
            oz + lx * bxz + ly * byz + lz * bzz,
        ))
    return out


def extract_points_bbox(pc_instance, bbox_world,
                        average_distance=0.01, max_points=200000):
    """
    Extract point cloud points within a model-space bounding box.

    Args:
        pc_instance:      Revit PointCloudInstance element.
        bbox_world:       BoundingBoxXYZ in Revit model coordinates.
        average_distance: Desired point spacing (feet). Smaller = denser.
        max_points:       Maximum point count cap (1 to 1000000).

    Returns:
        list[tuple]: (x, y, z) points in model coordinates.
    """
    if not HAS_REVIT:
        raise RuntimeError(
            "Revit point cloud API unavailable: {}".format(
                globals().get('IMPORT_ERROR', 'unknown import failure'))
        )

    if pc_instance is None:
        return []

    # PointCloudInstance derives from Instance, so GetTransform() gives the
    # instance's local -> model transform.
    transform = pc_instance.GetTransform() if hasattr(
        pc_instance, 'GetTransform') else None

    pc_filter = _make_bbox_filter(bbox_world)
    pts = pc_instance.GetPoints(pc_filter, average_distance, max_points)

    return _points_to_list(pts, transform)


def extract_points_near_curve(pc_instance, curve,
                              buffer_ft=2.0,
                              average_distance=0.01,
                              max_points=100000):
    """
    Extract points in a box around a Revit curve (pipe/conduit centerline).

    Args:
        pc_instance:      Revit PointCloudInstance.
        curve:            Revit Curve (e.g. from LocationCurve).
        buffer_ft:        Buffer padding around the curve extents (feet).
        average_distance: Point spacing (feet).
        max_points:       Max point cap.

    Returns:
        list[tuple]: (x, y, z) points in model coordinates.
    """
    if not HAS_REVIT:
        raise RuntimeError(
            "Revit point cloud API unavailable: {}".format(
                globals().get('IMPORT_ERROR', 'unknown import failure'))
        )

    if pc_instance is None or curve is None:
        return []

    p0 = curve.GetEndPoint(0)
    p1 = curve.GetEndPoint(1)

    bbox = BoundingBoxXYZ()
    bbox.Min = XYZ(
        min(p0.X, p1.X) - buffer_ft,
        min(p0.Y, p1.Y) - buffer_ft,
        min(p0.Z, p1.Z) - buffer_ft,
    )
    bbox.Max = XYZ(
        max(p0.X, p1.X) + buffer_ft,
        max(p0.Y, p1.Y) + buffer_ft,
        max(p0.Z, p1.Z) + buffer_ft,
    )

    return extract_points_bbox(
        pc_instance, bbox,
        average_distance=average_distance,
        max_points=max_points,
    )


def bbox_to_model_aabb(bbox):
    """
    Convert a BoundingBoxXYZ that carries a Transform into an axis-aligned
    box in MODEL coordinates.

    A View3D section box and a View crop box are both expressed in the view's
    own coordinate system, with the mapping held in bbox.Transform. Using
    their Min/Max directly is only correct when that transform is identity -
    a rotated section box or a view with a rotated crop region would otherwise
    produce a query box in the wrong place, silently returning the wrong
    points (or none).

    Args:
        bbox (BoundingBoxXYZ): Box possibly expressed in view coordinates.

    Returns:
        BoundingBoxXYZ in model coordinates (the input, if already identity).
    """
    if bbox is None:
        return None

    transform = getattr(bbox, 'Transform', None)
    if transform is None or transform.IsIdentity:
        return bbox

    return _transform_bbox(bbox, transform)


def _transform_bbox(bbox, transform):
    """Transform a BoundingBoxXYZ by a Revit Transform (AABB of corners)."""
    corners = [
        XYZ(bbox.Min.X, bbox.Min.Y, bbox.Min.Z),
        XYZ(bbox.Min.X, bbox.Min.Y, bbox.Max.Z),
        XYZ(bbox.Min.X, bbox.Max.Y, bbox.Min.Z),
        XYZ(bbox.Min.X, bbox.Max.Y, bbox.Max.Z),
        XYZ(bbox.Max.X, bbox.Min.Y, bbox.Min.Z),
        XYZ(bbox.Max.X, bbox.Min.Y, bbox.Max.Z),
        XYZ(bbox.Max.X, bbox.Max.Y, bbox.Min.Z),
        XYZ(bbox.Max.X, bbox.Max.Y, bbox.Max.Z),
    ]
    tc = [transform.OfPoint(c) for c in corners]

    new_bbox = BoundingBoxXYZ()
    new_bbox.Min = XYZ(
        min(c.X for c in tc),
        min(c.Y for c in tc),
        min(c.Z for c in tc),
    )
    new_bbox.Max = XYZ(
        max(c.X for c in tc),
        max(c.Y for c in tc),
        max(c.Z for c in tc),
    )
    return new_bbox
