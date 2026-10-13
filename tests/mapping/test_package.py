# -*- coding: utf-8 -*-
import ast
import copy
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET
from test_mapping import ROOT, schedule, document, element
from suzanoo_mapping import core
from suzanoo_mapping.p6 import MappingError


class PackageContractTests(unittest.TestCase):
    def test_xaml_parses_and_events_have_handlers(self):
        folder = ROOT / 'MappingAuthoring.extension' / 'lib' / 'suzanoo_mapping'
        root = ET.parse(str(folder / 'window.xaml')).getroot()
        tree = ast.parse((folder / 'ui.py').read_text(encoding='utf-8'))
        methods = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        for node in root.iter():
            for key in ('Click', 'TextChanged', 'SelectionChanged', 'SelectedItemChanged', 'Checked', 'Unchecked'):
                if key in node.attrib:
                    self.assertIn(node.attrib[key], methods)

    def test_production_is_free_of_model_write_calls_and_core_has_no_revit_import(self):
        root = ROOT / 'MappingAuthoring.extension'
        for path in root.rglob('*.py'):
            tree = ast.parse(path.read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    self.assertNotIn(node.func.attr, ('Transaction', 'SubTransaction', 'TransactionGroup', 'SetEntity', 'Delete', 'Set'))
            if path.name in ('core.py', 'p6.py', 'storage.py'):
                imports = [n.module or '' for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
                self.assertFalse(any('Revit' in n or 'pyrevit' in n for n in imports))

    def test_500_elements_two_activities_and_export(self):
        s = core.new_work(document(), schedule(), 'tester')
        elements = [element('e-%d' % i) for i in range(500)]
        for activity in s['schedule']['activities'][:2]:
            s, ids = core.assign(s, elements, activity['key'])
            self.assertEqual(500, len(ids))
        core.validate(s)
        resolution = {e['unique_id']: {'status': 'resolved', 'element': e} for e in elements}
        out = core.exchange(s, document(), resolution)
        self.assertEqual(1000, len(out['relationships'])); self.assertEqual(500, len(out['elements']))

    def test_exchange_rejects_false_readiness_and_mismatched_model_evidence(self):
        s = core.new_work(document(), schedule(), 'tester')
        s, unused = core.assign(s, [element('e1')], s['schedule']['activities'][0]['key'])
        out = core.exchange(s, document(), {'e1': {'status': 'resolved', 'element': element('e1')}})
        corrupt = copy.deepcopy(out); corrupt['validation']['time_ready'] = False
        with self.assertRaises(MappingError): core.validate_exchange(corrupt)
        corrupt = copy.deepcopy(out); corrupt['validation']['document']['title'] = 'other'
        with self.assertRaises(MappingError): core.validate_exchange(corrupt)


if __name__ == '__main__': unittest.main()
