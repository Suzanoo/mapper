# Architecture and data contracts

This describes the accepted pilot and UI-01, not a new exchange standard.

## Flow and ownership

P6 XML → strict importer/normalizer → stored schedule snapshot → presentation tree → selected Activity key → Revit ExternalEvent → guarded native reads → pure candidate relationship edit → validated atomic working-file save. Export derives from a saved, validated revision.

`p6.py` owns schedule normalization; `core.py` owns relationships and validation; `storage.py` owns external persistence; `revit_adapter.py` owns native reads; `ui.py` coordinates WPF/ExternalEvent. `activity_tree.py` projects normalized records only. No Revit transactions, parameter changes or geometry writes are introduced.

## Identities and relationships

A working document has its own working ID and logical model key. Native element UniqueId resolves within the bound model; ElementId is diagnostic, not a replacement lookup. Binding compares ProjectInformation identity and requires operator lineage confirmation because copies can preserve identity. Deleted elements remain unresolved and are not matched to replacements by name, geometry or ElementId.

Activity keys from the normalized snapshot are authoritative within that snapshot. Labels, tree positions and WBS codes are never mapping keys. One element may map to multiple activities; many elements may map to one activity. One unique pair per element/activity is permitted. Adding a duplicate pair is a no-op. Reassignment changes only selected relationship endpoints, retains relationship identity/notes, and rejects the entire command on duplicate-pair collision. Removal deletes selected relationships, never model elements. Undo is session-scoped and commits a new revision.

## Persistence and exchange

Formats remain `suzanoo-mapping-work-1` and `suzanoo-mapping-exchange-1-pilot`. UI-01 makes no format/version changes. One schedule snapshot and one local writer per document. Every confirmed edit saves a validated candidate; failed writes must not adopt the candidate. Storage uses locking, replacement and a previous-revision `.bak`. This is not a long-term backup or collaboration service. Use local NTFS, close work before copying backups, and never delete a lock to bypass an active writer.

Unknown/future formats are rejected. Recovery writes a new file. Source XML changes are detected by hash; automatic revision migration is unsupported. Existing work embeds its schedule and does not need the original XML path to reopen.

Exchange is derived data, not an editable working document. It retains model, element, schedule and relationship identity/provenance; missing native elements block export. Missing dates can yield `time_ready=false`; dates are not invented. Offline exchange validation checks the data contract, not current RVT/IFC geometry correspondence. Renderer object IDs, animation rules and geometry crosswalks do not belong to this core format by assumption.

## Tree presentation contract

WBS ObjectId/ParentObjectId define hierarchy; Activity WBSObjectId determines placement. Source order is retained among siblings, with child WBS before activities. No numeric SequenceNumber or alphabetic sort is invented. WBS/group selection clears the target; only a uniquely identified Activity supplies a mapping key. Search retains ancestors and includes descendants of matching WBS headings. Hiding the selected Activity clears its target. Collapse alone leaves its explicit target detail intact. Expansion/selection are transient and do not change the working revision.

Defensive projection retains orphan/missing/ambiguous WBS records and cycles in a visible diagnostic branch. Duplicate/missing activity keys remain visible but cannot be assigned. Input records are never repaired or mutated. The accepted strict importer and working-file validator still reject malformed schedules explicitly; UI-01 does not promise to import every P6 dialect or malformed XML. Thus rejected input is an explicit error, not silently omitted activities.

## Compatibility boundaries

Revit 2026.1 / accepted pyRevit IronPython 2.7 environment; CPython tests are not engine qualification. Native host categories only: Walls, Floors, Structural Columns, Structural Framing. Non-workshared saved/unmodified model guard remains. No linked authoring, MSP, IFC correspondence generation, geometry splitting, renderer or schedule revision migration in this milestone.
