# Synthetic trace generation

The generator uses `tqdm` for rollout progress and prints generation,
validation, and total elapsed seconds to stderr. Its JSON result remains on
stdout; trace contents and checksums remain deterministic.

```sh
uv run data/synthetic/tracegen.py generate --rollouts 10000 --out data/synthetic/new-run
uv run data/synthetic/tracegen.py validate data/synthetic/new-run
```

`uv run` installs the inline script dependency automatically. With another
Python environment, install `tqdm>=4.66,<5` first. Pass `--no-progress` to disable
the bar. Generation progress counts completed rollouts; validation follows it
and is timed separately. Configurations, seeds, and output schemas are unchanged.

For reproducible file-size timing experiments:

```sh
uv run scripts/benchmark_tracegen.py --config configs/tracegen-size-timing.json \
  --traces data/synthetic/size-timing-2026-11-08 \
  --output results/tracegen-timing-2026-11-08
```

The requested sizes are approximate binary MiB of `nodes.jsonl + events.jsonl`.
The report records actual sizes, generation/validation wall times, accesses,
unique nodes, logical cache bytes, and external snapshot bytes. Increasing
rollouts primarily increases stream length, not the finite template working
set. The runs use the local filesystem and OS caching; they do not include an
explicit durable-storage flush. Policy replay timings are a separate experiment.

## Multi-GiB logical-cache suite

Generate large-result stress workloads with three seeds per family:

```sh
uv run scripts/generate_large_traces.py \
  --traces data/synthetic/large-2026-11-08 \
  --output results/large-traces-2026-11-08
```

Outputs are grouped by family and then by a uniquely named seed directory.
Each trace remains a standard catalog/events/manifest directory, independently
usable by the Rust replay and Python evaluator. Existing output traces are never
overwritten; use new destinations for another experiment.

This suite uses the existing memory-pressure fixture's **64 KiB–4 MiB result
size range** for all tools, 24 templates per task, and seeds 42/43/44. It retains
each family's runtime/cost distributions, reuse settings, and snapshot rules.
Balanced and popularity-shift use 256 tasks and 20,000 rollouts; memory-pressure
uses 128 tasks and 20,000 rollouts; expensive-reuse uses 512 tasks and 40,000
rollouts to expose enough distinct entries despite its strong template reuse.
The shift scenario's hot cohorts scale with task count.

These are explicitly **large-result synthetic stress cases**, not measurements
of typical real tool payload sizes. Their target is roughly 8–16 GiB of
`sum(cache_entry_bytes)` across unique nodes. Logical charges are not JSONL file
sizes, actual allocated payloads, process RSS, or external snapshot storage.

Reports retain exact configurations, generation/validation times, physical
JSONL sizes, repeat fractions, and bytes in nodes accessed more than once
(overall and per phase). Reused-entry bytes are a useful coverage diagnostic;
they do not prove a simultaneous or rolling working set of that size. Replay
the policies at the desired capacities to quantify actual eviction pressure.
