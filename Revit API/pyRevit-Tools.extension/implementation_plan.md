# Point Cloud → Revit MEP Automation (Electrical Conduit & Plumbing) pyRevit Plugin Plan

## Overview
This document outlines the detailed architecture and implementation plan for creating a pyRevit plugin extension for **Point Cloud to MEP Automation (Electrical Conduit & Plumbing)** in Revit.

Based on the research specification ([point-cloud-to-mep-automation-spec.md](file:///c:/Users/TahirSanwarwala/AppData/Roaming/Github_Tahir/BIM_Automation_Tools/Revit%20API/pyRevit-Tools.extension/Tahir_Tools.tab/point-cloud-to-mep-automation-spec.md)), the implementation will follow **Option A (pyRevit script using the CPython3 engine)** with a decoupled core processing library placed in `lib/Tahir/pointcloud/`.

---

## Architecture & Modular Design

```
pyRevit-Tools.extension/
├── lib/
│   └── Tahir/
│       └── pointcloud/                <-- Decoupled Core Library (Pure Python + Open3D + Numpy)
│           ├── __init__.py
│           ├── extractor.py           <-- Revit Point Cloud API reading & coordinate translation
│           ├── processor.py           <-- Open3D filter, DBSCAN, PCA, Cylinder RANSAC
│           ├── mep_sizes.py           <-- Standard EMT/RMC/PVC & Pipe trade size snapping rules
│           └── qa.py                  <-- Scan-vs-BIM centerline deviation calculation
└── Tahir_Tools.tab/
    └── PointCloudMEP.panel/           <-- New pyRevit Panel
        ├── EnvironmentCheck.pushbutton/ <-- Tool 0: Verify Python 3, Open3D, Numpy setup
        │   ├── script.py
        │   └── icon.png
        ├── ScanQA.pushbutton/         <-- Tool 1 (Phase 1): Scan vs. BIM Deviation QA Tool
        │   ├── script.py
        │   └── icon.png
        └── StraightRunGenerator.pushbutton/ <-- Tool 2 (Phase 2): Semi-Auto Conduit/Pipe Generator
            ├── script.py
            └── icon.png
```

---

## User Review Required

> [!IMPORTANT]
> **CPython Engine & Open3D Dependency Setup**
> pyRevit buttons using `#! python3` rely on a local CPython environment configured in pyRevit settings. `open3d`, `numpy`, and `scipy` must be installed in that CPython environment (`pip install open3d numpy scipy`). We will include an **Environment Diagnostic Tool** (`EnvironmentCheck.pushbutton`) as step 1 to automate validation and installation guidance.

> [!NOTE]
> **Semi-Automated Scope (Phase 1 & Phase 2)**
> As decided in the spec, elbow/tee fitting auto-detection is out of scope for the initial release due to scan noise and line-of-sight occlusion. Phase 1 focuses on the **Scan-vs-BIM Deviation/QA Tool**, and Phase 2 focuses on **Semi-Automated Straight-Run Conduit/Pipe Generation** with user confirmation UI before element creation.

---

## Open Questions

> [!NOTE]
> 1. **Revit Version Target**: Are you running Revit 2023, 2024, or 2025? (Revit API parameter access for Conduit/Pipe sizes varies slightly across versions).
> 2. **Default MEP Trade Size Table**: Do you want trade size snapping to read dynamically from the active Revit Project Routing Preferences / Pipe & Conduit Settings, or use built-in standard lookup tables (e.g. EMT 1/2", 3/4", 1", 1-1/4", 1-1/2", 2", 3", 4")?

---

## Proposed Changes

### Core Library Component (`lib/Tahir/pointcloud/`)

#### [NEW] [__init__.py](file:///c:/Users/TahirSanwarwala/AppData/Roaming/Github_Tahir/BIM_Automation_Tools/Revit%20API/pyRevit-Tools.extension/lib/Tahir/pointcloud/__init__.py)
Exposes public API for point cloud processing module.

#### [NEW] [extractor.py](file:///c:/Users/TahirSanwarwala/AppData/Roaming/Github_Tahir/BIM_Automation_Tools/Revit%20API/pyRevit-Tools.extension/lib/Tahir/pointcloud/extractor.py)
- Wraps `PointCloudInstance.GetPoints()` with `PointCloudFilter.CreateWithBoundingBox()`.
- Converts Revit API `XYZ` points to numpy arrays `np.ndarray` float64.
- Handles coordinate transformations (Internal Origin vs. Survey Point / Shared Coordinates).

#### [NEW] [processor.py](file:///c:/Users/TahirSanwarwala/AppData/Roaming/Github_Tahir/BIM_Automation_Tools/Revit%20API/pyRevit-Tools.extension/lib/Tahir/pointcloud/processor.py)
- `voxel_downsample(points_np, voxel_size=0.02)`: Open3D downsampling to reduce scan point density.
- `remove_statistical_outliers(pcd_o3d, nb_neighbors=20, std_ratio=2.0)`: Cleans hangers, walls, and stray noise.
- `cluster_dbscan(pcd_o3d, eps=0.08, min_points=15)`: Isolates distinct pipe/conduit runs into separate clusters without needing predefined cluster count `k`.
- `fit_pca_axis(cluster_points_np)`: Primary eigenvector computation via SVD (`np.linalg.svd`) for axis vector and initial radial estimate.
- `fit_cylinder_ransac(cluster_points_np, max_iterations=1000, distance_threshold=0.01)`: Custom RANSAC cylinder model estimating cylinder center line start/end, direction vector, and radius.

#### [NEW] [mep_sizes.py](file:///c:/Users/TahirSanwarwala/AppData/Roaming/Github_Tahir/BIM_Automation_Tools/Revit%20API/pyRevit-Tools.extension/lib/Tahir/pointcloud/mep_sizes.py)
- Standard trade size tables for Electrical Conduit (EMT, RMC, PVC) and Plumbing Pipes (Carbon Steel, Copper, PVC).
- `snap_to_trade_size(fitted_radius_ft, mep_domain='conduit')`: Snaps raw scan-fitted radius to standard trade diameter.

#### [NEW] [qa.py](file:///c:/Users/TahirSanwarwala/AppData/Roaming/Github_Tahir/BIM_Automation_Tools/Revit%20API/pyRevit-Tools.extension/lib/Tahir/pointcloud/qa.py)
- Computes perpendicular distances from point cloud points to selected Revit Pipe/Conduit centerlines (`Curve.Distance()`).
- Calculates Min, Max, Mean, and StdDev deviation values.

---

### pyRevit UI Panel & Pushbuttons (`Tahir_Tools.tab/PointCloudMEP.panel/`)

#### [NEW] [EnvironmentCheck.pushbutton/script.py](file:///c:/Users/TahirSanwarwala/AppData/Roaming/Github_Tahir/BIM_Automation_Tools/Revit%20API/pyRevit-Tools.extension/Tahir_Tools.tab/PointCloudMEP.panel/EnvironmentCheck.pushbutton/script.py)
- `#! python3` script checking Python version, `open3d`, `numpy`, `scipy`, and pyRevit CPython engine status.
- Displays WPF alert dialog summarizing health status and standard `pip install` commands if packages are missing.

#### [NEW] [ScanQA.pushbutton/script.py](file:///c:/Users/TahirSanwarwala/AppData/Roaming/Github_Tahir/BIM_Automation_Tools/Revit%20API/pyRevit-Tools.extension/Tahir_Tools.tab/PointCloudMEP.panel/ScanQA.pushbutton/script.py)
- Tool 1 (Phase 1): User selects one or more modeled pipes/conduits and a linked Point Cloud Instance.
- Extracts scan points in proximity buffer around the centerlines.
- Computes deviation stats and presents a WPF results dialog (with tolerance thresholds, e.g. <1/4", <1/2", >1").
- Highlights high-deviation zones using Revit Analysis Visualization Framework (AVF) or temporary detail lines.

#### [NEW] [StraightRunGenerator.pushbutton/script.py](file:///c:/Users/TahirSanwarwala/AppData/Roaming/Github_Tahir/BIM_Automation_Tools/Revit%20API/pyRevit-Tools.extension/Tahir_Tools.tab/PointCloudMEP.panel/StraightRunGenerator.pushbutton/script.py)
- Tool 2 (Phase 2): Prompt user to pick a Box / Selection region of the point cloud.
- Runs complete core algorithm pipeline: Downsample → Clean Outliers → DBSCAN → PCA / Cylinder RANSAC → Trade Size Snapping.
- Opens a pyRevit WPF preview dialog listing detected candidate runs (Endpoint 1, Endpoint 2, Fitted Radius, Snapped Trade Diameter, Confidence Score).
- On user confirmation, executes a Revit Transaction using `Conduit.Create()` or `Pipe.Create()`.

---

## Build & Phased Implementation Strategy

### Step 1: Environment Diagnostic & Core Library Foundations
1. Create `lib/Tahir/pointcloud/` structure.
2. Build `EnvironmentCheck.pushbutton` to verify Open3D and CPython integration inside Revit.
3. Build unit test script in `scratch/` to test `processor.py` math against synthetic cylinder point cloud data.

### Step 2: Phase 1 — Point Cloud vs. MEP Deviation QA Tool (`ScanQA`)
1. Implement `extractor.py` and `qa.py`.
2. Build `ScanQA.pushbutton` pyRevit UI.
3. Test against sample Revit project with linked point cloud.

### Step 3: Phase 2 — Semi-Automated Straight-Run Generator (`StraightRunGenerator`)
1. Implement DBSCAN clustering and custom cylinder RANSAC in `processor.py`.
2. Implement trade size snapping in `mep_sizes.py`.
3. Create WPF confirmation UI for candidate runs.
4. Wire up `Conduit.Create` / `Pipe.Create` Revit transactions.

---

## Verification Plan

### Automated / Synthetic Tests
- Run offline Python test script in `scratch/test_pointcloud.py` using standard CPython interpreter:
  - Generate synthetic cylinder point cloud (noisy radius 1.5", 10ft length, rotated randomly in 3D).
  - Verify DBSCAN clusters cylinder out of noise.
  - Verify PCA & Cylinder RANSAC extract centerline vector within <0.05 ft error and radius within <0.05" error.
  - Verify trade size snapping returns exactly 1.5" EMT.

### Manual Verification in Revit
1. Open Revit with linked `.rcp` / `.rcs` Point Cloud instance.
2. Run `EnvironmentCheck` button -> Verify green checkmarks for CPython 3, Open3D, and Numpy.
3. Run `ScanQA` button -> Select existing conduit -> Verify distance metrics report accuracy within expected tolerance.
4. Run `StraightRunGenerator` button -> Pick region -> Verify candidate preview -> Confirm -> Check created `Conduit` / `Pipe` element in 3D view.
