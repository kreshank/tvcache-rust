#!/usr/bin/env python3
"""Generate 1 GiB-budget train/val/test traces by scaling the four synthetic workloads.

Each family keeps its original reuse structure but has 4x the tasks and rollouts;
balanced-style families also have 128x larger tool outputs, so that the unique
cache-entry total is about 4 GiB (1 GiB is roughly 25% of the working set).

  python3 scripts/gen_1g_splits.py --out traces/1g [--splits train val] [--families ...]
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRACEGEN = ROOT / "data/synthetic/tracegen.py"
FAMILIES = ("balanced", "expensive_reuse", "memory_pressure", "popularity_shift")
# Test seeds are reserved: generate them only for the final evaluation.
SPLITS = {"train": range(1, 11), "val": range(11, 14), "test": range(14, 19)}
TASK_SCALE, ROLLOUT_SCALE = 4, 4
# memory_pressure already has large outputs; other families need bigger entries.
VALUE_SCALE = {"balanced": 128, "expensive_reuse": 128, "popularity_shift": 128, "memory_pressure": 1}


def family_config(family):
    config = json.loads((ROOT / f"data/synthetic/{family}/manifest.json").read_text())["config"]
    config.pop("seed")
    config["num_tasks"] *= TASK_SCALE
    config["num_rollouts"] *= ROLLOUT_SCALE
    for tool in config["tool_profiles"]:
        tool["value_bytes"] = {k: v * VALUE_SCALE[family] for k, v in tool["value_bytes"].items()}
    return config


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--splits", nargs="+", choices=SPLITS, default=["train", "val"])
    parser.add_argument("--families", nargs="+", choices=FAMILIES, default=list(FAMILIES))
    args = parser.parse_args()
    configs = args.out / "configs"
    configs.mkdir(parents=True, exist_ok=True)
    rows = []
    for family in args.families:
        config_path = configs / f"{family}_1g.json"
        config_path.write_text(json.dumps(family_config(family), indent=2) + "\n")
        for split in args.splits:
            for seed in SPLITS[split]:
                trace = args.out / split / f"{family}_1g_s{seed:02d}"
                if not (trace / "manifest.json").exists():
                    subprocess.run([sys.executable, str(TRACEGEN), "generate", "--config", str(config_path),
                                    "--out", str(trace), "--seed", str(seed)],
                                   check=True, stdout=subprocess.DEVNULL)
                summary = json.loads((trace / "summary.json").read_text())
                rows.append({"split": split, "family": family, "seed": seed, "path": str(trace.relative_to(args.out)),
                             **{k: summary[k] for k in ("events", "unique_nodes", "repeat_fraction",
                                                        "unique_cache_entry_bytes", "unique_external_snapshot_bytes")}})
                print(f"{split:<5} {family:<17} seed {seed:>2}  events {summary['events']:>6}  "
                      f"nodes {summary['unique_nodes']:>5}  entries {summary['unique_cache_entry_bytes'] / 2**30:5.2f} GiB",
                      flush=True)
    index = args.out / "splits.json"
    previous = json.loads(index.read_text()) if index.exists() else []
    keep = [r for r in previous if (r["split"], r["family"], r["seed"]) not in {(x["split"], x["family"], x["seed"]) for x in rows}]
    index.write_text(json.dumps(sorted(keep + rows, key=lambda r: (r["split"], r["family"], r["seed"])), indent=2) + "\n")


if __name__ == "__main__":
    main()
