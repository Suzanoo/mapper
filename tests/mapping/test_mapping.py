# -*- coding: utf-8 -*-
"""Core/IO regressions; executed under CPython, no desktop acceptance implied."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / 'MappingAuthoring.extension' / 'lib'
sys.path.insert(0, str(LIB))
from suzanoo_mapping import core, p6, storage
from suzanoo_mapping.p6 import MappingError
SOURCE = Path(__file__).parent / 'fixtures' / 'sample_p6.xml'
REAL_SOURCE = Path(os.environ['MAPPER_REAL_P6']) if os.environ.get('MAPPER_REAL_P6') else None


def document():
    return {'title': 'HOST', 'path': 'C:/Models/HOST.rvt', 'project_information_unique_id': 'project-native-id',
            'is_modified': False, 'is_workshared': False, 'document_version': {'guid': 'r1', 'number_of_saves': 10}}


def element(uid='native-001', category='OST_Walls'):
    return {'unique_id': uid, 'element_id': '900', 'scope': 'native-host',
            'category': category, 'category_builtin': category, 'name': 'Wall', 'type_name': 'W1',
            'level': {'name': 'ชั้น 1', 'unique_id': 'level-1', 'basis': 'WALL_BASE_CONSTRAINT'}}


def schedule():
    return p6.normalize(p6.inspect(str(SOURCE)), '5380')


class CoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schedule = schedule()

    def setUp(self):
        self.state = core.new_work(document(), self.schedule, 'tester')
        self.a, self.b, self.c = [a['key'] for a in self.schedule['activities'][:3]]

    def batch(self):
        state, ids = core.assign(self.state, [element('e1'), element('e2'), element('e1')], self.a)
        return core.assign(state, [element('e1')], self.b)[0]

    def test_many_to_many_preserves_all_existing_pairs(self):
        original = copy.deepcopy(self.state)
        s = self.batch()
        self.assertEqual(3, len(s['relationships']))
        self.assertEqual({('e1', self.a), ('e2', self.a), ('e1', self.b)}, {(r['element_uid'], r['activity_key']) for r in s['relationships']})
        self.assertEqual(original, self.state)
        core.validate(s)

    def test_duplicate_assign_is_idempotent(self):
        s = self.batch()
        result, changed = core.assign(s, [element('e1')], self.a)
        self.assertEqual([], changed)
        self.assertEqual(s, result)

    def test_remove_only_one_pair(self):
        s = self.batch()
        target = next(r for r in s['relationships'] if r['activity_key'] == self.b)
        result, ids = core.remove(s, [target['id']])
        self.assertEqual(2, len(result['relationships']))
        self.assertTrue(all(r['activity_key'] == self.a for r in result['relationships']))
        self.assertIn('e1', result['elements'])
        self.assertEqual(3, len(s['relationships']))

    def test_reassign_retains_id_note_and_unselected_pairs(self):
        s = self.batch()
        target = s['relationships'][0]
        annotated, unused = core.edit_note(s, [target['id']], 'งานแบบหล่อ')
        result, ids = core.reassign(annotated, [target['id']], self.c)
        row = next(r for r in result['relationships'] if r['id'] == target['id'])
        self.assertEqual('งานแบบหล่อ', row['note'])
        self.assertEqual(self.c, row['activity_key'])
        self.assertEqual(annotated['relationships'][1:], result['relationships'][1:])

    def test_reassign_collision_is_atomic(self):
        s = self.batch(); before = copy.deepcopy(s)
        with self.assertRaisesRegex(MappingError, 'duplicate'):
            core.reassign(s, [s['relationships'][0]['id']], self.b)
        self.assertEqual(before, s)

    def test_reassign_two_rows_of_same_element_to_one_target_refuses(self):
        s = self.batch()
        with self.assertRaises(MappingError):
            core.reassign(s, [r['id'] for r in s['relationships'] if r['element_uid'] == 'e1'], self.c)

    def test_reassign_same_target_is_noop(self):
        s = self.batch()
        result, ids = core.reassign(s, [s['relationships'][0]['id']], self.a)
        self.assertEqual([], ids); self.assertEqual(s, result)

    def test_note_clear_and_selected_only(self):
        s = self.batch(); rid = s['relationships'][0]['id']
        changed, ids = core.edit_note(s, [rid], 'ทดสอบ')
        self.assertEqual('', changed['relationships'][1]['note'])
        cleared, ids = core.edit_note(changed, [rid], '')
        self.assertEqual('', cleared['relationships'][0]['note'])
        with self.assertRaises(MappingError): core.edit_note(s, [rid], 'x' * 2001)

    def test_invalid_actions_leave_state_unchanged(self):
        s = self.batch(); before = copy.deepcopy(s)
        cases = [lambda: core.assign(s, [], self.a), lambda: core.assign(s, [element()], 'unknown'),
                 lambda: core.remove(s, []), lambda: core.remove(s, ['missing']),
                 lambda: core.assign(s, [element(category='OST_Doors')], self.a)]
        for action in cases:
            with self.assertRaises(MappingError): action()
            self.assertEqual(before, s)

    def test_wrong_model_modified_workshared_rejected(self):
        for field, value in [('project_information_unique_id', 'another'), ('is_modified', True), ('is_workshared', True)]:
            d = document(); d[field] = value
            with self.assertRaises(MappingError): core.check_binding(self.state, d)

    def test_renamed_path_requires_ui_confirmation_but_native_identity_matches(self):
        d = document(); d['path'] = 'C:/Moved/HOST.rvt'
        core.check_binding(self.state, d)

    def test_missing_and_replacement_never_rebind(self):
        s = self.batch(); before = copy.deepcopy(s)
        resolutions = {'e1': {'status': 'missing'}, 'replacement': {'status': 'resolved', 'element': element('replacement')},
                       'e2': {'status': 'resolved', 'element': element('e2')}}
        report = core.validation_report(s, document(), resolutions)
        self.assertEqual('e1', report['issues'][0]['element_uid'])
        with self.assertRaises(MappingError): core.exchange(s, document(), resolutions)
        self.assertEqual(before, s)

    def test_unchecked_or_ineligible_blocks_export(self):
        s = self.batch()
        for resolution in ({}, {'e1': {'status': 'ineligible'}}):
            with self.assertRaises(MappingError): core.exchange(s, document(), resolution)

    def test_resolver_cannot_substitute_different_identity(self):
        s = self.batch()
        with self.assertRaises(MappingError):
            core.exchange(s, document(), {'e1': {'status': 'resolved', 'element': element('replacement')}})

    def test_export_roundtrip_portable_many_to_many(self):
        s = self.batch(); before = copy.deepcopy(s)
        resolution = dict((uid, {'status': 'resolved', 'element': element(uid)}) for uid in ('e1', 'e2'))
        out = core.exchange(s, document(), resolution)
        core.validate_exchange(json.loads(json.dumps(out)))
        self.assertEqual(3, len(out['relationships']))
        self.assertTrue(out['validation']['time_ready'])
        self.assertNotIn('path', out['model']['native_revision'])
        self.assertEqual(before, s)

    def test_missing_dates_allow_mapping_but_not_time_ready(self):
        s = self.batch()
        s['schedule']['activities'][0]['dates']['StartDate'] = {'state': 'nil', 'value': None}
        core.validate(s)
        resolution = dict((uid, {'status': 'resolved', 'element': element(uid)}) for uid in ('e1', 'e2'))
        out = core.exchange(s, document(), resolution)
        self.assertFalse(out['validation']['time_ready'])
        self.assertTrue(out['validation']['relationship_valid'])

    def test_exchange_invalid_endpoint_and_duplicates_rejected(self):
        s = self.batch()
        resolution = dict((uid, {'status': 'resolved', 'element': element(uid)}) for uid in ('e1', 'e2'))
        out = core.exchange(s, document(), resolution)
        out['relationships'][0]['activity_key'] = 'bad'
        with self.assertRaises(MappingError): core.validate_exchange(out)

    def test_corrupt_or_future_work_refused(self):
        for mutate in [lambda s: s.update(format='future-99'),
                       lambda s: s['relationships'].append(copy.deepcopy(s['relationships'][0])),
                       lambda s: s['relationships'][0].update(activity_key='unknown'),
                       lambda s: s['elements']['e1'].update(unique_id='bad')]:
            s = self.batch(); mutate(s)
            with self.assertRaises(MappingError): core.validate(s)

    def test_schedule_substitution_on_commit_refused(self):
        candidate = copy.deepcopy(self.state)
        candidate['schedule']['project']['Name'] = 'different'
        with self.assertRaises(MappingError): core.revision(candidate, self.state, 'tester', 'edit', [])


class P6Tests(unittest.TestCase):
    def setUp(self):
        self.inspected = p6.inspect(str(SOURCE))
        self.ns = {'p': p6.NAMESPACE}
        self.project = self.inspected['root'].find('p:Project', self.ns)

    def normalize(self): return p6.normalize(self.inspected, '5380')
    def activity(self): return self.project.find('p:Activity', self.ns)
    def tag(self, name): return '{%s}%s' % (p6.NAMESPACE, name)

    @unittest.skipUnless(REAL_SOURCE, 'Optional private fixture: set MAPPER_REAL_P6 to original 009_P6.xml')
    def test_real_source_identity_dates_unicode_counts(self):
        s = p6.normalize(p6.inspect(str(REAL_SOURCE)), '5380')
        self.assertEqual(209, len(s['activities'])); self.assertEqual(72, len(s['wbs']))
        self.assertEqual('545ffe1c0a9e5bb36d98dda09e7bc32336b9ecafcffb88c5492d8cf91b70446e', s['source']['sha256'])
        a = next(a for a in s['activities'] if a['Id'] == 'A1660')
        self.assertEqual('126279', a['ObjectId'])
        self.assertIn('ก่ออิฐ', a['Name'])
        self.assertEqual('2026-10-16T08:00:00', a['dates']['StartDate']['value'])
        self.assertEqual('nil', a['dates']['ActualStartDate']['state'])
        self.assertEqual([], s['warnings'])

    def test_multi_project_select_specific_project(self):
        other = copy.deepcopy(self.project)
        other.find(self.tag('ObjectId')).text = 'other'
        self.inspected['root'].append(other)
        self.assertEqual('5380', self.normalize()['project']['ObjectId'])
        with self.assertRaises(MappingError): p6.normalize(self.inspected, 'missing')

    def test_duplicate_activity_ids_and_guids_rejected(self):
        for field in ('Id', 'ObjectId', 'GUID'):
            source = copy.deepcopy(self.inspected)
            rows = source['root'].find(self.tag('Project')).findall(self.tag('Activity'))
            rows[1].find(self.tag(field)).text = rows[0].find(self.tag(field)).text
            with self.assertRaises(MappingError): p6.normalize(source, '5380')

    def test_missing_guid_allowed(self):
        self.activity().remove(self.activity().find(self.tag('GUID')))
        self.assertIsNone(self.normalize()['activities'][0]['GUID'])

    def test_wbs_cycle_or_orphan_rejected(self):
        w = self.project.find(self.tag('WBS'))
        par = w.find(self.tag('ParentObjectId'))
        par.attrib.clear(); par.text = w.find(self.tag('ObjectId')).text
        with self.assertRaises(MappingError): self.normalize()
        par.text = 'missing'
        with self.assertRaises(MappingError): self.normalize()

    def test_foreign_project_or_wbs_refused(self):
        a = self.activity(); a.find(self.tag('ProjectObjectId')).text = 'wrong'
        with self.assertRaises(MappingError): self.normalize()

    def test_bad_dates_reversed_dates_and_state_mismatch(self):
        with self.assertRaises(MappingError): p6.date_value('2026-02-30T12:00:00')
        self.activity().find(self.tag('StartDate')).text = '2099-01-01T00:00:00'
        with self.assertRaises(MappingError): self.normalize()
        s = schedule(); s['activities'][0]['dates']['StartDate']['state'] = 'nil'
        with self.assertRaises(MappingError): p6.validate(s)

    def test_offsets_and_fraction_preserved(self):
        date = '2026-01-01T07:00:00.123+07:00'
        self.assertEqual(p6.date_value(date), p6.date_value('2026-01-01T00:00:00.123Z'))
        with self.assertRaises(MappingError): p6.date_value('2026-01-01T00:00:00+15:00')

    def test_mixed_timezone_not_time_ready(self):
        s = self.normalize(); a = s['activities'][0]
        a['dates']['StartDate']['value'] += 'Z'
        p6.validate(s)
        self.assertIn('mixed timezone', p6.date_warnings(a)[0])

    def test_repeated_field_rejected(self):
        self.activity().append(copy.deepcopy(self.activity().find(self.tag('Id'))))
        with self.assertRaises(MappingError): self.normalize()

    def test_malformed_wrong_profile_dtd_utf16_and_size_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'bad.xml'
            for data in [b'<bad', b'<Project xmlns="http://schemas.microsoft.com/project"/>',
                         b'<!DOCTYPE a [<!ENTITY foo "x">]><a/>',
                         '<!DOCTYPE a><a/>'.encode('utf-16')]:
                path.write_bytes(data)
                with self.assertRaises(MappingError): p6.inspect(str(path))
            path.write_bytes(b'a' * 11)
            with patch.object(p6, 'LIMIT', 10):
                with self.assertRaises(MappingError): p6.inspect(str(path))


class StorageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.schedule = schedule()
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / 'project.mapping.json')
        self.store = storage.WorkingStore.create(self.path, core.new_work(document(), self.schedule, 'tester'))
        self.a, self.b = [a['key'] for a in self.schedule['activities'][:2]]
    def tearDown(self):
        self.store.close(); self.tmp.cleanup()
    def add(self):
        candidate, ids = core.assign(self.store.state, [element('e1'), element('e2')], self.a)
        self.store.commit(candidate, 'assign', ids, 'tester')
    def bytes(self): return Path(self.path).read_bytes()

    def test_full_roundtrip_add_reassign_note_remove_undo(self):
        self.add()
        s, ids = core.assign(self.store.state, [element('e1')], self.b)
        self.store.commit(s, 'assign', ids, 'tester')
        rid = self.store.state['relationships'][0]['id']
        s, ids = core.edit_note(self.store.state, [rid], 'งานเหล็ก')
        self.store.commit(s, 'note', ids, 'tester')
        s, ids = core.remove(self.store.state, [rid]); self.store.commit(s, 'remove', ids, 'tester')
        self.store.undo('tester')
        expected = copy.deepcopy(self.store.state)
        self.store.close(); self.store = storage.WorkingStore.open(self.path)
        self.assertEqual(expected, self.store.state)
        self.assertEqual(3, len(self.store.state['relationships']))
        self.assertEqual('งานเหล็ก', self.store.state['relationships'][0]['note'])
        self.assertEqual(5, self.store.state['revision'])
        self.assertIsNone(self.store.undo_state)
        self.assertEqual(4, storage.read(self.path + '.bak')[0]['revision'])

    def test_noop_does_not_advance_revision(self):
        self.add(); before = self.bytes()
        candidate, ids = core.assign(self.store.state, [element('e1')], self.a)
        self.assertFalse(self.store.commit(candidate, 'assign', ids, 'tester'))
        self.assertEqual(before, self.bytes())

    def test_failed_replace_preserves_memory_and_disk_reopen(self):
        self.add(); before = self.bytes(); state = copy.deepcopy(self.store.state)
        candidate, ids = core.assign(state, [element('e1')], self.b)
        with patch.object(storage, '_replace', side_effect=IOError('simulated disk failure')):
            with self.assertRaises(IOError): self.store.commit(candidate, 'assign', ids, 'tester')
        self.assertEqual(before, self.bytes()); self.assertEqual(state, self.store.state)
        self.assertEqual([], list(Path(self.tmp.name).glob('*.tmp-*')))
        self.store.close(); self.store = storage.WorkingStore.open(self.path)
        self.assertEqual(state, self.store.state)

    def test_failed_staging_preserves_work(self):
        before = self.bytes(); candidate, ids = core.assign(self.store.state, [element()], self.a)
        with patch.object(storage, '_temp_write', side_effect=IOError('disk full')):
            with self.assertRaises(IOError): self.store.commit(candidate, 'assign', ids, 'tester')
        self.assertEqual(before, self.bytes()); self.assertEqual(0, self.store.state['revision'])

    def test_external_change_refuses_overwrite(self):
        self.add()
        Path(self.path).write_bytes(self.bytes() + b'\n')
        before = self.bytes(); candidate, ids = core.assign(self.store.state, [element()], self.b)
        with self.assertRaisesRegex(MappingError, 'changed outside'):
            self.store.commit(candidate, 'assign', ids, 'tester')
        self.assertEqual(before, self.bytes())

    def test_second_writer_blocked_and_crash_release(self):
        with self.assertRaises(MappingError): storage.WorkingStore.open(self.path)
        code = 'from suzanoo_mapping.storage import WorkingStore; WorkingStore.open(%r)' % self.path
        env = dict(os.environ, PYTHONPATH=str(LIB))
        blocked = subprocess.run([sys.executable, '-c', code], env=env, capture_output=True)
        self.assertNotEqual(0, blocked.returncode)
        self.store.close()
        code += '; import os; os._exit(0)'
        crashed = subprocess.run([sys.executable, '-c', code], env=env, capture_output=True)
        self.assertEqual(0, crashed.returncode, crashed.stderr)
        self.store = storage.WorkingStore.open(self.path)

    def test_backup_recovery_to_new_never_overwrites_original(self):
        self.add(); first = copy.deepcopy(self.store.state)
        s, ids = core.assign(first, [element('e1')], self.b); self.store.commit(s, 'assign', ids, 'tester')
        before = self.bytes(); new = str(Path(self.tmp.name) / 'recovered.mapping.json')
        recovered = storage.recover_to_new(self.path + '.bak', new, 'tester')
        try:
            self.assertEqual(first['relationships'], recovered.state['relationships'])
            self.assertEqual('recover-backup-to-new-file', recovered.state['history'][-1]['action'])
        finally: recovered.close()
        self.assertEqual(before, self.bytes())
        with self.assertRaises(Exception): storage.recover_to_new(self.path + '.bak', self.path, 'tester')
        self.assertEqual(before, self.bytes())

    def test_duplicate_keys_future_schema_and_corrupt_file_never_rewritten(self):
        bad = Path(self.tmp.name) / 'bad.mapping.json'
        for data in [b'{"format":"x","format":"y"}', b'{oops', b'{}', b'{"x": NaN}']:
            bad.write_bytes(data)
            with self.assertRaises(MappingError): storage.WorkingStore.open(str(bad))
            self.assertEqual(data, bad.read_bytes())

    def test_existing_export_not_overwritten(self):
        before = self.bytes()
        with self.assertRaises(MappingError): storage.write_new(self.path, {})
        self.assertEqual(before, self.bytes())

    def test_read_only_source_not_needed_for_resume(self):
        self.add(); self.store.close()
        with patch.object(p6, 'inspect', side_effect=AssertionError('must not read XML')):
            self.store = storage.WorkingStore.open(self.path)
        self.assertEqual(2, len(self.store.state['relationships']))


if __name__ == '__main__': unittest.main()
