# -*- coding: utf-8 -*-
"""Called only inside a supported Revit API context. Never creates transactions."""
from __future__ import unicode_literals
from pyrevit import DB
from System.Collections.Generic import List
from . import core
from .p6 import MappingError


def id_text(eid):
    return str(eid.Value if hasattr(eid, 'Value') else eid.IntegerValue)


def safe_name(e):
    if e is None:
        return None
    try:
        return e.Name
    except Exception:
        return DB.Element.Name.GetValue(e)


def current(uiapp, bound=None, bound_path=None):
    uidoc = uiapp.ActiveUIDocument
    if uidoc is None:
        raise MappingError('Open the saved native host RVT first.')
    doc = uidoc.Document
    if bound is not None and (not bound.IsValidObject or not doc.Equals(bound)):
        raise MappingError('Active RVT changed or the bound RVT closed. Return to it, or Close work and Open again.')
    if bound_path is not None and doc.PathName != bound_path:
        raise MappingError('RVT path changed (Save As). Close work and reopen to confirm model lineage.')
    if doc.IsFamilyDocument or doc.IsLinked or doc.IsWorkshared or not doc.PathName:
        raise MappingError('Pilot requires a saved local, non-workshared native host RVT.')
    if doc.IsModified:
        raise MappingError('Save the RVT first, then retry. Mapping never saves or changes the RVT for you.')
    return uidoc, doc


def evidence(doc):
    ver = DB.Document.GetDocumentVersion(doc)
    return {'title': doc.Title, 'path': doc.PathName,
            'project_information_unique_id': doc.ProjectInformation.UniqueId,
            'is_modified': bool(doc.IsModified), 'is_workshared': bool(doc.IsWorkshared),
            'document_version': {'guid': str(ver.VersionGUID), 'number_of_saves': int(ver.NumberOfSaves)}}


def extract(doc, e):
    if e is None:
        raise MappingError('Element is missing.')
    if not e.Document.Equals(doc):
        raise MappingError('Element is not owned by the bound host.')
    if isinstance(e, (DB.ElementType, DB.RevitLinkInstance, DB.ImportInstance, DB.Group, DB.AssemblyInstance, DB.Part)):
        raise MappingError('Types, links, CAD, containers and Parts are excluded.')
    if e.ViewSpecific or e.Category is None:
        raise MappingError('View-specific or uncategorized element excluded.')
    categories = dict((str(int(getattr(DB.BuiltInCategory, k))), k) for k in core.CATEGORIES)
    category = categories.get(id_text(e.Category.Id))
    if category is None:
        raise MappingError('Supported: Walls, Floors, Structural Columns and Structural Framing.')
    if isinstance(e, DB.FamilyInstance) and e.SuperComponent is not None:
        raise MappingError('Nested family instances are not qualified in this pilot.')
    level_params = {
        'OST_Walls': ('WALL_BASE_CONSTRAINT',),
        'OST_Floors': ('LEVEL_PARAM',),
        'OST_StructuralColumns': ('FAMILY_BASE_LEVEL_PARAM',),
        'OST_StructuralFraming': ('INSTANCE_REFERENCE_LEVEL_PARAM',)}
    level, basis = None, 'unknown: no associated level; not a geometric zone'
    for param_name in level_params[category]:
        bip = getattr(DB.BuiltInParameter, param_name, None)
        p = e.get_Parameter(bip) if bip is not None else None
        if p is not None and p.StorageType == DB.StorageType.ElementId:
            candidate = doc.GetElement(p.AsElementId())
            if isinstance(candidate, DB.Level):
                level, basis = candidate, param_name
                break
    if level is None:
        candidate = doc.GetElement(e.LevelId)
        if isinstance(candidate, DB.Level):
            level, basis = candidate, 'Element.LevelId fallback'
    typ = doc.GetElement(e.GetTypeId())
    row = {'scope': 'native-host', 'unique_id': e.UniqueId, 'element_id': id_text(e.Id),
           'category_builtin': category, 'category': e.Category.Name,
           'name': safe_name(e), 'type_name': safe_name(typ),
           'level': {'name': safe_name(level), 'unique_id': level.UniqueId if level else None, 'basis': basis}}
    core.validate_element(row)
    return row


def capture(uidoc):
    doc = uidoc.Document
    elements, excluded = [], []
    for eid in uidoc.Selection.GetElementIds():
        try:
            elements.append(extract(doc, doc.GetElement(eid)))
        except Exception as ex:
            excluded.append({'element_id': id_text(eid), 'reason': core.as_text(ex)})
    return elements, excluded


def resolve(doc, uids):
    result = {}
    for uid in sorted(set(uids)):
        e = doc.GetElement(uid)
        if e is None:
            result[uid] = {'status': 'missing', 'reason': 'Original UniqueId no longer resolves; no replacement search.'}
            continue
        try:
            result[uid] = {'status': 'resolved', 'element': extract(doc, e)}
        except Exception as ex:
            result[uid] = {'status': 'ineligible', 'reason': core.as_text(ex)}
    return result


def select(uidoc, uids):
    resolved = resolve(uidoc.Document, uids)
    ids = List[DB.ElementId]()
    for uid, row in resolved.items():
        if row['status'] == 'resolved':
            ids.Add(uidoc.Document.GetElement(uid).Id)
    # Selection only; do not hide/isolate/color or modify the document.
    uidoc.Selection.SetElementIds(ids)
    return resolved
