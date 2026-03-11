# CSharp Tools — Revit Add-in

A set of productivity tools for Revit, available directly in the **CSharp_Tools** ribbon tab. No scripts to run — just click a button and go.

---

## What's in the Ribbon

The add-in adds a **CSharp_Tools** tab with three panels:

| Panel | Buttons | What it does |
|---|---|---|
| **Annotation** | Switch Bubbles, Add Elbows, Align Elbows | Tools for tidying up Level and Grid annotations |
| **Selection** | Match by View, Match by Model | Select the same element type across multiple views or levels at once |
| **Sheets** | Sheets from Excel | Create Revit sheets in bulk from a spreadsheet |

---

## Tools at a Glance

### 📐 Annotation Panel
Tools for managing how Levels and Grids look in your drawings.

- **Switch Bubbles** — Turn datum bubbles on or off at either end of Levels or Grids.
- **Add Elbows** — Add a leader elbow to Level heads so they don't overlap other annotations.
- **Align Elbows** — Line up multiple Level elbows to match one another in a single click.

### 🔍 Selection Panel
Go beyond Revit's built-in "Select All Instances" with more control over where you're selecting.

- **Match by View** — Select elements of the same type across specific views you choose.
- **Match by Model** — Select elements of the same type across specific levels in the model.

### 📄 Sheets Panel
- **Sheets from Excel** — Point the tool at an Excel file and it creates all your sheets automatically.

---

## Folder Structure

```
CSharp_Tools/
├── Application.cs              Builds the ribbon tab and buttons on Revit startup
├── CSharp_Tools.addin          Revit add-in registration file
├── CSharp_Tools.csproj         Visual Studio project file
│
└── Tools/
    ├── DatumTools/             Annotation panel tools
    │   ├── README.md
    │   ├── Commands/
    │   ├── Dialogs/
    │   └── Icons/
    │
    ├── MultiLevelSelect/       Selection panel tools
    │   ├── README.md
    │   ├── Commands/
    │   ├── Dialogs/
    │   └── Icons/
    │
    └── SheetsFromExcel/        Sheets panel tool
        ├── README.md
        ├── Commands/
        ├── Dialogs/
        ├── Models/
        └── Icons/
```

---

## Detailed Documentation

| Tool | README |
|---|---|
| Annotation Tools | [Tools/DatumTools/README.md](Tools/DatumTools/README.md) |
| Selection Tools | [Tools/MultiLevelSelect/README.md](Tools/MultiLevelSelect/README.md) |
| Sheets from Excel | [Tools/SheetsFromExcel/README.md](Tools/SheetsFromExcel/README.md) |

---

## Requirements

- Autodesk Revit **2022 – 2026**
- Built and tested with Visual Studio 2022

## Building from Source

Open `CSharp_Tools.slnx` in Visual Studio, select your target configuration (e.g. `Debug.R24`), and build. The add-in files are automatically copied to your Revit Add-ins folder.
