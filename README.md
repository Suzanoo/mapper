# Mapper

**BIM–Schedule Mapping & Exchange**

Mapper is a project for authoring, reviewing, persisting, validating, and exporting relationships between BIM model elements and construction schedule activities.

## Current status

**Repository bootstrap / migration pending.** The accepted MS-0 technical proof and MS-1 host-model mapping authoring pilot were developed in `Suzanoo/revit-toolkit`. Their source files and documentation have **not** been declared migrated or integrated into this repository.

## Accepted capabilities to preserve during migration

- Revit + pyRevit host-model mapping authoring pilot.
- P6 XML activity import and stored schedule snapshot.
- Many-to-many mapping between Revit elements and activities.
- Review, reassign, remove, undo, and durable external working data.
- Validation and renderer-independent mapping exchange.

The accepted MS-1 pilot does not establish linked-model authoring, automatic schedule revision migration, or 4D viewer integration.

## Architecture direction

Keep mapping identity and relationships independent from any particular renderer. Revit/pyRevit is the initial authoring environment; IFC and viewer integration are separate future concerns subject to investigation and Product Owner approval.

## Repository migration

Migration from `Suzanoo/revit-toolkit` requires a controlled engineering handoff, including accepted source files, tests, documentation, compatibility checks, and a changed-file manifest. Do not assume the contents of `revit-toolkit` should be copied wholesale.

## Collaboration

- **Product Owner:** approves scope, milestones, and acceptance.
- **Coordinator / Git Operator:** reviews deliveries, manages integration and Git operations under the agreed authority.
- **Work (Engineer):** investigates, implements, tests, and delivers complete changed files without performing Git operations.

## License

No license has been selected yet. All rights reserved unless a license is explicitly added.
