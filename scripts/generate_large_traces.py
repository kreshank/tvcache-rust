#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["tqdm>=4.66,<5"]
# ///
"""Generate a reproducible multi-GiB logical-cache stress suite, not GiB of JSONL."""
import argparse
from collections import Counter
import copy
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("tracegen", ROOT / "data/synthetic/tracegen.py")
tracegen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tracegen)
FAMILIES = {"balanced": (256, 20000), "expensive_reuse": (512, 40000),
            "memory_pressure": (128, 20000), "popularity_shift": (256, 20000)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", nargs="+", type=int, default=[42, 43, 44])
    parser.add_argument("--families", nargs="+", choices=list(FAMILIES), default=list(FAMILIES))
    parser.add_argument("--traces", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path, help="small reports and exact input configurations")
    args = parser.parse_args()
    if len(set(args.seeds)) != len(args.seeds) or len(set(args.families)) != len(args.families):
        parser.error("seeds and families must be unique")
    # Preflight all destinations; never overwrite an existing experiment.
    for seed in args.seeds:
        for family in args.families:
            destination = args.traces / family / f"{family}-seed-{seed}"
            if destination.exists() and any(destination.iterdir()):
                parser.error(f"trace destination must be new or empty: {destination}")
    args.output.mkdir(parents=True, exist_ok=True)
    rows = []
    suite_started = perf_counter()
    for seed in args.seeds:
        for family in args.families:
            base = ROOT / "data/synthetic" / family / "manifest.json"
            config = copy.deepcopy(json.loads(base.read_text())["config"])
            tasks, rollouts = FAMILIES[family]
            config.update(seed=seed, num_tasks=tasks, num_rollouts=rollouts, templates_per_task=24)
            for profile in config["tool_profiles"]:
                profile["value_bytes"] = {"min": 65536, "max": 4194304}
            # Preserve three distinct hot cohorts when scaling the shift scenario.
            if family == "popularity_shift":
                for i, phase in enumerate(config["phases"]):
                    phase["hot_task_offset"] = i * tasks // len(config["phases"])
            config_path = args.output / "configs" / family / f"seed-{seed}.json"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            tracegen.dump_json(config_path, config)
            directory = args.traces / family / f"{family}-seed-{seed}"
            print(f"Generating {family}, seed {seed}: {rollouts:,} rollouts...", flush=True)
            started = perf_counter()
            summary = tracegen.generate(config, directory)
            generated = perf_counter()
            print(f"{family} seed {seed}: validating...", flush=True)
            tracegen.validate(directory)
            validated = perf_counter()
            # This is a trace diagnostic, not a policy result or a rolling working-set estimate.
            nodes = {n["node_id"]: n for n in tracegen.read_jsonl(directory / "nodes.jsonl")}
            counts, phases = Counter(), {}
            for event in tracegen.read_jsonl(directory / "events.jsonl"):
                counts[event["node_id"]] += 1
                phases.setdefault(event["phase"], Counter())[event["node_id"]] += 1
            repeated_bytes = sum(nodes[n]["cache_entry_bytes"] for n, count in counts.items() if count > 1)
            phase_repeated = {str(phase): sum(nodes[n]["cache_entry_bytes"] for n, count in tally.items() if count > 1)
                              for phase, tally in phases.items()}
            row = {"family": family, "seed": seed, "rollouts": rollouts, "accesses": summary["events"],
                "unique_nodes": summary["unique_nodes"], "repeat_fraction": summary["repeat_fraction"],
                "cache_gib": summary["unique_cache_entry_bytes"]/1024**3,
                "reused_entry_gib": repeated_bytes/1024**3,
                "minimum_phase_reused_gib": min(phase_repeated.values())/1024**3,
                "maximum_entry_mib": max(n["cache_entry_bytes"] for n in nodes.values())/1024**2,
                "external_snapshot_gib": summary["unique_external_snapshot_bytes"]/1024**3,
                "jsonl_mib": sum((directory/n).stat().st_size for n in ("nodes.jsonl", "events.jsonl"))/1024**2,
                "generation_seconds": generated-started, "validation_seconds": validated-generated,
                "total_seconds": perf_counter()-started, "trace_directory": str(directory.resolve())}
            tracegen.dump_json(directory / "scale-report.json", {**row, "phase_reused_bytes": phase_repeated,
                "diagnostic_note": "Repeated-entry bytes are counted once per node; not simultaneous residency or a rolling working set."})
            rows.append(row)
            with (args.output / "summary.csv").open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(row))
                writer.writeheader()
                writer.writerows(rows)
            print(f"{family} seed {seed}: {row['cache_gib']:.2f} GiB cache entries, "
                  f"{row['reused_entry_gib']:.2f} GiB reused entries, {row['jsonl_mib']:.1f} MiB JSONL, "
                  f"{row['total_seconds']:.1f}s", flush=True)
    elapsed = perf_counter()-suite_started
    tracegen.dump_json(args.output / "completion.json", {"complete": True, "traces": len(rows),
        "elapsed_seconds": elapsed,
        "all_catalogs_at_least_8gib": all(r["cache_gib"] >= 8 for r in rows),
        "all_reused_entry_sets_above_4gib": all(r["reused_entry_gib"] > 4 for r in rows),
        "generator_sha256": hashlib.sha256(Path(spec.origin).read_bytes()).hexdigest(),
        "synthetic": True, "payload_range_bytes": [65536,4194304]})
    print(f"Completed {len(rows)} traces in {elapsed:.1f}s. Reports: {args.output}", flush=True)


if __name__ == "__main__":
    main()
