# -*- coding: utf-8 -*-
"""Headless API/UI contract tests with explicit fakes, NOT Revit/WPF execution."""
import copy
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch
from test_mapping import LIB, document, schedule, element
from suzanoo_mapping import core, storage
from suzanoo_mapping.p6 import MappingError


class EventHook:
    def __iadd__(self, callback): return self


class Items(list):
    def Clear(self): self.clear()
    def Add(self, item): self.append(item)


class Control:
    def __init__(self):
        self.Text = ''; self.IsEnabled = True; self.IsChecked = False
        self.Items = Items(); self.SelectedItem = None; self.selected = []
    @property
    def SelectedItems(self): return self.selected or [i for i in self.Items if getattr(i, 'IsSelected', False)]


class WPF:
    def __init__(self, path):
        self.Closing, self.Closed = EventHook(), EventHook()
        for name in ('Workspace', 'Summary', 'Activities', 'ActivitySearch', 'ActivityDetails',
                     'Relationships', 'ReviewSearch', 'OnlyActivity', 'OnlyCaptured',
                     'Messages', 'CaptureSummary', 'TreeStatus'):
            setattr(self, name, Control())
        self.Activities = TreeControl()


class Item:
    def __init__(self): self.IsSelected = False


class TreeItem(Item):
    def __init__(self):
        super().__init__()
        self.Items = Items()
        self.IsExpanded = False


class TreeControl:
    def __init__(self):
        self.Items = Items()
    @property
    def SelectedItem(self):
        stack = list(self.Items)
        while stack:
            item = stack.pop()
            if item.IsSelected:
                return item
            stack.extend(item.Items)
        return None


class Id:
    def __init__(self, value): self.Value = value


class GenericList(list):
    @classmethod
    def __class_getitem__(cls, item): return cls
    def Add(self, value): self.append(value)


class Element:
    def __init__(self, doc, uid, eid, category=-1):
        self.Document, self.UniqueId, self.Id = doc, uid, Id(eid)
        self.Name = 'instance'; self.ViewSpecific = False
        self.Category = types.SimpleNamespace(Id=Id(category), Name='Category')
        self.LevelId = Id(-100); self.params = {}
    def GetTypeId(self): return Id(-200)
    def get_Parameter(self, bip): return self.params.get(bip)


class FamilyInstance(Element):
    SuperComponent = None


class Level(Element): pass
class ElementType(Element): pass
class Link(Element): pass
class Import(Element): pass
class Group(Element): pass
class Assembly(Element): pass
class Part(Element): pass


class Doc:
    def __init__(self):
        self.PathName = document()['path']; self.Title = 'HOST'
        self.IsValidObject = True; self.IsFamilyDocument = False; self.IsLinked = False
        self.IsWorkshared = False; self.IsModified = False
        self.ProjectInformation = types.SimpleNamespace(UniqueId='project-native-id')
        self.rows = {}; self.level = Level(self, 'L1', -100)
        self.level.Name = 'ชั้น 1'; self.add(self.level)
    def Equals(self, other): return self is other
    def GetElement(self, key): return self.rows.get(key.Value if isinstance(key, Id) else key)
    def add(self, e): self.rows[e.UniqueId] = e; self.rows[e.Id.Value] = e; return e


class Selection:
    def __init__(self): self.ids = []
    def GetElementIds(self): return self.ids
    def SetElementIds(self, ids): self.ids = list(ids)


DB = types.SimpleNamespace(ElementId=Id, Element=Element, ElementType=ElementType,
    RevitLinkInstance=Link, ImportInstance=Import, Group=Group, AssemblyInstance=Assembly,
    Part=Part, FamilyInstance=FamilyInstance, Level=Level,
    StorageType=types.SimpleNamespace(ElementId='ElementId'),
    BuiltInCategory=types.SimpleNamespace(OST_Walls=-1, OST_Floors=-2, OST_StructuralColumns=-3, OST_StructuralFraming=-4),
    BuiltInParameter=types.SimpleNamespace(WALL_BASE_CONSTRAINT='wall', LEVEL_PARAM='floor', FAMILY_BASE_LEVEL_PARAM='column', INSTANCE_REFERENCE_LEVEL_PARAM='frame'),
    Document=types.SimpleNamespace(GetDocumentVersion=lambda d: types.SimpleNamespace(VersionGUID='r1', NumberOfSaves=10)))
forms = types.SimpleNamespace(WPFWindow=WPF, alert=Mock(return_value=True), pick_file=Mock(return_value=None),
    save_file=Mock(return_value=None), ask_for_string=Mock(return_value=None),
    SelectFromList=types.SimpleNamespace(show=Mock(return_value=None)))
module_defs = {'pyrevit': {'DB': DB, 'forms': forms}, 'Autodesk': {}, 'Autodesk.Revit': {},
    'Autodesk.Revit.UI': {'IExternalEventHandler': object, 'ExternalEvent': types.SimpleNamespace(Create=Mock())},
    'System': {}, 'System.Windows': {}, 'System.Windows.Controls': {'ListBoxItem': Item, 'TreeViewItem': TreeItem},
    'System.Collections': {}, 'System.Collections.Generic': {'List': GenericList}}
for name, attrs in module_defs.items():
    mod = types.ModuleType(name); mod.__dict__.update(attrs); sys.modules[name] = mod
from suzanoo_mapping import revit_adapter as native, ui


class NativeBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.doc = Doc(); self.selection = Selection()
        self.uidoc = types.SimpleNamespace(Document=self.doc, Selection=self.selection)
        self.app = types.SimpleNamespace(ActiveUIDocument=self.uidoc)

    def test_native_identity_and_all_initial_categories(self):
        for i, cat in enumerate(core.CATEGORIES, 1):
            e = self.doc.add(Element(self.doc, 'uid%d' % i, i, -i))
            row = native.extract(self.doc, e)
            self.assertEqual(cat, row['category_builtin']); self.assertEqual(e.UniqueId, row['unique_id'])
            self.assertEqual('ชั้น 1', row['level']['name'])
        self.assertFalse(self.doc.IsModified)

    def test_category_level_parameter_precedes_fallback(self):
        e = self.doc.add(Element(self.doc, 'e1', 1)); other = self.doc.add(Level(self.doc, 'L2', -101))
        other.Name = 'LEVEL2'; e.params['wall'] = types.SimpleNamespace(StorageType='ElementId', AsElementId=lambda: other.Id)
        row = native.extract(self.doc, e)
        self.assertEqual('L2', row['level']['unique_id']); self.assertEqual('WALL_BASE_CONSTRAINT', row['level']['basis'])

    def test_unknown_level_preserved(self):
        e = self.doc.add(Element(self.doc, 'e1', 1)); e.LevelId = Id(999)
        row = native.extract(self.doc, e)
        self.assertIsNone(row['level']['unique_id']); self.assertIn('unknown', row['level']['basis'])

    def test_containers_link_types_unsupported_and_nested_are_excluded(self):
        for cls in (Link, Import, Group, Assembly, Part, ElementType):
            with self.assertRaises(MappingError): native.extract(self.doc, cls(self.doc, 'bad', 1))
        nested = FamilyInstance(self.doc, 'nested', 2); nested.SuperComponent = object()
        with self.assertRaises(MappingError): native.extract(self.doc, nested)
        with self.assertRaises(MappingError): native.extract(self.doc, Element(self.doc, 'bad', 3, -999))
        with self.assertRaises(MappingError): native.extract(self.doc, Element(Doc(), 'foreign', 4))

    def test_mixed_capture_reports_every_exclusion(self):
        self.doc.add(Element(self.doc, 'good', 1)); self.doc.add(Link(self.doc, 'bad', 2))
        self.selection.ids = [Id(1), Id(2), Id(404)]
        good, excluded = native.capture(self.uidoc)
        self.assertEqual(1, len(good)); self.assertEqual(2, len(excluded))

    def test_selection_resolves_unique_id_not_reused_element_id(self):
        replacement = self.doc.add(Element(self.doc, 'replacement', 900))
        result = native.select(self.uidoc, ['old', 'replacement', 'replacement'])
        self.assertEqual('missing', result['old']['status'])
        self.assertEqual([replacement.Id], self.selection.ids)

    def test_document_switch_close_saveas_and_modified_are_guarded(self):
        native.current(self.app, self.doc, self.doc.PathName)
        with self.assertRaises(MappingError): native.current(self.app, Doc(), self.doc.PathName)
        with self.assertRaises(MappingError): native.current(self.app, self.doc, 'different.rvt')
        self.doc.IsValidObject = False
        with self.assertRaises(MappingError): native.current(self.app, self.doc)
        self.doc.IsValidObject = True; self.doc.IsModified = True
        with self.assertRaises(MappingError): native.current(self.app)


class UIFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.sched = schedule()
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / 'work.mapping.json')
        self.doc = Doc(); self.sel = Selection()
        self.doc.add(Element(self.doc, 'e1', 1)); self.doc.add(Element(self.doc, 'e2', 2))
        self.app = types.SimpleNamespace(ActiveUIDocument=types.SimpleNamespace(Document=self.doc, Selection=self.sel))
        self.handler = ui.Handler(); self.event = types.SimpleNamespace(Raise=Mock(return_value='Accepted'), Dispose=Mock())
        self.window = ui.MappingWindow(self.handler, self.event); self.handler.window = self.window
        self.window.attach(storage.WorkingStore.create(self.path, core.new_work(document(), self.sched, 'tester')), self.doc)
        self.a, self.b, self.c = [a['key'] for a in self.sched['activities'][:3]]
        for f in (forms.alert, forms.pick_file, forms.save_file, forms.ask_for_string, forms.SelectFromList.show):
            f.reset_mock(); f.side_effect = None
        forms.alert.return_value = True; forms.pick_file.return_value = None
        forms.save_file.return_value = None; forms.ask_for_string.return_value = None
        forms.SelectFromList.show.return_value = None
    def tearDown(self):
        if self.window.store: self.window.store.close()
        self.tmp.cleanup()
    def perform(self, action, ids=None, target=None):
        self.window.perform(self.app, {'action': action, 'ids': ids or [], 'target': target})
    def capture_add(self, target):
        self.sel.ids = [Id(1), Id(2)]; self.perform('capture'); self.perform('assign', target=target)
    def bytes(self): return Path(self.path).read_bytes()

    def test_full_ui_action_loop_many_to_many_resume_export(self):
        self.capture_add(self.a); self.capture_add(self.b)
        self.assertEqual(4, len(self.window.store.state['relationships']))
        rid = self.window.store.state['relationships'][0]['id']
        self.perform('reassign', [rid], self.c)
        self.perform('select', [rid]); self.assertEqual(1, self.sel.ids[0].Value)
        forms.ask_for_string.return_value = 'ตรวจแล้ว'; self.perform('note', [rid])
        self.perform('remove', [rid]); self.perform('undo')
        expected = copy.deepcopy(self.window.store.state)
        self.perform('close'); forms.pick_file.return_value = self.path; self.perform('open')
        self.assertEqual(expected, self.window.store.state)
        out = str(Path(self.tmp.name) / 'out.exchange.json'); forms.save_file.return_value = out
        self.perform('export'); exported, unused = storage.read(out)
        core.validate_exchange(exported); self.assertEqual(4, len(exported['relationships']))
        self.assertFalse(self.doc.IsModified)

    def test_confirmation_cancel_never_commits(self):
        self.capture_add(self.a); before = self.bytes()
        rid = self.window.store.state['relationships'][0]['id']
        forms.alert.return_value = False
        self.perform('assign', target=self.b); self.perform('remove', [rid]); self.perform('reassign', [rid], self.b)
        self.perform('undo')
        self.assertEqual(before, self.bytes())

    def test_new_open_recover_source_export_picker_cancel_keeps_current_work(self):
        self.capture_add(self.a); before = self.bytes(); working = self.window.store
        for action in ('new', 'open', 'recover', 'source', 'export'):
            self.perform(action)
            self.assertIs(working, self.window.store); self.assertEqual(before, self.bytes())

    def test_empty_capture_and_missing_buffer_no_assignment(self):
        self.perform('capture'); before = self.bytes()
        with self.assertRaises(MappingError): self.perform('assign', target=self.a)
        self.sel.ids = [Id(1)]; self.perform('capture'); del self.doc.rows['e1']
        with self.assertRaises(MappingError): self.perform('assign', target=self.a)
        self.assertEqual(before, self.bytes())

    def test_missing_is_visible_blocks_export_and_can_remove_only_that_pair(self):
        self.capture_add(self.a); self.capture_add(self.b)
        del self.doc.rows['e1']; self.perform('validate')
        self.assertEqual('missing', self.window.resolution['e1']['status'])
        out = str(Path(self.tmp.name) / 'out.json'); forms.save_file.return_value = out
        self.perform('export'); self.assertFalse(Path(out).exists())
        r = next(r for r in self.window.store.state['relationships'] if r['element_uid'] == 'e1')
        self.perform('remove', [r['id']])
        self.assertEqual(3, len(self.window.store.state['relationships']))
        self.assertEqual(1, sum(r['element_uid'] == 'e1' for r in self.window.store.state['relationships']))

    def test_changed_source_detected_without_reimport(self):
        from test_mapping import SOURCE
        altered = Path(self.tmp.name) / 'changed.xml'; altered.write_bytes(SOURCE.read_bytes() + b'\n')
        forms.pick_file.return_value = str(altered); before = self.bytes()
        with self.assertRaisesRegex(MappingError, 'source changed'): self.perform('source')
        self.assertEqual(before, self.bytes())

    def test_wrong_or_declined_binding_preserves_open_work(self):
        self.capture_add(self.a); before = self.bytes(); current = self.window.store
        path = str(Path(self.tmp.name) / 'other.mapping.json')
        other = core.new_work(document(), self.sched, 'tester')
        other['model']['binding']['project_information_unique_id'] = 'other'
        store = storage.WorkingStore.create(path, other); store.close()
        forms.pick_file.return_value = path
        with self.assertRaises(MappingError): self.perform('open')
        self.assertIs(current, self.window.store); self.assertEqual(before, self.bytes())
        other['model']['binding']['project_information_unique_id'] = 'project-native-id'
        Path(path).unlink(); store = storage.WorkingStore.create(path, other); store.close()
        forms.alert.return_value = False; self.perform('open')
        self.assertIs(current, self.window.store)

    def test_pending_request_disabled_and_document_switch_is_rejected(self):
        self.capture_add(self.a); before = self.bytes()
        self.window.target = self.b
        self.window.submit('assign')
        self.assertFalse(self.window.Workspace.IsEnabled)
        request = self.handler.pending
        self.window.submit('remove'); self.assertIs(request, self.handler.pending)
        self.app.ActiveUIDocument.Document = Doc()
        with patch('builtins.print'):
            self.handler.Execute(self.app)
        self.assertIsNone(self.handler.pending); self.assertTrue(self.window.Workspace.IsEnabled)
        self.assertEqual(before, self.bytes())

    def test_external_event_denied_does_not_leave_busy_state(self):
        self.event.Raise.return_value = 'Denied'; self.window.submit('capture')
        self.assertIsNone(self.handler.pending); self.assertTrue(self.window.Workspace.IsEnabled)

    def test_close_while_pending_prevented(self):
        self.window.submit('capture'); args = types.SimpleNamespace(Cancel=False)
        self.window.closing(None, args); self.assertTrue(args.Cancel)

    def test_review_filters_both_directions_and_note_search(self):
        self.capture_add(self.a); self.capture_add(self.b)
        self.window.refresh(); self.assertEqual(4, len(self.window.Relationships.Items))
        self.window.target = self.a; self.window.OnlyActivity.IsChecked = True
        self.window.fill_relationships(); self.assertEqual(2, len(self.window.Relationships.Items))
        self.window.OnlyActivity.IsChecked = False; self.sel.ids = [Id(1)]
        self.perform('capture'); self.window.OnlyCaptured.IsChecked = True
        self.window.fill_relationships(); self.assertEqual(2, len(self.window.Relationships.Items))

    def test_invalid_open_and_failed_commit_preserve_previous_work(self):
        self.capture_add(self.a); before = self.bytes()
        with patch.object(storage, '_replace', side_effect=IOError('failure')):
            with self.assertRaises(IOError): self.perform('assign', target=self.b)
        self.assertEqual(before, self.bytes())
        bad = Path(self.tmp.name) / 'bad.json'; bad.write_text('{}', encoding='utf-8')
        forms.pick_file.return_value = str(bad)
        with self.assertRaises(MappingError): self.perform('open')
        self.assertEqual(before, self.bytes())


if __name__ == '__main__': unittest.main()
