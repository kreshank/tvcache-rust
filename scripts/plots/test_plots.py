"""Small input-contract and end-to-end checks for plotting only."""
import argparse
import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import matplotlib.pyplot as plt

from common import (ORIGINAL, Run, num, read_csv, select_budget, eviction_cells,
                    capacity_axis, zero_capacity_control, aggregate_seeds, seed_errors)
from plots_seed_summary import render as render_seed_summary

SCRIPTS = Path(__file__).resolve().parent


def fixture(directory, workloads=("example",)):
    directory.mkdir(parents=True)
    rows = []
    for workload in workloads:
        for policy, elapsed in ((ORIGINAL, 200), ("linear", 100), ("future-policy", 150)):
            rows.append(dict(engine="rust", snapshots="False", workload=workload,
                policy=policy, budget_mib=1, hit_rate=.75, baseline_tool_time_ms=1000,
                baseline_tool_cost_usd=0, net_time_saved_ms=1000-elapsed,
                modeled_request_ms=elapsed, gross_hit_time_ms=900, net_cost_saved_usd=0,
                rust_policy_ns_per_request=1000))
    write_rows(directory, rows)
    return rows


def write_rows(directory, rows):
    with (directory / "summary.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


class PlotTests(unittest.TestCase):
    def test_aggregation_keeps_seed_ratios_and_rejects_unmatched_seeds(self):
        rows = []
        for seed, baseline, remaining in ((42, 100, 50), (43, 200, 100), (44, 400, 100)):
            for policy in (ORIGINAL, "lru"):
                rows.append(dict(family="example", seed=seed, workload=f"example-{seed}",
                    policy=policy, budget_mib=1024,
                    improvement=0 if policy==ORIGINAL else 1-remaining/baseline))
        grouped = aggregate_seeds(rows, ["improvement"])
        lru = next(r for r in grouped if r['policy']=="lru")
        self.assertEqual(lru['workload'], 'example')
        self.assertEqual(lru['seeds'], 3)
        self.assertAlmostEqual(lru['improvement'], (0.5+0.5+0.75)/3)
        self.assertNotAlmostEqual(lru['improvement'], 1-250/700)
        lower, upper = seed_errors([lru], 'improvement')
        self.assertAlmostEqual(lru['improvement']-lower[0], .5)
        self.assertAlmostEqual(lru['improvement']+upper[0], .75)
        for invalid in (rows[:-1], rows+[rows[-1]]):
            with self.assertRaisesRegex(ValueError, "same completed seeds"):
                aggregate_seeds(invalid, ["improvement"])

    def test_seed_summary_normalizes_each_trace_and_reports_observed_range(self):
        source = self.root / "seed-suite"
        source.mkdir()
        rows = []
        for family in ("a", "b"):
            for seed, fraction in ((42, .5), (43, .7)):
                for policy in (ORIGINAL, "lru"):
                    for budget in (1024, 2048):
                        rows.append(dict(engine="rust", snapshots="False", family=family, seed=seed,
                            workload=f"{family}-{seed}", policy=policy, budget_mib=budget,
                            hit_rate=fraction, baseline_tool_time_ms=1000*(seed-41),
                            net_time_saved_ms=fraction*1000*(seed-41), requests=100, evictions=10))
        write_rows(source, rows)
        paths = render_seed_summary(self.args(source))
        self.assertEqual(len(paths), 3)
        data = read_csv(paths[1].with_suffix('.csv'), ["mean", "minimum", "maximum", "seeds"])
        for row in data:
            self.assertAlmostEqual(float(row['mean']), .6)
            self.assertAlmostEqual(float(row['minimum']), .5)
            self.assertAlmostEqual(float(row['maximum']), .7)
            self.assertEqual(int(row['seeds']), 2)
        write_rows(source, rows[:-1])
        with self.assertRaisesRegex(ValueError, "same completed seeds"):
            render_seed_summary(self.args(source))

    def test_capacity_axis_spaces_doublings_equally_and_keeps_zero_off_axis(self):
        fig, ax = plt.subplots()
        self.addCleanup(plt.close, fig)
        capacity_axis(ax)
        ax.set_xlim(1, 16)
        fig.canvas.draw()
        positions = [ax.transData.transform((v, 0))[0] for v in (1, 2, 4, 8, 16)]
        gaps = [b-a for a, b in zip(positions, positions[1:])]
        for gap in gaps:
            self.assertAlmostEqual(gap, gaps[0])
        zero_capacity_control(ax, [0, 0])
        self.assertEqual(ax.get_xscale(), "log")
        self.assertEqual(len(ax.lines), 0)
        self.assertIn("0 MiB control", ax.texts[0].get_text())

    def test_equal_hits_do_not_imply_absence_of_eviction(self):
        rows = [dict(workload="x", policy=p, budget_mib=1, evictions=e, hit_rate=.5)
                for p, e in (("lru", 2), ("lfu", 3))]
        cell = eviction_cells(rows)[0]
        self.assertEqual(cell["hit_rate_spread"], 0)
        self.assertEqual(cell["maximum_evictions"], 3)
        for row in rows:
            row["evictions"] = 0
        self.assertEqual(eviction_cells(rows)[0]["maximum_evictions"], 0)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def args(self, source, engine="rust", snapshots="off"):
        return argparse.Namespace(input=source, output=self.root / "plots", engine=engine,
                                  snapshots=snapshots, budget_position="smallest")

    def test_capacity_selection_uses_tested_positive_budgets(self):
        rows = [{"budget_mib": v} for v in (0, 64, 256, 1024, 2048, 4096)]
        for position, expected in (("smallest", 64), ("middle", 1024), ("largest", 4096)):
            budget, chosen = select_budget(rows, position)
            self.assertEqual(budget, expected)
            self.assertEqual(len(chosen), 1)

    def test_duplicates_are_rejected(self):
        source = self.root / "input"
        rows = fixture(source)
        write_rows(source, rows + [rows[0]])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            Run(self.args(source))

    def test_bad_columns_and_nonfinite_values(self):
        path = self.root / "bad.csv"
        path.write_text("other\n1\n")
        with self.assertRaisesRegex(ValueError, "missing columns"):
            read_csv(path, ["hit_rate"])
        with self.assertRaisesRegex(ValueError, "nonfinite"):
            num({"value": "nan"}, "value")

    def test_engines_and_snapshot_modes_stay_separate(self):
        source = self.root / "input"
        rows = fixture(source)
        for snapshots in ("True", "False"):
            rows.append({**rows[0], "engine": "python-reference", "snapshots": snapshots})
        write_rows(source, rows)
        rust = Run(self.args(source))
        reference = Run(self.args(source, "python-reference", "on"))
        self.assertEqual(len(rust.rows), 3)
        self.assertEqual(len(reference.rows), 1)
        self.assertNotEqual(rust.output, reference.output)

    def test_batch_directories_arithmetic_and_zero_costs(self):
        one, three = self.root / "run-one", self.root / "run-three"
        fixture(one)
        fixture(three, ("one", "two", "three"))
        for source in (one, three):
            rows = read_csv(source / "summary.csv", ["policy"])
            controls = [{**r, "budget_mib": 0, "hit_rate": 0, "net_time_saved_ms": 0,
                         "modeled_request_ms": 1000, "gross_hit_time_ms": 0} for r in rows]
            write_rows(source, rows + controls)
        result = subprocess.run([sys.executable, str(SCRIPTS / "plots_all.py"),
            "--inputs", str(one), str(three), "--output", str(self.root / "plots"), "--skip", "paper"],
            cwd=self.root, capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("skip cost_saved: no defined normalized values", result.stdout)
        for source in (one, three):
            gallery = self.root / "plots" / source.name
            self.assertTrue((gallery / "index.html").exists())
            self.assertEqual(len(list(gallery.rglob("*.png"))), 5)
            csv_path = gallery / "rust-snapshots-off/tradeoffs/vs_original.csv"
            rows = read_csv(csv_path, ["time_reduction_vs_original"])
            for r in rows:
                expected = (0 if num(r, "budget_mib") == 0 else
                            {ORIGINAL: 0, "linear": .5, "future-policy": .25}[r["policy"]])
                self.assertAlmostEqual(num(r, "time_reduction_vs_original"), expected)
                self.assertEqual(r["display_role"], "off-axis zero control" if num(r, "budget_mib") == 0 else "curve")
            metadata = json.loads(csv_path.with_suffix(".json").read_text())
            self.assertIn(str(source / "summary.csv"), metadata["sources_sha256"])
            capacity_rows = read_csv(gallery / "rust-snapshots-off/capacity/hit_rate.csv", ["display_role"])
            self.assertTrue(any(r["display_role"] == "off-axis zero control" for r in capacity_rows))
        self.assertTrue((self.root / "plots/index.html").exists())


if __name__ == "__main__":
    unittest.main()
