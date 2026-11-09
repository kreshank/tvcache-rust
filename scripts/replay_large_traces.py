#!/usr/bin/env python3
"""Replay all six Rust configurations on a generated suite, with independent scoring.

Results are checkpointed per policy and may be resumed with identical inputs.
Python reference policies/snapshots are not part of this result-only comparison.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from benchmark_compatibility import check_rust_bytes
from tvcache_eval.trace import load_trace, read_jsonl
from tvcache_eval.evaluator import evaluate

POLICIES = ["original-ttl-and-watermark", "fifo", "linear", "lru", "lfu", "lfu-persistent"]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f".{os.getpid()}.tmp")
    temp.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temp.replace(path)


def run_budget(item, mib, output):
    directory = Path(item["trace_directory"])
    trace = load_trace(directory)
    trace_out = Path(output) / trace.name
    dump(trace_out / "validation.json", {"workload": trace.name, "family": item["family"],
                                       "seed": item["seed"], **trace.validation})
    for label in POLICIES:
        case = trace_out / f"{mib}mib" / label
        receipt = case / "case.json"
        if receipt.exists():
            continue
        mode = "original" if label == "original-ttl-and-watermark" else label
        weights = []
        if label == "lfu-persistent":
            mode, weights = "linear", ["configs/lfu-persistent.json"]
        started = perf_counter()
        command = [str(ROOT / "target/release/replay"), str(directory), mode, str(mib),
                   *weights, f"--decisions={case}"]
        native = json.loads(subprocess.check_output(command, cwd=ROOT, text=True))[0]
        replay_done = perf_counter()
        dump(case / "replay.json", native)
        decisions = list(read_jsonl(case / f"{native['policy']}.decisions.jsonl"))
        check_rust_bytes(trace, decisions, native)
        scored = evaluate(trace, memory_budget_bytes=mib*1024**2, decisions=decisions)
        metrics = scored["metrics"]
        assert metrics["hits"] == native["hits"]
        assert math.isclose(metrics["gross_hit_time_ms"], native["gross_tool_ms_saved"], rel_tol=1e-9, abs_tol=1e-6)
        assert math.isclose(metrics["gross_hit_cost_usd"], native["gross_tool_cost_usd_saved"], rel_tol=1e-9, abs_tol=1e-6)
        dump(case / "scored.json", scored)
        row = {"engine": "rust", "workload": trace.name, "family": item["family"],
            "seed": int(item["seed"]), "policy": label, "budget_mib": mib, "snapshots": False,
            "catalog_bytes": trace.validation["unique_cache_entry_bytes"],
            "rust_peak_bytes": native["peak_bytes_after_enforcement"], "rust_final_bytes": native["final_bytes"],
            "rust_peak_bytes_before_enforcement": native["peak_bytes_before_enforcement"],
            "rust_bypassed_missing_parent": native["bypassed_missing_parent"],
            "rust_policy_ns_per_request": native["policy_ns"] / native["requests"],
            "replay_wall_seconds": replay_done-started,
            "scoring_wall_seconds": perf_counter()-replay_done, **metrics}
        dump(receipt, row)
        print(f"{trace.name} {mib} MiB {label}: hit {metrics['hit_rate']:.4f}, "
              f"evictions {metrics['evictions']}, time saved {metrics['net_time_saved_ms']/metrics['baseline_tool_time_ms']:.4f}, "
              f"wall {perf_counter()-started:.1f}s", flush=True)
        del decisions, scored
    return trace.name, mib


def checkpoint(output):
    rows = [json.loads(p.read_text()) for p in output.glob("*/*mib/*/case.json")]
    rows.sort(key=lambda r: (r["family"], r["seed"], r["budget_mib"], r["policy"]))
    if rows:
        temporary = output / "summary.csv.tmp"
        with temporary.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=sorted(set().union(*(r.keys() for r in rows))))
            writer.writeheader()
            writer.writerows(rows)
        temporary.replace(output / "summary.csv")
    validation = [json.loads(p.read_text()) for p in sorted(output.glob("*/validation.json"))]
    dump(output / "validation.json", validation)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, default=ROOT / "results/large-traces-2026-11-08/summary.csv")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--budgets-mib", type=int, nargs="+", default=[1024, 2048, 4096])
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    if args.workers < 1 or any(b <= 0 or b > 2**32-1 for b in args.budgets_mib):
        parser.error("workers and MiB budgets must be positive; budgets must fit u32")
    if len(set(args.budgets_mib)) != len(args.budgets_mib):
        parser.error("duplicate budgets")
    with args.suite.open(newline="") as stream:
        items = list(csv.DictReader(stream))
    if not items or len({Path(i['trace_directory']).name for i in items}) != len(items):
        parser.error("suite must have uniquely named nonempty trace directories")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    sources = [ROOT / p for p in ("src/replay.rs", "src/policy/history.rs", "src/policy/classic.rs", "src/policy/fifo.rs",
        "src/policy/linear.rs", "configs/lfu-persistent.json", "tvcache_eval/evaluator.py",
        "tvcache_eval/trace.py", "tvcache_eval/costs.py", "target/release/replay", "scripts/replay_large_traces.py")]
    metadata = {"budgets_mib": sorted(args.budgets_mib), "policies": POLICIES,
        "traces": items, "suite_sha256": digest(args.suite), "workers": args.workers,
        "source_sha256": {str(p.relative_to(ROOT)): digest(p) for p in sources},
        "assumptions": "Synthetic result-only replay; zero modeled cache overheads; no admitted snapshots; original tie order nondeterministic."}
    manifest = output / "run.json"
    if manifest.exists() and json.loads(manifest.read_text()) != metadata:
        parser.error("output belongs to different inputs or code; use a new output directory")
    dump(manifest, metadata)
    expected = len(items)*len(args.budgets_mib)*len(POLICIES)
    started = perf_counter()
    print(f"Starting {expected} policy runs with {args.workers} workers", flush=True)
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        # Mix families early so partial results cover each workload pattern.
        futures = {pool.submit(run_budget, item, mib, str(output))
                   for mib in sorted(args.budgets_mib) for item in items}
        while futures:
            done, futures = wait(futures, timeout=30, return_when=FIRST_COMPLETED)
            for future in done:
                future.result()
            rows = checkpoint(output)
            print(f"Checkpoint: {len(rows)}/{expected} independently validated policy runs", flush=True)
    rows = checkpoint(output)
    assert len(rows) == expected
    dump(output / "completion.json", {"complete": True, "runs": len(rows), "trace_count": len(items),
        "elapsed_seconds_this_invocation": perf_counter()-started,
        "all_runs_had_evictions": all(r["evictions"] > 0 for r in rows),
        "checks": ["trace hashes and causal history", "decision residency and full Rust byte budgets",
                   "independent hit and gross savings agreement", "modeled reconstruction and net savings"]})
    print(f"Completed {len(rows)} runs: {output / 'summary.csv'}", flush=True)


if __name__ == "__main__":
    main()
