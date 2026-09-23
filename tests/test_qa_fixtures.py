"""Preflight checks for QA materials, NOT tests of the absent backend.

No app imports, HTTP requests, AI calls, or simulator implementation.
Run: python3 -m unittest discover -s tests -p 'test_qa_fixtures.py' -v
"""
from decimal import Decimal
from pathlib import Path
import json
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / 'examples'
IDS = ['esil', 'almaty', 'saryarka', 'baikonur', 'nura']
KEYS = ['T1', 'T2', 'E1', 'E2', 'S1', 'S2', 'B1', 'B2', 'C1', 'C2']


def load(name):
    return json.loads((EXAMPLES / name).read_text(encoding='utf-8'))


def dec(value):
    return Decimal(str(value))


class QAFixturePreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = load('qa-cases.json')
        cls.config = load('expected_config.json')
        cls.golden = load('expected_results.json')
        cls.contract_examples = [json.loads(block) for block in re.findall(
            r'```json\n(.*?)\n```',
            (ROOT / 'docs/api-contract.md').read_text(encoding='utf-8'), re.S)]

    def test_manifest_accounts_for_every_request_file(self):
        cases = self.manifest['cases']
        self.assertEqual(len(cases), 30)
        self.assertEqual(len({case['id'] for case in cases}), 30)
        self.assertEqual(len({case['request_file'] for case in cases}), 30)
        self.assertEqual(sum(c['expected']['http_status'] == 200 for c in cases), 7)
        self.assertEqual(sum(c['expected']['http_status'] == 422 for c in cases), 23)
        files = {p.name for p in EXAMPLES.iterdir() if p.is_file()}
        self.assertEqual(files, {c['request_file'] for c in cases} | {
            'qa-cases.json', 'expected_config.json', 'expected_results.json'})
        for case in cases:
            with self.subTest(case=case['id']):
                path = (EXAMPLES / case['request_file']).resolve()
                self.assertEqual(path.parent, EXAMPLES.resolve())
                self.assertTrue(path.is_file())
                self.assertEqual(case['content_type'], 'application/json')
                if case['expected']['http_status'] == 422:
                    self.assertIn('error_code', case['expected'])
                    self.assertNotIn('final_score', case['expected'])
        self.assertEqual(self.manifest['execution_status'],
                         'prepared_not_executed_against_backend')

    def test_request_syntax_and_intentionally_malformed_json(self):
        for case in self.manifest['cases']:
            with self.subTest(case=case['id']):
                raw = (EXAMPLES / case['request_file']).read_text(encoding='utf-8')
                if case['id'] == 'invalid_json':
                    with self.assertRaises(json.JSONDecodeError):
                        json.loads(raw)
                else:
                    json.loads(raw)

    def test_contract_configuration_matches_reviewed_snapshot(self):
        documented = next(x for x in self.contract_examples if 'measures' in x)
        self.assertEqual(documented, self.config)
        for field, expected in [('contract_version', '2.0'),
                                ('dataset_version', 'city-v1'),
                                ('rules_version', 'five-directions-v1')]:
            self.assertEqual(self.config[field], expected)
            self.assertEqual(self.manifest[field], expected)
        self.assertEqual([d['id'] for d in self.config['districts']], IDS)
        self.assertEqual(self.config['indicators'], KEYS)
        self.assertEqual([m['id'] for m in self.config['measures']],
                         [f'M{i}' for i in range(1, 15)])
        self.assertEqual(sum(dec(x) for x in self.config['weights'].values()), 1)
        self.assertEqual(sum(dec(d['population_share'])
                             for d in self.config['districts']), 1)

    def test_snapshot_matches_specification_tables(self):
        rows = [[cell.strip() for cell in line.strip('|').split('|')]
                for line in (ROOT / 'docs/spec.md').read_text(encoding='utf-8').splitlines()
                if line.startswith('|')]
        district_rows = {r[0]: r for r in rows if r[0] in IDS}
        measure_rows = {r[0]: r for r in rows if re.fullmatch(r'M\d+', r[0])}
        self.assertEqual(len(district_rows), 5)
        self.assertEqual(len(measure_rows), 14)
        for district in self.config['districts']:
            r = district_rows[district['id']]
            self.assertEqual(r[1], district['name'])
            self.assertEqual(dec(r[2]), dec(district['population_share']))
            self.assertEqual(dict(zip(KEYS, map(Decimal, r[3:13]))),
                             {k: dec(v) for k, v in district['indicators'].items()})
        for measure in self.config['measures']:
            r = measure_rows[measure['id']]
            self.assertEqual(r[1:4], [measure['category'], measure['name'], measure['scope']])
            self.assertEqual([int(r[4]), int(r[5])], [measure['cost'], measure['lag_quarters']])
            effects = {k: int(v) for k, v in re.findall(r'([TESBC][12])\s+([+-]\d+)', r[6])}
            self.assertEqual(effects, measure['effects'])

    def test_valid_request_fixtures_have_reviewed_costs_and_categories(self):
        catalog = {m['id']: m for m in self.config['measures']}
        for case in self.manifest['cases']:
            if case['expected']['http_status'] != 200:
                continue
            with self.subTest(case=case['id']):
                payload = load(case['request_file'])
                self.assertEqual(set(payload), {'selections'})
                selections = payload['selections']
                self.assertEqual(len(selections), 5)
                self.assertEqual(len({s['measure_id'] for s in selections}), 5)
                self.assertEqual(sorted(catalog[s['measure_id']]['category'] for s in selections),
                                 sorted(self.config['required_categories']))
                cost = sum(catalog[s['measure_id']]['cost'] for s in selections)
                self.assertEqual(cost, case['expected']['total_cost'])
                self.assertLessEqual(cost, 100)
                for selection in selections:
                    self.assertLessEqual(set(selection), {'measure_id', 'district_id'})
                    if catalog[selection['measure_id']]['scope'] == 'district':
                        self.assertIn(selection['district_id'], IDS)
                    else:
                        self.assertIsNone(selection.get('district_id'))

    def test_invalid_budget_and_conflict_examples_isolate_the_intended_problem(self):
        catalog = {m['id']: m for m in self.config['measures']}
        for file, expected_cost in [('invalid_budget_107.json', 107),
                                     ('invalid_park_school_conflict.json', 83),
                                     ('invalid_fuel_network_conflict.json', 91)]:
            selections = load(file)['selections']
            self.assertEqual(sum(catalog[s['measure_id']]['cost'] for s in selections),
                             expected_cost)
            self.assertEqual(sorted(catalog[s['measure_id']]['category'] for s in selections),
                             sorted(self.config['required_categories']))
        park = {s['measure_id']: s['district_id'] for s in load('invalid_park_school_conflict.json')['selections']}
        fuel = {s['measure_id']: s['district_id'] for s in load('invalid_fuel_network_conflict.json')['selections']}
        self.assertEqual((park['M4'], park['M7']), ('nura', 'nura'))
        self.assertEqual((fuel['M5'], fuel['M13']), ('nura', 'nura'))
        cases = {c['id']: c for c in self.manifest['cases']}
        self.assertEqual(cases['invalid_m1_m3_category_first']['expected']['error_code'],
                         'CATEGORY_COVERAGE')

    def test_golden_tables_are_arithmetically_consistent(self):
        """Audit stored answers; do not simulate initiatives or call app code."""
        shares = {d['id']: dec(d['population_share']) for d in self.config['districts']}
        weights = {k: dec(v) for k, v in self.config['weights'].items()}
        for name in ['baseline', 'scenario_a', 'scenario_b']:
            with self.subTest(scenario=name):
                expected = self.golden[name]
                self.assertEqual(list(expected['indicators']), IDS)
                for id in IDS:
                    row = expected['indicators'][id]
                    self.assertEqual(list(row), KEYS)
                    self.assertEqual(sum(dec(row[k]) * weights[k] for k in KEYS),
                                     dec(expected['district_scores'][id]))
                average = sum(shares[id] * dec(expected['district_scores'][id]) for id in IDS)
                self.assertEqual(average, dec(expected['city_average']))
                minimum = min(map(dec, expected['district_scores'].values()))
                self.assertEqual(minimum, dec(expected['weakest_district_score']))
                critical = [{'district_id': id, 'indicator': k, 'value': expected['indicators'][id][k]}
                            for id in IDS for k in KEYS if dec(expected['indicators'][id][k]) < 40]
                self.assertEqual(critical, expected['critical'])
                self.assertEqual(Decimal('.7') * average + Decimal('.3') * minimum - len(critical),
                                 dec(expected['score']))

    def test_demo_changes_only_school_target_and_preserves_fixed_answers(self):
        a, b = load('scenario_a.json'), load('scenario_b.json')
        self.assertEqual([i for i, (x, y) in enumerate(zip(a['selections'], b['selections'])) if x != y], [2])
        self.assertEqual(a['selections'][2], {'measure_id': 'M7', 'district_id': 'esil'})
        self.assertEqual(b['selections'][2], {'measure_id': 'M7', 'district_id': 'nura'})
        self.assertEqual(dec(self.golden['baseline']['score']), Decimal('52.55768'))
        self.assertEqual(dec(self.golden['scenario_a']['score']), Decimal('53.8250475'))
        self.assertEqual(dec(self.golden['scenario_b']['score']), Decimal('55.0703475'))
        self.assertEqual(dec(self.golden['scenario_b']['score']) - dec(self.golden['scenario_a']['score']),
                         Decimal('1.2453'))
        for key in ['scenario_a', 'scenario_b']:
            self.assertEqual(dec(self.golden[key]['score_delta']),
                             dec(self.golden[key]['score']) - dec(self.golden['baseline']['score']))
        self.assertEqual(load('scenario_b_reversed.json')['selections'], list(reversed(b['selections'])))
        omitted = load('city_district_omitted.json')
        omitted['selections'][4]['district_id'] = None
        self.assertEqual(omitted, b)

    def test_documented_result_b_matches_independent_golden_tables(self):
        result = next(x for x in self.contract_examples if 'applied_effects' in x)
        expected = self.golden['scenario_b']
        self.assertEqual(result['selections'], load('scenario_b.json')['selections'])
        self.assertEqual(result['final_score'], expected['score'])
        self.assertEqual(result['total_cost'], 83)
        self.assertEqual(result['critical_after'], expected['critical'])
        for district in result['districts']:
            id = district['id']
            self.assertEqual(district['before'], self.golden['baseline']['indicators'][id])
            self.assertEqual(district['after'], expected['indicators'][id])
            self.assertEqual(district['score_after'], expected['district_scores'][id])
        self.assertEqual(result['applied_synergies'],
                         [{'measure_ids': ['M10', 'M12'], 'district_id': 'esil', 'effects': {'B1': 2}}])

    def test_documented_ai_evidence_paths_resolve_without_ai_call(self):
        result = next(x for x in self.contract_examples if 'applied_effects' in x)
        response = next(x for x in self.contract_examples if x.get('status') == 'ok' and 'analysis' in x)
        analysis = response['analysis']
        for statement in [analysis['summary'], *analysis['strengths'], *analysis['risks'], analysis['tradeoff']]:
            for pointer in statement['evidence_paths']:
                value = result
                for token in pointer.split('/')[1:]:
                    token = token.replace('~1', '/').replace('~0', '~')
                    value = value[int(token)] if isinstance(value, list) else value[token]


if __name__ == '__main__':
    unittest.main()
