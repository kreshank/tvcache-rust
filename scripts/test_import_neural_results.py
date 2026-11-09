"""Check CSV import semantics, matched cells, source preservation and focused views."""
import csv
import json
from pathlib import Path
import tempfile
import unittest

from import_neural_results import import_results, validate, ORIGINAL


def fixture():
    rows=[]
    for family in ('a','b'):
        for seed,fraction in ((11,.2),(12,.5),(13,.8)):
            for budget in (512,1536):
                for policy in (ORIGINAL,'lfu-persistent','linear','lin-belady','small-belady','big-belady'):
                    baseline=1000*(seed-10)
                    rows.append(dict(engine='rust',snapshots='False',workload=f'{family}-{seed}',
                        family=family,seed=str(seed),policy=policy,budget_mib=str(budget),
                        requests='100',hits='50',hit_rate='.5',evictions='10',
                        baseline_tool_time_ms=str(baseline),net_time_saved_ms=str(fraction*baseline),
                        modeled_request_ms=str((1-fraction)*baseline),baseline_tool_cost_usd='10',
                        net_cost_saved_usd=str(10*fraction),rust_policy_ns_per_request='1000',
                        speedup=str(1/(1-fraction)),kind='learned' if '-' in policy and policy!=ORIGINAL and policy!='lfu-persistent' else 'baseline',
                        saved_fraction_of_achievable='.99'))
    return rows


class ImportTests(unittest.TestCase):
    def test_import_preserves_rows_and_averages_seed_ratios(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'incoming.csv';rows=fixture()
            with source.open('w',newline='') as stream:
                writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
            output=root/'imported'
            metadata=import_results(source,output)
            self.assertEqual(metadata['audit']['runs'],72)
            self.assertEqual((output/'source/summary.csv').read_bytes(),source.read_bytes())
            with (output/'summary.csv').open() as stream:
                self.assertEqual(list(csv.DictReader(stream)),rows)
            with (output/'family-summary.csv').open() as stream:
                for row in csv.DictReader(stream):
                    self.assertAlmostEqual(float(row['mean_time_saved_fraction']),.5)
                    self.assertAlmostEqual(float(row['min_time_saved_fraction']),.2)
                    self.assertAlmostEqual(float(row['max_time_saved_fraction']),.8)
                    self.assertEqual(int(row['seeds']),3)
            self.assertEqual(set(metadata['views']),{'baselines','linear','small','big'})
            for view in ('linear','small','big'):
                with (output/'views'/view/'summary.csv').open() as stream:
                    policies={r['policy'] for r in csv.DictReader(stream)}
                self.assertIn(ORIGINAL,policies)
                self.assertIn('lfu-persistent',policies)
                self.assertIn(f'{"lin" if view=="linear" else view}-belady',policies)
            self.assertEqual(json.loads((output/'run.json').read_text())['source_sha256'],metadata['source_sha256'])

    def test_incomplete_duplicate_and_inconsistent_rows_are_rejected(self):
        rows=fixture()
        for invalid in (rows[:-1],rows+[rows[0]], [{**rows[0],'hit_rate':'50'},*rows[1:]],
                        [{**rows[0],'baseline_tool_time_ms':'9999'},*rows[1:]]):
            with self.assertRaises(ValueError):
                validate(invalid)

    def test_different_import_cannot_overwrite_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'incoming.csv';rows=fixture()
            def save():
                with source.open('w',newline='') as stream:
                    writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
            save();output=root/'imported';import_results(source,output)
            rows[0]['evictions']='11';save()
            with self.assertRaisesRegex(ValueError,'different import'):
                import_results(source,output)


if __name__=='__main__':
    unittest.main()
