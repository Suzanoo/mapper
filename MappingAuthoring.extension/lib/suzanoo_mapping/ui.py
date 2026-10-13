# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import os
import traceback
from pyrevit import forms
from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent
from System.Windows.Controls import ListBoxItem, TreeViewItem
from . import core, p6, storage, activity_tree, revit_adapter as native
from .p6 import MappingError

_WINDOW = None


class Handler(IExternalEventHandler):
    def __init__(self):
        self.window = None
        self.pending = None

    def GetName(self):
        return 'Suzanoo Mapping Authoring'

    def Execute(self, uiapp):
        request = self.pending
        try:
            if request is not None and self.window is not None:
                self.window.perform(uiapp, request)
        except Exception as ex:
            print(traceback.format_exc())
            self.window.message('ACTION FAILED: %s\nNo success is implied. See pyRevit output for details.' % ex)
            forms.alert(core.as_text(ex), title='Mapping: action not completed', warn_icon=True)
        finally:
            self.pending = None
            if self.window is not None:
                self.window.Workspace.IsEnabled = True
                try:
                    self.window.refresh()
                except Exception as ex:
                    print(traceback.format_exc())
                    self.window.message('Display refresh failed; committed work is retained. Close and reopen the palette. %s' % ex)


class MappingWindow(forms.WPFWindow):
    def __init__(self, handler, event):
        self.ready = False
        self.store = None
        self.bound_doc = None
        self.bound_path = None
        self.captured = []
        self.excluded = []
        self.resolution = {}
        self.target = None
        self._tree_items = {}
        self._tree_expanded = {}
        self._tree_filtered = False
        self.handler, self.external_event = handler, event
        self.actor = os.environ.get('USERNAME') or os.environ.get('USER') or 'local-operator'
        forms.WPFWindow.__init__(self, os.path.join(os.path.dirname(__file__), 'window.xaml'))
        self.Closing += self.closing
        self.Closed += self.closed
        self.ready = True
        self.message('MS-1 Pilot. Host only: Walls, Floors, Structural Columns, Structural Framing.\n'
                     'Use New + Import P6 or Open work. Select elements in Revit while this palette stays open.')

    def message(self, text):
        self.Messages.Text = text

    def ask(self, text):
        return forms.alert(text, title='Mapping confirmation', yes=True, no=True)

    def submit(self, action):
        if self.handler.pending is not None:
            return
        ids = [i.Tag for i in self.Relationships.SelectedItems]
        self.handler.pending = {'action': action, 'target': self.target, 'ids': ids}
        self.Workspace.IsEnabled = False
        try:
            status = self.external_event.Raise()
            if str(status) != 'Accepted':
                raise MappingError('Revit did not accept the request (%s). Finish the active command and retry.' % status)
        except Exception as ex:
            self.handler.pending = None
            self.Workspace.IsEnabled = True
            self.message(core.as_text(ex))

    def on_new(self, sender, args): self.submit('new')
    def on_open(self, sender, args): self.submit('open')
    def on_close_work(self, sender, args): self.submit('close')
    def on_save(self, sender, args): self.submit('save')
    def on_recover(self, sender, args): self.submit('recover')
    def on_check_source(self, sender, args): self.submit('source')
    def on_validate(self, sender, args): self.submit('validate')
    def on_export(self, sender, args): self.submit('export')
    def on_capture(self, sender, args): self.submit('capture')
    def on_assign(self, sender, args): self.submit('assign')
    def on_select(self, sender, args): self.submit('select')
    def on_reassign(self, sender, args): self.submit('reassign')
    def on_note(self, sender, args): self.submit('note')
    def on_remove(self, sender, args): self.submit('remove')
    def on_undo(self, sender, args): self.submit('undo')

    def closing(self, sender, args):
        if self.handler.pending is not None:
            args.Cancel = True
            self.message('Wait for the pending Revit request before closing.')

    def closed(self, sender, args):
        global _WINDOW
        if self.store:
            self.store.close()
        self.handler.window = None
        self.external_event.Dispose()
        _WINDOW = None

    def detach(self):
        if self.store:
            self.store.close()
        self.store = None
        self.bound_doc = None
        self.bound_path = None
        self.captured, self.excluded = [], []
        self.resolution = {}
        self.target = None
        self._tree_items = {}
        self._tree_expanded = {}
        self._tree_filtered = False

    def on_activity_filter(self, sender, args):
        if self.ready:
            self.fill_activities()

    def on_activity_changed(self, sender, args):
        if not self.ready:
            return
        item = self.Activities.SelectedItem
        self.target = activity_tree.selected_key(item.Tag if item else None)
        self.fill_details()
        self.fill_relationships()

    def on_review_filter(self, sender, args):
        if self.ready:
            self.fill_relationships()

    def target_record(self):
        if self.store:
            return next((a for a in self.store.state['schedule']['activities'] if a['key'] == self.target), None)

    def fill_activities(self):
        remembered = self.target
        if not self._tree_filtered:
            for ident, item in self._tree_items.items():
                if item.Tag['kind'] != 'activity':
                    self._tree_expanded[ident] = bool(item.IsExpanded)
        term = self.ActivitySearch.Text.strip()
        self.ready = False
        self.target = None
        try:
            self.Activities.Items.Clear()
            self._tree_items = {}
            if self.store:
                tree = activity_tree.build(self.store.state['schedule'])
                roots = activity_tree.filtered(tree['roots'], term)
                stack = [(n, self.Activities.Items) for n in reversed(roots)]
                visible = 0
                while stack:
                    node, collection = stack.pop()
                    item = TreeViewItem()
                    item.Header, item.Tag = node['label'], node
                    item.ToolTip = node['reason'] or node['label']
                    collection.Add(item)
                    self._tree_items[node['id']] = item
                    item.IsExpanded = bool(term) or self._tree_expanded.get(node['id'], False)
                    activity_key = activity_tree.selected_key(node)
                    if node['kind'] == 'activity':
                        visible += 1
                    if activity_key and activity_key == remembered:
                        # TreeView.SelectedItem is read-only; select its container.
                        item.IsSelected = True
                        self.target = activity_key
                    stack.extend((child, item.Items) for child in reversed(node['children']))
                self.TreeStatus.Text = '%d / %d activities | %d hierarchy warnings' % (visible, tree['activity_count'], len(tree['warnings']))
                self.TreeStatus.ToolTip = '\n'.join(tree['warnings']) or 'WBS headings are navigation only.'
            else:
                self.TreeStatus.Text = 'No schedule loaded.'
                self.TreeStatus.ToolTip = None
        finally:
            self._tree_filtered = bool(term)
            self.ready = True
        self.fill_details()
        self.fill_relationships()

    def on_expand_tree(self, sender, args):
        self.set_tree_expansion(True)

    def on_collapse_tree(self, sender, args):
        self.set_tree_expansion(False)

    def set_tree_expansion(self, expanded):
        for ident, item in self._tree_items.items():
            if item.Tag['kind'] != 'activity':
                item.IsExpanded = expanded
                if not self._tree_filtered:
                    self._tree_expanded[ident] = expanded

    def fill_details(self):
        a = self.target_record()
        if a is None:
            self.ActivityDetails.Text = 'Select a target activity. Adding it never removes other activity relationships.'
            return
        lines = ['TARGET: %s | %s' % (a['Id'], a['Name']),
                 '%s | %s | ObjectId %s' % (a.get('Type'), a.get('Status'), a['ObjectId'])]
        for k in p6.DATE_FIELDS:
            d = a['dates'][k]
            lines.append('%s: %s' % (k, d['value'] or d['state']))
        lines.append('Dates retain source timezone/absence; no baseline or CPM inference.')
        self.ActivityDetails.Text = '\n'.join(lines)

    def fill_relationships(self):
        if not self.ready:
            return
        selected = set(i.Tag for i in self.Relationships.SelectedItems)
        self.Relationships.Items.Clear()
        if not self.store:
            return
        s = self.store.state
        acts = dict((a['key'], a) for a in s['schedule']['activities'])
        captured = set(e['unique_id'] for e in self.captured)
        term = self.ReviewSearch.Text.lower().strip()
        for r in s['relationships']:
            uid = r['element_uid']
            if self.OnlyActivity.IsChecked and r['activity_key'] != self.target:
                continue
            if self.OnlyCaptured.IsChecked and uid not in captured:
                continue
            resolved = self.resolution.get(uid, {})
            e = resolved.get('element', s['elements'][uid])
            a = acts[r['activity_key']]
            label = '%s | %s | %s | %s\n%s | %s\n%s' % (
                e['element_id'], e['category'], e['level'].get('name') or 'Unknown level',
                resolved.get('status', 'unchecked'), a['Id'], a['Name'], r['note'])
            if term and term not in (label + uid).lower():
                continue
            item = ListBoxItem()
            item.Content, item.Tag = label, r['id']
            item.ToolTip = 'UniqueId: %s\nRelationship: %s\n%s' % (uid, r['id'], resolved.get('reason', ''))
            self.Relationships.Items.Add(item)
            if r['id'] in selected:
                item.IsSelected = True

    def refresh(self):
        if not self.ready:
            return
        if self.store:
            s = self.store.state
            project = s['schedule']['project']
            self.Summary.Text = '%s | %s / %s | %d activities | %d relationships | Last committed revision %d\n%s' % (
                s['model']['binding']['title'], project['Id'], project['Name'],
                len(s['schedule']['activities']), len(s['relationships']), s['revision'], self.store.path)
        else:
            self.Summary.Text = 'No working document open. New + Import P6 or Open work.'
        self.CaptureSummary.Text = '%d captured eligible host elements; %d excluded. Buffer is used by Add.' % (len(self.captured), len(self.excluded))
        self.fill_activities()

    def attach(self, store, doc):
        # New/open is staged; prior work stays usable if loading/confirmation fails.
        previous = self.store
        self.store, self.bound_doc, self.bound_path = store, doc, doc.PathName
        self.captured, self.excluded, self.resolution = [], [], {}
        self.target = None
        self._tree_items = {}
        self._tree_expanded = {}
        self._tree_filtered = False
        if previous:
            previous.close()

    def confirm_binding(self, state, document):
        core.check_binding(state, document)
        return self.ask('Confirm SAME logical model lineage. Copies can share native IDs.\n\n'
                        'Working model: %s\nOriginally: %s\nCurrent RVT: %s\n\n'
                        'Choose No for a different project/fork; create new work instead.' % (
                            state['model']['binding']['title'], state['model']['binding']['path'], document['path']))

    def reconcile(self, doc):
        uids = set(r['element_uid'] for r in self.store.state['relationships'])
        self.resolution = native.resolve(doc, uids)
        return core.validation_report(self.store.state, native.evidence(doc), self.resolution)

    def perform(self, uiapp, request):
        action = request['action']
        if action == 'close':
            self.detach()
            self.message('Working document closed. Every previously confirmed edit was already saved.')
            return
        if action in ('new', 'open', 'recover'):
            uidoc, doc = native.current(uiapp)
            document = native.evidence(doc)
            if action == 'new':
                xml = forms.pick_file(file_ext='xml', title='Import P6 Professional V24.12 XML')
                if not xml: return
                inspected = p6.inspect(xml)
                choices = dict(('%s | %s [%s]' % (p['Id'], p['Name'], p['ObjectId']), p['ObjectId']) for p in inspected['projects'])
                choice = forms.SelectFromList.show(sorted(choices), title='Choose P6 project', multiselect=False)
                if not choice: return
                schedule = p6.normalize(inspected, choices[choice])
                if not self.ask('Create work for %s?\n%s\n%d activities / %d WBS / %d warnings\n'
                                'P6 source SHA-256: %s\n\nWhole-element many-to-many associations.\n%s' % (
                                    document['title'], choice, len(schedule['activities']), len(schedule['wbs']),
                                    len(schedule['warnings']), schedule['source']['sha256'], '\n'.join(schedule['warnings'][:12]))):
                    return
                path = forms.save_file(file_ext='mapping.json', default_name='Project.mapping.json', title='Create NEW working file in a local folder')
                if not path: return
                loaded = storage.WorkingStore.create(path, core.new_work(document, schedule, self.actor))
            elif action == 'open':
                path = forms.pick_file(files_filter='Mapping work (*.mapping.json)|*.mapping.json|JSON (*.json)|*.json', title='Open working document (not an exchange)')
                if not path: return
                if self.store and os.path.normcase(os.path.abspath(path)) == os.path.normcase(self.store.path):
                    self.message('This working document is already open.'); return
                loaded = storage.WorkingStore.open(path)
                try:
                    if not self.confirm_binding(loaded.state, document):
                        loaded.close(); return
                except Exception:
                    loaded.close(); raise
            else:
                backup = forms.pick_file(files_filter='Backup (*.bak)|*.bak', title='Choose previous committed .mapping.json.bak')
                if not backup: return
                state, unused = storage.read(backup)
                core.validate(state)
                if not self.confirm_binding(state, document): return
                path = forms.save_file(file_ext='mapping.json', default_name='Recovered.mapping.json', title='Recover to a NEW working file')
                if not path: return
                loaded = storage.recover_to_new(backup, path, self.actor)
            self.attach(loaded, doc)
            report = self.reconcile(doc)
            self.message('Opened %s\n%d relationships, %d unresolved elements. Snapshot is stored inside the working file.\n'
                         'Native IDs are exact; no replacement search is performed.' % (self.store.path, report['relationship_count'], len(report['issues'])))
            return
        if not self.store:
            raise MappingError('Create or open a working document first.')
        uidoc, doc = native.current(uiapp, self.bound_doc, self.bound_path)
        core.check_binding(self.store.state, native.evidence(doc))
        self.store.check_current()
        s = self.store.state
        if action == 'capture':
            self.captured, self.excluded = native.capture(uidoc)
            lines = ['Captured %d eligible / excluded %d.' % (len(self.captured), len(self.excluded))]
            lines += ['%s | %s | %s' % (e['element_id'], e['category'], e['level']['name'] or 'Unknown level') for e in self.captured]
            lines += ['EXCLUDED %s: %s' % (e['element_id'], e['reason']) for e in self.excluded]
            self.message('\n'.join(lines)); return
        if action in ('save', 'validate'):
            report = self.reconcile(doc)
            self.message('Saved revision %d verified on disk. %d relationships / %d elements / %d unresolved.\n'
                         'Relationship-valid: %s | Time-ready: %s\n%s' % (
                             s['revision'], report['relationship_count'], report['element_count'], len(report['issues']),
                             report['relationship_valid'], report['time_ready'],
                             '\n'.join('%s: %s' % (r['element_uid'], r['status']) for r in report['issues'])))
            return
        if action == 'source':
            path = forms.pick_file(file_ext='xml', title='Compare P6 source checksum (no migration)')
            if not path: return
            inspected = p6.inspect(path)
            if inspected['source']['sha256'] != s['schedule']['source']['sha256']:
                raise MappingError('P6 source changed. Stored snapshot and mappings remain unchanged. Schedule migration is deferred.')
            self.message('P6 checksum matches the stored snapshot. No import or mapping changes.'); return
        if action == 'export':
            report = self.reconcile(doc)
            if report['issues']:
                self.message('EXPORT BLOCKED. Review missing/ineligible rows. Existing work is retained.\n' +
                             '\n'.join('%s: %s' % (r['element_uid'], r['status']) for r in report['issues']))
                return
            if not s['relationships']:
                raise MappingError('No relationships to export. Assign a batch first.')
            data = core.exchange(s, native.evidence(doc), self.resolution)
            if not self.ask('Export saved revision %d?\n%d relationships / %d elements\n'
                            'Time-ready: %s\nGeometry correspondence is not evaluated.\n%s' % (
                                s['revision'], report['relationship_count'], report['element_count'], report['time_ready'],
                                '\n'.join(str(x) for x in report['date_issues']))): return
            path = forms.save_file(file_ext='json', default_name='Mapping-r%d.exchange.json' % s['revision'], title='Export to a NEW filename')
            if not path: return
            self.store.check_current()
            storage.write_new(path, data)
            self.message('Validated exchange saved: %s\nOrigin working revision %d. Working state unchanged.' % (path, s['revision'])); return
        if action == 'select':
            rows = core._selected(s, request['ids'])
            resolved = native.select(uidoc, [r['element_uid'] for r in rows])
            self.resolution.update(resolved)
            self.message('Selected %d distinct resolved elements. Missing/ineligible: %d. No model modifications.' % (
                sum(1 for r in resolved.values() if r['status'] == 'resolved'), sum(1 for r in resolved.values() if r['status'] != 'resolved'))); return
        if action == 'undo':
            if self.store.undo_state is None:
                raise MappingError('No committed edit to undo in this session.')
            if not self.ask('Undo the last committed Mapping edit? This creates a new saved revision; it does not undo Revit geometry.'): return
            self.store.undo(self.actor)
        else:
            if action == 'assign':
                fresh = native.resolve(doc, [e['unique_id'] for e in self.captured])
                if any(r['status'] != 'resolved' for r in fresh.values()):
                    raise MappingError('Captured elements changed or are missing. Use current selection again.')
                candidate, changed = core.assign(s, [r['element'] for r in fresh.values()], request['target'])
                prompt = 'Add %d NEW relationships to target activity?\n%d captured elements; %d excluded.\nExisting activity relationships remain.' % (
                    len(changed), len(self.captured), len(self.excluded))
            elif action == 'remove':
                candidate, changed = core.remove(s, request['ids'])
                prompt = 'Remove exactly %d selected relationships? Other activity relationships remain; Revit elements are untouched.' % len(changed)
            elif action == 'reassign':
                candidate, changed = core.reassign(s, request['ids'], request['target'])
                prompt = 'Reassign %d selected relationships to the target activity? Unselected relationships remain.' % len(changed)
            elif action == 'note':
                rows = core._selected(s, request['ids'])
                note = forms.ask_for_string(default=rows[0]['note'] if len(rows) == 1 else '', prompt='Note for selected relationship(s), maximum 2000 characters. Empty clears the note.', title='Edit relationship note')
                if note is None: return
                candidate, changed = core.edit_note(s, request['ids'], note)
                prompt = 'Save the note on %d selected relationships?' % len(changed)
            else:
                raise MappingError('Unknown action.')
            if not changed:
                self.message('No changes. Requested relationships/values already exist. Saved revision unchanged.'); return
            if request['target']:
                target = next((a for a in s['schedule']['activities'] if a['key'] == request['target']), None)
                if target:
                    prompt += '\nTarget: %s | %s' % (target['Id'], target['Name'])
            # The explicit row list makes remove/reassign scope reviewable.
            selected_rows = [r for r in s['relationships'] if r['id'] in set(request['ids'])]
            acts = dict((a['key'], a['Id']) for a in s['schedule']['activities'])
            if selected_rows:
                prompt += '\nSelected pairs:\n' + '\n'.join('%s -> %s' % (s['elements'][r['element_uid']]['element_id'], acts[r['activity_key']]) for r in selected_rows[:20])
                if len(selected_rows) > 20: prompt += '\n... %d more selected rows' % (len(selected_rows) - 20)
            if not self.ask(prompt): return
            self.store.commit(candidate, action, changed, self.actor)
        self.reconcile(doc)
        self.message('Saved revision %d. %d relationships. Previous committed file: %s.bak' % (
            self.store.state['revision'], len(self.store.state['relationships']), self.store.path))


def launch():
    global _WINDOW
    if _WINDOW is not None and _WINDOW.IsLoaded:
        _WINDOW.Activate()
        return
    handler = Handler()
    event = ExternalEvent.Create(handler)  # command context, never WPF callback
    try:
        window = MappingWindow(handler, event)
        handler.window = window
        _WINDOW = window
        window.Show()
    except Exception:
        event.Dispose()
        raise
