# -*- coding: utf-8 -*-
"""Plain-data relationship transactions. No Revit or UI imports."""
from __future__ import unicode_literals
import copy
import datetime
import uuid
from . import VERSION
from . import p6
from .p6 import MappingError

WORK_FORMAT = 'suzanoo-mapping-work-1'
EXCHANGE_FORMAT = 'suzanoo-mapping-exchange-1-pilot'
CATEGORIES = ('OST_Walls', 'OST_Floors', 'OST_StructuralColumns', 'OST_StructuralFraming')
try:
    TEXT = (basestring,)
    as_text = unicode
except NameError:
    TEXT = (str,)
    as_text = str


def utc():
    return datetime.datetime.utcnow().isoformat() + 'Z'


def key(prefix):
    return prefix + ':' + uuid.uuid4().hex


def require_text(v, label):
    if not isinstance(v, TEXT) or not v.strip():
        raise MappingError('Missing/invalid ' + label)


def new_work(document, schedule, actor):
    validate_document(document)
    p6.validate(schedule)
    now = utc()
    return {'format': WORK_FORMAT, 'producer_version': VERSION,
            'working_id': key('work'), 'revision': 0, 'created_utc': now, 'updated_utc': now,
            'model': {'key': key('model'), 'binding': copy.deepcopy(document)},
            'schedule': copy.deepcopy(schedule), 'elements': {}, 'relationships': [],
            'history': [{'revision': 0, 'utc': now, 'actor': actor, 'action': 'create',
                         'relationship_ids': []}]}


def validate_document(d):
    require_text(d['project_information_unique_id'], 'ProjectInformation UniqueId')
    require_text(d['path'], 'saved model path')
    require_text(d['title'], 'model title')
    if d['is_modified'] is not False or d['is_workshared'] is not False:
        raise MappingError('Pilot requires a saved, unmodified, non-workshared host model.')


def check_binding(state, document):
    validate_document(document)
    if state['model']['binding']['project_information_unique_id'] != document['project_information_unique_id']:
        raise MappingError('This RVT has a different ProjectInformation identity. Open the bound model.')
    # Copies can preserve this ID: the UI additionally asks for lineage confirmation.


def validate_element(e):
    require_text(e['unique_id'], 'element UniqueId')
    require_text(e['element_id'], 'element diagnostic Id')
    if e['scope'] != 'native-host' or e['category_builtin'] not in CATEGORIES:
        raise MappingError('Only supported native host instances are eligible.')
    require_text(e['category'], 'element category')
    if not isinstance(e['level'], dict) or not e['level'].get('basis'):
        raise MappingError('Level provenance required (unknown is permitted).')


def validate(state):
    try:
        if state['format'] != WORK_FORMAT:
            raise MappingError('Unsupported working-file format. No automatic migration.')
        require_text(state['working_id'], 'working document identity')
        require_text(state['model']['key'], 'logical model key')
        if not isinstance(state['revision'], int) or isinstance(state['revision'], bool) or state['revision'] < 0:
            raise MappingError('Invalid working revision.')
        validate_document(state['model']['binding'])
        p6.validate(state['schedule'])
        if not isinstance(state['elements'], dict) or not isinstance(state['relationships'], list):
            raise MappingError('Invalid element/relationship collections.')
        for uid, e in state['elements'].items():
            validate_element(e)
            if uid != e['unique_id']:
                raise MappingError('Element identity mismatch.')
        acts = set(a['key'] for a in state['schedule']['activities'])
        ids, pairs = set(), set()
        for r in state['relationships']:
            require_text(r['id'], 'relationship identity')
            pair = (r['element_uid'], r['activity_key'])
            if r['id'] in ids or pair in pairs:
                raise MappingError('Duplicate relationship identity or endpoint pair.')
            ids.add(r['id']); pairs.add(pair)
            if r['element_uid'] not in state['elements'] or r['activity_key'] not in acts:
                raise MappingError('Unresolved stored relationship endpoint.')
            if r['scope'] != 'whole-element' or r['meaning'] != 'associated-work':
                raise MappingError('Unsupported relationship scope/meaning.')
            if not isinstance(r['note'], TEXT) or len(r['note']) > 2000:
                raise MappingError('Relationship note must be text, at most 2000 characters.')
            require_text(r['created_utc'], 'relationship creation time')
            require_text(r['updated_utc'], 'relationship update time')
        history = state['history']
        if not isinstance(history, list) or not history or history[-1]['revision'] != state['revision']:
            raise MappingError('Invalid history/revision.')
    except (KeyError, TypeError, AttributeError) as ex:
        raise MappingError('Incomplete working document: %s' % ex)


def _activity(state, activity_key):
    if activity_key not in set(a['key'] for a in state['schedule']['activities']):
        raise MappingError('Choose an activity in the imported schedule snapshot.')


def _selected(state, ids):
    ids = set(ids)
    if not ids:
        raise MappingError('Select one or more relationship rows first.')
    rows = [r for r in state['relationships'] if r['id'] in ids]
    if len(rows) != len(ids):
        raise MappingError('Selected relationships are stale; refresh the review.')
    return rows


def assign(state, elements, activity_key):
    _activity(state, activity_key)
    if not elements:
        raise MappingError('No eligible selected host elements.')
    result = copy.deepcopy(state)
    pairs = set((r['element_uid'], r['activity_key']) for r in result['relationships'])
    added = []
    for e in elements:
        validate_element(e)
        pair = (e['unique_id'], activity_key)
        if pair in pairs:
            continue
        pairs.add(pair)
        result['elements'][e['unique_id']] = copy.deepcopy(e)
        now = utc()
        r = {'id': key('rel'), 'element_uid': e['unique_id'], 'activity_key': activity_key,
             'scope': 'whole-element', 'meaning': 'associated-work', 'note': '',
             'created_utc': now, 'updated_utc': now}
        result['relationships'].append(r)
        added.append(r['id'])
    return result, added


def remove(state, ids):
    rows = _selected(state, ids)
    selected = set(r['id'] for r in rows)
    result = copy.deepcopy(state)
    result['relationships'] = [r for r in result['relationships'] if r['id'] not in selected]
    return result, sorted(selected)


def reassign(state, ids, activity_key):
    _activity(state, activity_key)
    selected = set(r['id'] for r in _selected(state, ids))
    result = copy.deepcopy(state)
    changed = []
    for r in result['relationships']:
        if r['id'] in selected and r['activity_key'] != activity_key:
            r['activity_key'] = activity_key
            r['updated_utc'] = utc()
            changed.append(r['id'])
    pairs = [(r['element_uid'], r['activity_key']) for r in result['relationships']]
    if len(pairs) != len(set(pairs)):
        raise MappingError('Reassign would duplicate an existing element/activity pair. '
                           'Nothing changed. Remove the redundant old relationship explicitly, '
                           'or select a different target activity.')
    return result, changed


def edit_note(state, ids, note):
    if not isinstance(note, TEXT) or len(note) > 2000:
        raise MappingError('Note limit is 2000 characters.')
    selected = set(r['id'] for r in _selected(state, ids))
    result = copy.deepcopy(state)
    changed = []
    for r in result['relationships']:
        if r['id'] in selected and r['note'] != note:
            r['note'] = note
            r['updated_utc'] = utc()
            changed.append(r['id'])
    return result, changed


def revision(candidate, before, actor, action, ids):
    result = copy.deepcopy(candidate)
    if result['working_id'] != before['working_id'] or result['schedule'] != before['schedule']:
        raise MappingError('Working identity/schedule substitution refused.')
    if result['model'] != before['model']:
        raise MappingError('Model substitution refused.')
    result['revision'] = before['revision'] + 1
    result['updated_utc'] = utc()
    result['history'] = copy.deepcopy(before['history']) + [{
        'revision': result['revision'], 'utc': result['updated_utc'],
        'actor': actor, 'action': action, 'relationship_ids': list(ids)}]
    validate(result)
    return result


def validation_report(state, document, resolution):
    validate(state)
    check_binding(state, document)
    used = sorted(set(r['element_uid'] for r in state['relationships']))
    issues = []
    for uid in used:
        row = resolution.get(uid, {'status': 'unchecked'})
        if row.get('status') != 'resolved':
            issues.append({'element_uid': uid, 'status': row.get('status', 'unchecked'),
                           'reason': row.get('reason', 'Native identity not resolved.')})
        else:
            validate_element(row['element'])
            if row['element']['unique_id'] != uid:
                raise MappingError('Resolver returned a different native identity.')
    used_acts = set(r['activity_key'] for r in state['relationships'])
    date_issues = [{'activity': a['Id'], 'issues': p6.date_warnings(a)}
                   for a in state['schedule']['activities'] if a['key'] in used_acts and p6.date_warnings(a)]
    return {'checked_utc': utc(), 'working_revision': state['revision'],
            'document': copy.deepcopy(document), 'element_count': len(used),
            'relationship_count': len(state['relationships']), 'issues': issues,
            'relationship_valid': not issues, 'date_issues': date_issues,
            'time_ready': not issues and not date_issues and bool(used),
            'geometry_correspondence': 'not-evaluated; no renderer integration'}


def exchange(state, document, resolution):
    report = validation_report(state, document, resolution)
    if report['issues']:
        raise MappingError('Export blocked: %d unresolved elements. Review/remove only the intended relationships.' % len(report['issues']))
    used = sorted(set(r['element_uid'] for r in state['relationships']))
    result = {'format': EXCHANGE_FORMAT, 'producer_version': VERSION,
              'exported_utc': utc(), 'origin': {'working_id': state['working_id'],
              'revision': state['revision'], 'model_key': state['model']['key']},
              'model': {'key': state['model']['key'], 'native_revision': copy.deepcopy(document)},
              'schedule': copy.deepcopy(state['schedule']),
              'elements': [copy.deepcopy(resolution[uid]['element']) for uid in used],
              'relationships': copy.deepcopy(state['relationships']), 'validation': report}
    # Exports are portable: no workstation path is needed to consume them.
    result['model']['native_revision'].pop('path', None)
    result['validation']['document'].pop('path', None)
    validate_exchange(result)
    return result


def validate_exchange(data):
    try:
        if data['format'] != EXCHANGE_FORMAT:
            raise MappingError('Unsupported exchange format.')
        p6.validate(data['schedule'])
        uids, pairs, ids = set(), set(), set()
        for e in data['elements']:
            validate_element(e)
            if e['unique_id'] in uids:
                raise MappingError('Duplicate exchange element.')
            uids.add(e['unique_id'])
        acts = set(a['key'] for a in data['schedule']['activities'])
        for r in data['relationships']:
            require_text(r['id'], 'exchange relationship identity')
            pair = (r['element_uid'], r['activity_key'])
            if pair in pairs or r['id'] in ids or pair[0] not in uids or pair[1] not in acts:
                raise MappingError('Invalid exchange relationship endpoints/uniqueness.')
            pairs.add(pair); ids.add(r['id'])
            if r['scope'] != 'whole-element' or r['meaning'] != 'associated-work':
                raise MappingError('Invalid exchange relationship semantics.')
            if not isinstance(r['note'], TEXT) or len(r['note']) > 2000:
                raise MappingError('Invalid exchange relationship note.')
            require_text(r['created_utc'], 'exchange relationship creation time')
            require_text(r['updated_utc'], 'exchange relationship update time')
        require_text(data['model']['key'], 'exchange model key')
        require_text(data['origin']['working_id'], 'exchange working identity')
        native = data['model']['native_revision']
        require_text(native['project_information_unique_id'], 'exchange native model evidence')
        if native['is_modified'] is not False or native['is_workshared'] is not False:
            raise MappingError('Exchange must reference a saved qualified host.')
        if data['validation']['document'] != native:
            raise MappingError('Exchange validation model evidence mismatch.')
        used_activities = set(r['activity_key'] for r in data['relationships'])
        ready = bool(pairs) and not any(p6.date_warnings(a) for a in data['schedule']['activities']
                                       if a['key'] in used_activities)
        if data['validation']['time_ready'] is not ready:
            raise MappingError('Exchange date readiness mismatch.')
        if (data['origin']['model_key'] != data['model']['key'] or
                not data['validation']['relationship_valid'] or data['validation']['issues'] or
                data['validation']['relationship_count'] != len(pairs) or
                data['validation']['element_count'] != len(uids) or
                data['origin']['revision'] != data['validation']['working_revision']):
            raise MappingError('Exchange validation/provenance mismatch.')
    except (KeyError, TypeError, AttributeError) as ex:
        raise MappingError('Incomplete exchange: %s' % ex)
