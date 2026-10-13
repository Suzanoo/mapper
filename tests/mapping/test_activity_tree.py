# -*- coding: utf-8 -*-
"""UI-01 tree projection and headless selection/command regression tests."""
import copy
import unittest
from unittest.mock import patch
import test_mapping as fixtures
import test_revit_boundary as boundary
from suzanoo_mapping import activity_tree as tree, core


class HierarchyTests(unittest.TestCase):
    def setUp(self):
        self.schedule = fixtures.schedule()

    def leaves(self, roots):
        return [n for n in tree.walk(roots) if n['kind'] == 'activity']

    def test_parent_child_forest_and_exact_activity_membership(self):
        result = tree.build(self.schedule)
        self.assertEqual(2, len(result['roots']))
        building = result['roots'][0]
        self.assertEqual(2, len(building['children']))
        self.assertEqual(2, len(building['children'][0]['children']))
        self.assertEqual(1, len(building['children'][1]['children']))
        self.assertEqual([a['key'] for a in self.schedule['activities']], [tree.selected_key(n) for n in self.leaves(result['roots'])])
        self.assertEqual([], result['warnings'])

    def test_duplicate_names_do_not_merge_identities(self):
        for r in self.schedule['wbs']:
            r['Code'] = 'SAME'; r['Name'] = 'ชื่อซ้ำ'
        for a in self.schedule['activities']:
            a['Name'] = 'Same name'
        result = tree.build(self.schedule)
        self.assertEqual(4, sum(n['kind'] == 'wbs' for n in tree.walk(result['roots'])))
        self.assertEqual(3, len(set(n['activity_key'] for n in self.leaves(result['roots']))))

    def test_child_before_parent_and_empty_wbs_not_lost(self):
        self.schedule['wbs'].reverse()
        result = tree.build(self.schedule)
        self.assertEqual(4, sum(n['kind'] == 'wbs' for n in tree.walk(result['roots'])))
        self.assertEqual(3, len(self.leaves(result['roots'])))
        self.assertEqual([], result['warnings'])

    def test_activity_missing_unknown_or_nil_wbs_stays_visible(self):
        for a, ref in zip(self.schedule['activities'], [None, '', 'missing']):
            a['WBSObjectId'] = ref
        result = tree.build(self.schedule)
        self.assertEqual('group', result['roots'][-1]['kind'])
        self.assertEqual(3, len(result['roots'][-1]['children']))
        self.assertEqual(3, len(result['warnings']))
        self.assertTrue(all(tree.selected_key(n) for n in self.leaves(result['roots'])))

    def test_orphan_parent_cycle_and_descendants_are_finite_and_complete(self):
        self.schedule['wbs'][0]['ParentObjectId'] = '11'
        self.schedule['wbs'][3]['ParentObjectId'] = 'not-present'
        result = tree.build(self.schedule)
        all_nodes = list(tree.walk(result['roots']))
        self.assertEqual(8, len(all_nodes))  # 4 WBS + 3 activities + diagnostic group
        self.assertEqual(3, len(result['warnings']))
        self.assertEqual(3, len(self.leaves(result['roots'])))

    def test_duplicate_wbs_ids_and_missing_id_do_not_drop_records(self):
        self.schedule['wbs'][1]['ObjectId'] = '10'
        self.schedule['wbs'][3]['ObjectId'] = None
        result = tree.build(self.schedule)
        self.assertEqual(4, sum(n['kind'] == 'wbs' for n in tree.walk(result['roots'])))
        self.assertEqual(3, len(self.leaves(result['roots'])))
        self.assertTrue(result['warnings'])

    def test_duplicate_or_missing_activity_key_visible_but_not_selectable(self):
        self.schedule['activities'][1]['key'] = self.schedule['activities'][0]['key']
        self.schedule['activities'][2]['key'] = None
        leaves = self.leaves(tree.build(self.schedule)['roots'])
        self.assertEqual(3, len(leaves))
        self.assertTrue(all(tree.selected_key(n) is None for n in leaves))

    def test_search_preserves_ancestors_and_thai_text(self):
        roots = tree.build(self.schedule)['roots']
        filtered = tree.filtered(roots, 'งานเหล็ก')
        self.assertEqual(1, len(filtered)); self.assertIn('Building', filtered[0]['label'])
        self.assertEqual(1, len(self.leaves(filtered)))
        self.assertIn('งานเหล็ก', self.leaves(filtered)[0]['label'])

    def test_wbs_search_includes_descendant_activities_and_no_match_empty(self):
        roots = tree.build(self.schedule)['roots']
        self.assertEqual(2, len(self.leaves(tree.filtered(roots, 'ชั้น 1'))))
        self.assertEqual([], tree.filtered(roots, 'no-such-label'))

    def test_presentation_never_mutates_schedule(self):
        before = copy.deepcopy(self.schedule)
        result = tree.build(self.schedule)
        tree.filtered(result['roots'], 'A100')
        self.assertEqual(before, self.schedule)

    def test_deep_hierarchy_avoids_python_recursion(self):
        schedule = {'activities': [], 'wbs': [{'ObjectId': str(i), 'ParentObjectId': str(i-1) if i else None,
                    'Code': str(i), 'Name': 'node'} for i in range(1200)]}
        result = tree.build(schedule)
        self.assertEqual(1200, len(list(tree.walk(result['roots']))))
        self.assertEqual(1200, len(list(tree.walk(tree.filtered(result['roots'], '1199')))))

    def test_headings_are_never_activity_targets(self):
        result = tree.build(self.schedule)
        self.assertIsNone(tree.selected_key(result['roots'][0]))
        self.assertIsNone(tree.selected_key(None))


class TreeSelectionTests(unittest.TestCase):
    # Reuse the setup, not inherited test cases (no double counting).
    setUp = boundary.UIFlowTests.setUp
    tearDown = boundary.UIFlowTests.tearDown
    perform = boundary.UIFlowTests.perform
    bytes = boundary.UIFlowTests.bytes

    @classmethod
    def setUpClass(cls): cls.sched = fixtures.schedule()

    def select(self, key=None, kind='activity'):
        self.window.fill_activities()
        for item in self.window._tree_items.values(): item.IsSelected = False
        item = next(i for i in self.window._tree_items.values()
                    if i.Tag['kind'] == kind and (key is None or i.Tag['activity_key'] == key))
        item.IsSelected = True
        self.window.on_activity_changed(None, None)
        return item

    def test_selected_leaf_drives_add_many_to_many_reassign_and_reopen(self):
        self.sel.ids = [boundary.Id(1), boundary.Id(2)]; self.perform('capture')
        for key in (self.a, self.b):
            self.select(key)
            self.window.submit('assign')
            self.assertEqual(key, self.handler.pending['target'])
            self.handler.Execute(self.app)
        self.assertEqual(4, len(self.window.store.state['relationships']))
        self.select(self.c)
        rid = self.window.store.state['relationships'][0]['id']
        self.perform('reassign', [rid], self.window.target)
        self.assertEqual(self.c, self.window.store.state['relationships'][0]['activity_key'])
        expected = copy.deepcopy(self.window.store.state)
        self.perform('close'); boundary.forms.pick_file.return_value = self.path; self.perform('open')
        self.assertEqual(expected, self.window.store.state)
        self.select(self.b); self.assertEqual(self.b, self.window.target)

    def test_heading_selection_clears_target_and_blocks_stale_assignment(self):
        self.select(self.a); self.select(kind='wbs')
        self.assertIsNone(self.window.target)
        self.sel.ids = [boundary.Id(1)]; self.perform('capture')
        before = self.bytes()
        self.window.submit('assign')
        with patch('builtins.print'): self.handler.Execute(self.app)
        self.assertEqual(before, self.bytes())

    def test_search_hidden_selection_clears_and_does_not_restore_stale_target(self):
        self.select(self.a)
        self.window.ActivitySearch.Text = 'A300'; self.window.fill_activities()
        self.assertIsNone(self.window.target)
        self.window.ActivitySearch.Text = ''; self.window.fill_activities()
        self.assertIsNone(self.window.target)

    def test_refresh_keeps_exact_selected_key_and_expand_collapse_state(self):
        self.select(self.a); self.window.set_tree_expansion(True)
        group = next(i for i in self.window._tree_items.values() if i.Tag['kind'] == 'wbs')
        ident = group.Tag['id']; group.IsExpanded = False
        self.window.refresh()
        self.assertEqual(self.a, self.window.target)
        self.assertFalse(self.window._tree_items[ident].IsExpanded)
        self.window.ActivitySearch.Text = 'A100'; self.window.fill_activities()
        self.assertTrue(all(i.IsExpanded for i in self.window._tree_items.values()))
        self.window.ActivitySearch.Text = ''; self.window.fill_activities()
        self.assertFalse(self.window._tree_items[ident].IsExpanded)

    def test_navigation_alone_does_not_save_or_change_schema(self):
        before = self.bytes()
        self.select(self.a); self.window.set_tree_expansion(True)
        self.window.set_tree_expansion(False)
        self.window.ActivitySearch.Text = 'Building'; self.window.fill_activities()
        self.assertEqual(before, self.bytes())
        self.assertEqual('suzanoo-mapping-work-1', self.window.store.state['format'])


if __name__ == '__main__': unittest.main()
