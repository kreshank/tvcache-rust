#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["tqdm>=4.66,<5"]
# ///
"""Measure generation and validation near requested on-disk JSONL sizes."""
import argparse
import csv
import importlib.util
import json
import math
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("tracegen", ROOT / "data/synthetic/tracegen.py")
tracegen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tracegen)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--traces", required=True, type=Path, help="new directory for generated traces")
    parser.add_argument("--output", required=True, type=Path, help="timing report directory")
    parser.add_argument("--sizes-mib", nargs="+", type=int, default=[64, 128, 256, 512, 1024, 2048])
    args = parser.parse_args()
    if not args.sizes_mib or any(n <= 0 for n in args.sizes_mib) or len(set(args.sizes_mib)) != len(args.sizes_mib):
        parser.error("sizes must be unique positive integer MiB values")
    config = tracegen.load_config(args.config)
    if args.traces.exists() and any(args.traces.iterdir()):
        parser.error("trace directory must be new or empty")
    args.output.mkdir(parents=True, exist_ok=True)
    tracegen.dump_json(args.output / "run.json", {"config": config, "sizes_mib": sorted(args.sizes_mib),
        "size_definition": "nodes.jsonl + events.jsonl, binary MiB; targets approximate",
        "method": "sequential single runs; wall time includes writes/hashes and validation, without fsync",
        "generator": str(spec.origin)})
    rows = []

    def measure(name, rollouts, target):
        c = {**config, "num_rollouts": rollouts}
        directory = args.traces / name
        started = perf_counter()
        summary = tracegen.generate(c, directory)
        generated = perf_counter()
        print(f"{name}: validating...", flush=True)
        tracegen.validate(directory)
        finished = perf_counter()
        node_bytes = (directory / "nodes.jsonl").stat().st_size
        event_bytes = (directory / "events.jsonl").stat().st_size
        row = {"target_mib": target, "actual_jsonl_mib": (node_bytes+event_bytes)/1024**2,
            "nodes_bytes": node_bytes, "events_bytes": event_bytes, "rollouts": rollouts,
            "accesses": summary["events"], "unique_nodes": summary["unique_nodes"],
            "logical_cache_mib": summary["unique_cache_entry_bytes"]/1024**2,
            "external_snapshots_gib": summary["unique_external_snapshot_bytes"]/1024**3,
            "generation_seconds": generated-started, "validation_seconds": finished-generated,
            "total_seconds": finished-started, "trace_directory": str(directory.resolve())}
        rows.append(row)
        with (args.output / "summary.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(row))
            writer.writeheader()
            writer.writerows(rows)
        print(f"{name}: {row['actual_jsonl_mib']:.1f} MiB, {summary['events']:,} accesses; "
              f"generate {generated-started:.2f}s + validate {finished-generated:.2f}s "
              f"= {finished-started:.2f}s", flush=True)
        return row

    previous = measure("calibration", 5000, 0)
    for size in sorted(args.sizes_mib):
        # Event bytes grow roughly linearly; the finite node catalog grows more slowly.
        estimated_nodes = min(size*1024**2*.25, previous["nodes_bytes"]*1.15)
        rollouts = max(1, math.ceil((size*1024**2-estimated_nodes) /
                                   (previous["events_bytes"]/previous["rollouts"])))
        previous = measure(f"{size}mib", rollouts, size)
    tracegen.dump_json(args.output / "completion.json", {"complete": True, "measurements": len(rows),
        "target_sizes_mib": sorted(args.sizes_mib)})


if __name__ == "__main__":
    main()
