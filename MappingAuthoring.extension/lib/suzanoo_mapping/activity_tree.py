# -*- coding: utf-8 -*-
"""Presentation only. Never changes normalized schedule records or mapping keys."""
from __future__ import unicode_literals
from collections import Counter


def build(schedule):
    """Return a forest, retaining every WBS/activity record exactly once.

    Invalid references get a visible diagnostic branch, not an invented WBS.
    This defensive view does not relax the existing import/work-file validator.
    Input list order is preserved within sibling groups (WBS before activities).
    """
    rows = schedule.get('wbs', [])
    activities = schedule.get('activities', [])
    counts = Counter(r.get('ObjectId') for r in rows)
    lookup = dict((r.get('ObjectId'), i) for i, r in enumerate(rows)
                  if r.get('ObjectId') and counts[r.get('ObjectId')] == 1)
    nodes, parents, warnings = [], {}, []
    for i, row in enumerate(rows):
        ident, parent = row.get('ObjectId'), row.get('ParentObjectId')
        reason = ''
        if not ident or counts[ident] != 1:
            reason = 'Missing or duplicate WBS ObjectId'
        elif parent and parent not in lookup:
            reason = 'Unresolved or ambiguous WBS parent: %s' % parent
        parents[i] = lookup.get(parent) if parent and not reason else None
        nodes.append({'id': ('wbs', i), 'kind': 'wbs', 'activity_key': None,
                      'label': '[WBS] %s | %s' % (row.get('Code') or '(no code)', row.get('Name') or '(unnamed)'),
                      'reason': reason, 'children': []})
    # Functional graph cycle detection; iterative, including disconnected cycles.
    done = set()
    for start in range(len(nodes)):
        trail, positions, current = [], {}, start
        while current is not None and current not in done:
            if current in positions:
                for i in trail[positions[current]:]:
                    parents[i] = None
                    nodes[i]['reason'] = 'WBS parent cycle; source hierarchy requires review'
                break
            positions[current] = len(trail)
            trail.append(current)
            current = parents[current]
        done.update(trail)
    roots = []
    issues = {'id': ('issues', 0), 'kind': 'group', 'activity_key': None,
              'label': '[Review] Unresolved WBS / identity', 'reason': 'Presentation fallback only; source data unchanged',
              'children': []}
    for i, node in enumerate(nodes):
        if node['reason']:
            issues['children'].append(node)
            warnings.append(node['label'] + ': ' + node['reason'])
        elif parents[i] is not None:
            nodes[parents[i]]['children'].append(node)
        else:
            roots.append(node)
    act_counts = Counter(a.get('key') for a in activities)
    for i, activity in enumerate(activities):
        key, wbs = activity.get('key'), activity.get('WBSObjectId')
        reason = '' if wbs in lookup else 'Missing, unknown or ambiguous WBS reference: %s' % wbs
        selectable = bool(key) and act_counts[key] == 1
        if not selectable:
            reason = (reason + '; ' if reason else '') + 'Missing/duplicate Activity key: selection disabled'
        node = {'id': ('activity', i), 'kind': 'activity',
                'activity_key': key if selectable else None,
                'label': '%s | %s' % (activity.get('Id') or '(no code)', activity.get('Name') or '(unnamed)'),
                'reason': reason, 'children': []}
        if wbs in lookup:
            nodes[lookup[wbs]]['children'].append(node)
        else:
            issues['children'].append(node)
        if reason:
            warnings.append(node['label'] + ': ' + reason)
    if issues['children']:
        roots.append(issues)
    return {'roots': roots, 'warnings': warnings, 'activity_count': len(activities)}


def walk(roots):
    """Preorder, no recursion limit for a deep imported hierarchy."""
    stack = list(reversed(roots))
    while stack:
        node = stack.pop()
        yield node
        stack.extend(reversed(node['children']))


def filtered(roots, term):
    """Keep matches, their ancestors, and descendants of matching WBS nodes."""
    term = term.strip().lower()
    if not term:
        return roots
    result, stack = [], []
    for n in reversed(roots):
        stack.append((n, result, False))
    order = []
    while stack:
        node, output, inherited = stack.pop()
        match = inherited or term in (node['label'] + ' ' + node['reason']).lower()
        clone = dict(node, children=[])
        output.append(clone)
        order.append((clone, output, match))
        for child in reversed(node['children']):
            stack.append((child, clone['children'], match))
    for node, output, match in reversed(order):
        if not match and not node['children']:
            output.remove(node)
    return result


def selected_key(node):
    """WBS/group headings can be selected for navigation but never assigned."""
    if node and node.get('kind') == 'activity':
        return node.get('activity_key')
    return None
