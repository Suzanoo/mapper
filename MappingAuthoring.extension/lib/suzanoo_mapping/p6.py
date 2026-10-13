# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import datetime
import hashlib
import os
import re
import xml.etree.ElementTree as ET

# Only the profile actually qualified with the PO source is enabled.
NAMESPACE = 'http://xmlns.oracle.com/Primavera/P6Professional/V24.12/API/BusinessObjects'
LIMIT = 20 * 1024 * 1024
DATE_FIELDS = ('StartDate', 'FinishDate', 'PlannedStartDate', 'PlannedFinishDate',
               'ActualStartDate', 'ActualFinishDate', 'RemainingEarlyStartDate',
               'RemainingEarlyFinishDate')
ACT_FIELDS = ('ObjectId', 'GUID', 'Id', 'Name', 'ProjectObjectId', 'WBSObjectId',
              'Type', 'Status', 'CalendarObjectId', 'PercentCompleteType',
              'PercentComplete', 'PhysicalPercentComplete', 'DurationPercentComplete',
              'PlannedDuration')


class MappingError(ValueError):
    pass


def field(node, key):
    values = node.findall('{%s}%s' % (NAMESPACE, key))
    if len(values) > 1:
        raise MappingError('Repeated XML field: ' + key)
    if not values:
        return {'state': 'missing', 'value': None}
    e = values[0]
    if e.get('{http://www.w3.org/2001/XMLSchema-instance}nil') in ('true', '1'):
        return {'state': 'nil', 'value': None}
    return {'state': 'value' if e.text else 'empty', 'value': e.text or None}


def value(node, key):
    return field(node, key)['value']


def date_value(text):
    """Validate ISO source timestamp. Return comparable UTC/naive tuple; keep raw text."""
    if text is None:
        return None
    m = re.match(r'^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(\.\d{1,6})?(Z|[+-]\d{2}:\d{2})?$', text)
    if not m:
        raise MappingError('Unsupported date: ' + text)
    try:
        dt = datetime.datetime.strptime(m.group(1), '%Y-%m-%dT%H:%M:%S')
        if m.group(2):
            dt = dt.replace(microsecond=int(m.group(2)[1:].ljust(6, '0')))
        zone = m.group(3)
        if zone and zone != 'Z':
            h, minute = int(zone[1:3]), int(zone[4:6])
            if h > 14 or minute > 59 or (h == 14 and minute):
                raise ValueError('offset out of range')
            delta = datetime.timedelta(hours=h, minutes=minute)
            dt = dt - delta if zone[0] == '+' else dt + delta
        return (bool(zone), dt)
    except ValueError as ex:
        raise MappingError('Invalid date %s: %s' % (text, ex))


def unique(rows, key, label, optional=False):
    seen = set()
    for row in rows:
        v = row.get(key)
        if not v:
            if optional:
                continue
            raise MappingError('Missing ' + label)
        k = v.strip('{}').lower() if key == 'GUID' else v
        if k in seen:
            raise MappingError('Duplicate %s: %s' % (label, v))
        seen.add(k)


def inspect(path):
    with open(path, 'rb') as f:
        data = f.read(LIMIT + 1)
    if len(data) > LIMIT:
        raise MappingError('P6 XML exceeds the pilot limit of 20 MiB.')
    scan = data.replace(b'\x00', b'').upper()
    if b'<!DOCTYPE' in scan or b'<!ENTITY' in scan:
        raise MappingError('DTD/entity declarations are not allowed.')
    try:
        root = ET.fromstring(data)
    except ET.ParseError as ex:
        raise MappingError('Malformed P6 XML: %s' % ex)
    if root.tag != '{%s}APIBusinessObjects' % NAMESPACE:
        raise MappingError('Use P6 Professional V24.12 XML. Other profiles and MSP are not qualified.')
    projects = root.findall('{%s}Project' % NAMESPACE)
    rows = [dict((k, value(p, k)) for k in ('ObjectId', 'Id', 'Name')) for p in projects]
    unique(rows, 'ObjectId', 'project ObjectId')
    if not rows:
        raise MappingError('No P6 projects found.')
    return {'root': root, 'projects': rows, 'source': {
        'kind': 'p6-xml', 'file': os.path.basename(path),
        'sha256': hashlib.sha256(data).hexdigest(), 'namespace': NAMESPACE}}


def normalize(inspected, project_id):
    root = inspected['root']
    matches = [p for p in root.findall('{%s}Project' % NAMESPACE)
               if value(p, 'ObjectId') == project_id]
    if len(matches) != 1:
        raise MappingError('Select exactly one existing P6 project.')
    p = matches[0]
    project = dict((k, value(p, k)) for k in ('ObjectId', 'GUID', 'Id', 'Name', 'DataDate', 'WBSObjectId'))
    snapshot = 'p6:' + inspected['source']['sha256'] + ':' + project_id
    wbs = [dict((k, value(n, k)) for k in ('ObjectId', 'GUID', 'Code', 'Name',
           'ParentObjectId', 'ProjectObjectId', 'SequenceNumber'))
           for n in p.findall('{%s}WBS' % NAMESPACE)]
    activities = []
    for n in p.findall('{%s}Activity' % NAMESPACE):
        row = dict((k, value(n, k)) for k in ACT_FIELDS)
        row['key'] = snapshot + ':activity:' + (row['ObjectId'] or '')
        row['source_order'] = len(activities)
        row['dates'] = dict((k, field(n, k)) for k in DATE_FIELDS)
        activities.append(row)
    schedule = {'normalization_version': 1, 'snapshot_key': snapshot,
                'source': inspected['source'], 'project': project, 'wbs': wbs,
                'activities': activities, 'date_basis': 'P6 current StartDate/FinishDate',
                'timezone_policy': 'Preserve source offsets; absent offset stays unspecified.',
                'warnings': []}
    validate(schedule)
    for a in activities:
        for message in date_warnings(a):
            schedule['warnings'].append('%s: %s' % (a['Id'], message))
    return schedule


def date_warnings(a):
    start, finish = (a['dates'][k]['value'] for k in ('StartDate', 'FinishDate'))
    if not start or not finish:
        return ['current StartDate/FinishDate incomplete; not time-ready']
    s, f = date_value(start), date_value(finish)
    if s[0] != f[0]:
        return ['mixed timezone awareness; not time-ready']
    return []


def validate(schedule):
    try:
        if (schedule['normalization_version'] != 1 or schedule['source']['namespace'] != NAMESPACE or
                schedule['source']['kind'] != 'p6-xml' or
                schedule['date_basis'] != 'P6 current StartDate/FinishDate'):
            raise MappingError('Unsupported schedule normalization/profile.')
        source_hash = schedule['source']['sha256']
        if not re.match(r'^[0-9a-f]{64}$', source_hash):
            raise MappingError('Invalid P6 source checksum.')
        p = schedule['project']
        if not p['ObjectId'] or not p['Id'] or not p['Name']:
            raise MappingError('Project ObjectId, Id and Name required.')
        date_value(p.get('DataDate'))
        expected = 'p6:' + source_hash + ':' + p['ObjectId']
        if schedule['snapshot_key'] != expected:
            raise MappingError('Schedule snapshot identity mismatch.')
        wbs, activities = schedule['wbs'], schedule['activities']
        unique(wbs, 'ObjectId', 'WBS ObjectId')
        by_wbs = dict((r['ObjectId'], r) for r in wbs)
        for r in wbs:
            if r['ProjectObjectId'] != p['ObjectId']:
                raise MappingError('WBS belongs to another project.')
            current, seen = r, set()
            while current:
                if current['ObjectId'] in seen:
                    raise MappingError('WBS cycle detected.')
                seen.add(current['ObjectId'])
                parent = current['ParentObjectId']
                if parent and parent not in by_wbs:
                    raise MappingError('Unresolved WBS parent: ' + parent)
                current = by_wbs.get(parent)
        if not activities:
            raise MappingError('No activities in selected project.')
        for k in ('ObjectId', 'Id', 'key'):
            unique(activities, k, 'activity ' + k)
        unique(activities, 'GUID', 'activity GUID', optional=True)
        for a in activities:
            if a['ProjectObjectId'] != p['ObjectId'] or a['WBSObjectId'] not in by_wbs:
                raise MappingError('Activity project/WBS endpoint is invalid: ' + a['Id'])
            if not a['Name'] or a['key'] != expected + ':activity:' + a['ObjectId']:
                raise MappingError('Activity name/key is invalid.')
            for k in DATE_FIELDS:
                d = a['dates'][k]
                if d['state'] not in ('value', 'missing', 'nil', 'empty'):
                    raise MappingError('Invalid date state.')
                if (d['state'] == 'value') != bool(d['value']):
                    raise MappingError('Date state/value mismatch.')
                date_value(d['value'])
            s, f = [date_value(a['dates'][k]['value']) for k in ('StartDate', 'FinishDate')]
            if s and f and s[0] == f[0] and s[1] > f[1]:
                raise MappingError('StartDate is after FinishDate: ' + a['Id'])
    except (KeyError, TypeError, AttributeError) as ex:
        raise MappingError('Incomplete schedule data: %s' % ex)


def wbs_path(schedule, wbs_id):
    rows = dict((r['ObjectId'], r) for r in schedule['wbs'])
    parts = []
    while wbs_id:
        r = rows[wbs_id]
        parts.append('%s %s' % (r.get('Code') or '', r.get('Name') or ''))
        wbs_id = r['ParentObjectId']
    return ' / '.join(reversed(parts))
