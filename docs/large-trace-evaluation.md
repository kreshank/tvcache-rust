# Large-trace policy evaluation

The input suite is `data/synthetic/large-2026-11-08`: four workload families,
three seeds each, with 9–14 GiB of logical cache-entry bytes per trace. The
comparison is all six Rust configurations at 1024, 2048, and 4096 MiB, starting
with an empty cache each time: **216 policy runs**.

```sh
cargo build --release --bin replay
python3 scripts/replay_large_traces.py \
  --output results/large-replay-v2-2026-11-08 --workers 9
```

The runner reads the generation suite's `summary.csv`, so inputs are explicit
leaf trace directories rather than the old small-fixture names. Each case saves
native decisions/report, independently scored metrics, and a validated receipt.
The parent process rebuilds `summary.csv` from completed receipts. Repeat the
same command to resume; differing inputs, code, or parameters require a new
output directory. A `completion.json` marker is written only after every case
has passed. The small-fixture compatibility runner remains available separately.

## Checks and semantics

Each worker validates input hashes, graph/rollout structure, and causal features.
Every decision log is checked for hit residency, resident eviction victims,
trace correspondence, and the full Rust entry-byte budget. Weitao's independent
evaluator then scores reconstruction and costs; hit counts and gross time/USD
savings must agree with the native report.

This is a **result-only replay**, with no admitted snapshots or TTL expiry.
External snapshot storage is excluded from these cache budgets. Entry payloads
are modeled byte charges, not allocated multi-GiB buffers. The evaluator's
unused-handle accounting and Rust's full-entry accounting are retained as
separate occupancy fields. Default modeled cache overheads and storage prices
are zero; tool times and dollar costs are synthetic fixture values.

`net_time_saved_ms / baseline_tool_time_ms` is savings in total modeled tool
work, including reconstruction; it is not measured RL wall-clock speedup.
Missing-parent bypasses follow the existing replay contract. Reconstruction
accounting does not implicitly admit replayed ancestors. Full client/server
lifecycle equivalence is not claimed.

The original enforcer retains its existing random HashMap ordering on equal
scores. Its seed range includes both workload variation and that tie behavior;
small single-run ranking differences should not be treated as conclusive.

## Replay bookkeeping improvements

The larger inputs exposed quadratic candidate-membership scans and unnecessary
allocation. Subtree members and their bytes are now maintained incrementally in
the same EntryId order as the old scan. Causal history uses borrowed path lookups
and records only observed ancestor IDs. Policy scoring/admission rules are
unchanged. Log-only Python scoring no longer copies a policy context it never
uses; the reference-policy path retains its immutable context copy.

Validation includes subtree membership/byte checks against a pairwise reference
over 256 forest subsets with removals, existing policy/reference replay tests,
byte-identical deterministic-policy decisions on the small pressure fixture,
and byte-identical linear decisions over the 199,507-access large balanced
trace. The Python evaluator produced exactly equal reports before and after
its allocation change. Source and binary hashes are retained with each run.

Pilot outputs are kept in `results/large-replay-2026-11-08`; the final matrix is
in `results/large-replay-v2-2026-11-08`. The final matrix initially used six
workers, then resumed with nine; `worker-history.json` records that transition.
This affects wall-time/CPU diagnostics, not trace-driven modeled metrics.

## Compare seeds without mixing workloads

```sh
scripts/plots/.venv/bin/python scripts/plots/plots_all.py \
  --input results/large-replay-v2-2026-11-08
```

All applicable plot families aggregate seeds, with one panel per workload family.
Lines/bars are equal-weight seed means. Error bars show the observed minimum/maximum
over seeds, not confidence intervals. Ratios are computed within each seed first;
comparisons with the original enforcer pair the same seed and capacity before
averaging. The `seed_summary` family covers hit rate, normalized net tool-time
savings, and evictions per 1000 requests. Every policy/capacity cell must contain
the same seeds before an aggregate plot can be generated. Raw per-trace metrics
and decisions remain available for inspection.
