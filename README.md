# Mapper

Mapper authors, reviews and exchanges relationships between BIM elements and construction schedule activities. This is a standalone product repository; its current application runs **inside Autodesk Revit through pyRevit**, not as a separate executable.

MS-0 and MS-1 are accepted by the Product Owner. UI-01 adds WBS → Activities navigation; its automated verification is complete and Revit Desktop acceptance remains pending. See [status](docs/mapping/STATUS.md) for the authoritative acceptance ledger.

## Supported pilot

- P6 Professional V24.12 XML import with one project/schedule snapshot per working document.
- Native host Walls, Floors, Structural Columns and Structural Framing.
- Many-to-many assignment, relationship review, native selection, reassignment, notes, individual removal and session undo.
- External working files, automatic save per edit, previous-revision recovery, validation and renderer-independent exchange.
- WBS hierarchy, expand/collapse, Thai/English text and search retaining hierarchy context.

## Install and start

1. Use the complete repository at the accepted baseline plus the reviewed UI-01 overlay. Copy `MappingAuthoring.extension` into `%APPDATA%\pyRevit\Extensions`; avoid duplicate copies.
2. Reload pyRevit in the accepted Revit 2026.1 / IronPython 2.7 environment. Open a saved, unmodified, non-workshared host model.
3. Choose Mapping → Authoring → Mapping. Create a work file with **New + Import P6**, or **Open work** to continue.
4. Expand WBS headings and select an Activity. Select native elements, click **Use current selection**, then **Add to target activity**. Additional activities preserve existing relationships.
5. Review relationships, Save / Check, Validate and Export. Close work before copying backups.

Full [installation and usage](docs/mapping/INSTALL_AND_DESKTOP_ACCEPTANCE.txt), [UI-01 desktop checklist](docs/mapping/UI01_DESKTOP_ACCEPTANCE.txt), and [documentation index](docs/mapping/README.md).

## Limits

One local writer; local NTFS working storage; saved non-workshared host only. No linked-model authoring, MSP, automatic schedule migration, geometry splitting or viewer. Exchange contains no geometry or IFC crosswalk. Native identity resolution never substitutes a replacement element. A file copy can retain native identity: explicit logical-model lineage confirmation remains necessary.

## Engineering

Run `python -m unittest discover -s tests/mapping -v` from the repository root (CPython 3.9+). The public fixture is synthetic. One optional original-project test is skipped unless `MAPPER_REAL_P6` points to the exact MS-0 `009_P6.xml`; that private source is not distributed.

Read [engineering workflow](docs/ENGINEERING.md) and [architecture/data contracts](docs/mapping/CONTRACTS.md) before editing. Work performs no Git operations; the Coordinator owns integration. Future work requires separate PO authorization.

## License

No license selected. All rights reserved unless an explicit license is added.
