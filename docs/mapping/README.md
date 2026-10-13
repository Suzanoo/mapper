# Mapping Authoring — MS-1 Pilot

Start with [installation and desktop acceptance](INSTALL_AND_DESKTOP_ACCEPTANCE.txt).
Read the [implementation report](REVIT_PYREVIT_MAPPING_MS1_IMPLEMENTATION_REPORT.txt)
for behavior, engineering decisions, limitations and evidence status.

New extension: `MappingAuthoring.extension` at repository root. Existing
`MyTools.extension` is unchanged. The separate MS-0 proof is closed and is not
this author's working-file format.

Authoritative policy: many-to-many relationships; Add never replaces existing
pairs. Reassign/remove operate on selected relationship rows. Host only, P6 only,
external autosave, no renderer and no RVT model writes.

Automated tests (CPython 3.9+, standard library only):

```text
python -m unittest discover -s tests/mapping -v
python tools/validate_mapping_exchange.py PATH_TO_EXCHANGE_JSON
```

Desktop execution/acceptance remains pending. Tests use explicit fakes where
Revit/WPF would be required. Their success is not desktop certification.
