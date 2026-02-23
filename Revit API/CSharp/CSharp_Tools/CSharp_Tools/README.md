# CSharp_Tools — Revit Add-in

A Revit add-in (C# / Revit API 2022–2026) that extends the ribbon with productivity tools grouped by function.

---

## Ribbon Layout

The add-in adds a **CSharp_Tools** tab with a **Deploy** panel containing:

| Ribbon Item | Type | Description |
|---|---|---|
| **Datum Tools** | Pulldown | Switch, add, and align datum bubble leaders on Levels & Grids |
| **Multi-Level Select** | Pulldown | Select similar elements across multiple views or levels |
| **Sheets from Excel** | Push button | Bulk-create Revit sheets from an Excel file |

---

## Project Structure

```
CSharp_Tools/
├── Application.cs              Entry point — builds the ribbon on Revit startup
├── CSharp_Tools.addin          Revit add-in manifest
├── CSharp_Tools.csproj         Project file
│
└── Tools/
    ├── DatumTools/             ← Datum Tools pulldown
    │   ├── README.md
    │   ├── Commands/
    │   ├── Dialogs/
    │   └── Icons/
    │
    ├── MultiLevelSelect/       ← Multi-Level Select pulldown
    │   ├── README.md
    │   ├── Commands/
    │   ├── Dialogs/
    │   └── Icons/
    │
    └── SheetsFromExcel/        ← Sheets from Excel push button
        ├── README.md
        ├── Commands/
        ├── Dialogs/
        ├── Models/
        └── Icons/
```

---

## Feature Documentation

| Feature | README |
|---|---|
| Datum Tools | [Tools/DatumTools/README.md](Tools/DatumTools/README.md) |
| Multi-Level Select | [Tools/MultiLevelSelect/README.md](Tools/MultiLevelSelect/README.md) |
| Sheets from Excel | [Tools/SheetsFromExcel/README.md](Tools/SheetsFromExcel/README.md) |

---

## Requirements

- Autodesk Revit **2022 – 2026**
- .NET Framework 4.8 (as required by Revit)
- Build with **Visual Studio 2022** or the [Nice3point.Revit.Sdk](https://github.com/Nice3point/RevitToolkit) MSBuild SDK

## Building

Open `CSharp_Tools.sln` in Visual Studio, select the desired configuration (e.g. `Debug.R24`), and build. The `.addin` manifest and DLL are automatically deployed to the Revit Add-ins folder.
