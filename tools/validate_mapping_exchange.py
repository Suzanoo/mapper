# -*- coding: utf-8 -*-
"""Offline contract validator. Does not resolve identities in Revit or geometry."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'MappingAuthoring.extension' / 'lib'))
from suzanoo_mapping import core, storage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('exchange_json')
    args = parser.parse_args()
    try:
        data, digest = storage.read(args.exchange_json)
        core.validate_exchange(data)
        print(json.dumps({'contract_valid': True, 'sha256': digest,
                          'origin': data['origin'], 'elements': len(data['elements']),
                          'relationships': len(data['relationships']),
                          'time_ready_at_export': data['validation']['time_ready'],
                          'native_resolution_repeated': False}, indent=2))
        return 0
    except Exception as ex:
        print('INVALID: %s' % ex, file=sys.stderr)
        return 1


if __name__ == '__main__': sys.exit(main())
