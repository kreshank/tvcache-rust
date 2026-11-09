# Benchmark plots

Run from any working directory. Inputs and outputs are organized per benchmark
run; no benchmark or simulator is rerun by these scripts.

```sh
# From the repository root (use an existing environment with matplotlib):
python3 scripts/plots/plots_all.py

# Explicit directories; each input gets its own output directory:
python3 scripts/plots/plots_all.py \
  --inputs results/compatibility-2026-11-07 results/another-run \
  --output results/plots

# One plot family:
python3 scripts/plots/plots_capacity.py --input results/compatibility-2026-11-07

# Python reference curves stay separate from Rust; separate mode directories:
python3 scripts/plots/plots_capacity.py --input results/compatibility-2026-11-07 \
  --engine python-reference --snapshots on

# Single-capacity figures can show the middle or largest tested budget:
python3 scripts/plots/plots_all.py --input results/large-memory-2026-11-07 \
  --budget-position middle
```

An isolated environment was created for this run. To set up or reproduce it:

```sh
uv venv scripts/plots/.venv
uv pip install --python scripts/plots/.venv/bin/python -r scripts/plots/requirements.lock
scripts/plots/.venv/bin/python scripts/plots/plots_all.py
```

`requirements.lock` records the exact versions used; `requirements.txt` is the
small direct-dependency declaration if you prefer your existing environment.
`plots_all.py --output` names the gallery root; individual scripts' `--output`
names one run's output directory. By default, both produce the layout below.

```text
results/
  compatibility-2026-11-07/     # inputs stay together
    summary.csv
    validation.json           # optional: full-cache repeat ceilings
    run.json                  # optional: input provenance
    load-summary.csv          # optional: measured server load cells
  plots/
    index.html                # all generated run galleries
    compatibility-2026-11-07/
      index.html              # image gallery, data/PDF/provenance links
      README.md               # same figures for Markdown viewers
      rust-snapshots-off/
        capacity/
        tradeoffs/
        reconstruction/
        snapshots/
        scaling/
        paper/
```

Every figure has `.png`, vector `.pdf`, the plotted input rows in `.csv`, and
caption/source SHA-256 hashes in `.json`. Open `results/plots/index.html` in a
browser, or browse the per-run Markdown gallery. Filenames are stable for easy
regeneration; different runs and selected engine/snapshot modes do not overwrite
one another. The gallery reflects the most recent batch invocation; older
figure files remain on disk but are not silently added to it.

| Script | Figures |
| --- | --- |
| `plots_seed_summary.py` | Per-family seed means/ranges for hit rate, normalized net savings, and eviction pressure |
| `plots_capacity.py` | Hit rate and modeled time/USD savings against MiB; original included |
| `plots_tradeoffs.py` | Matched-budget time improvement over original; callback CPU cost |
| `plots_reconstruction.py` | Net savings only at a selected nonzero budget; reconstruction included |
| `plots_snapshots.py` | Python-reference snapshot savings and external storage |
| `plots_scaling.py` | Measured mean/p95 lookup latency and burst throughput |
| `plots_paper.py` | Versioned paper hit-rate / median-speedup references beside local estimates |
| `plots_all.py` | All applicable families, run galleries, and top-level index |

Capacity curves always show the entire sweep. `--budget-position` selects the
smallest (default), middle, or largest nonzero tested budget separately for each
workload in reconstruction, snapshot, and paper-context panels. For an even
number of budgets, middle selects the upper middle entry. These panels label
the actual MiB; no measurements are interpolated. Capacity curves also mark the
memory needed for the complete unique-entry catalog when validation is present.

All capacity x axes (including relative gains and policy CPU cost) use a
**base-2 logarithmic scale**, so each doubling occupies the same distance.
Zero-capacity measurements cannot lie on that axis: they appear as a separate
annotated control and remain in the relevant CSVs with
`display_role = off-axis zero control`. They are never shifted to an invented
positive capacity or connected to the positive-capacity curves. The timing
figure already excludes zero-capacity cases from its callback comparison.

Every gallery also reports how many nonzero workload/capacity cells had zero
evictions and saves the per-cell counts in `capacity-audit.json`. Capacity
figures shade the region that holds the full entry catalog and label sweeps
with no observed evictions. Coincident policy curves there are expected, not
evidence of a meaningful eviction-policy comparison. Equal hit rates alone are
never used to infer the absence of eviction.

Generating new raw trace directories does not change existing benchmark CSVs
or graphs. Replay the policies on the new inputs first, then pass that result
directory to the plot scripts. The gallery names its exact source directory.

## Larger-capacity experiments

The initial grids span roughly 10–100% of each synthetic entry catalog. The
first three catalogs contain only 6.9–9.8 MiB; `memory_pressure` contains about
1321 MiB. More memory than the catalog requires eliminates capacity eviction,
so policies reach the same repeat ceiling. Snapshot bytes are a separate,
potentially much larger external storage budget. Replay byte budgets are
simulated charges, not allocated process RSS or sandbox RAM measurements.

Sweep explicit capacities and keep their results in a new input directory:

```sh
python3 scripts/benchmark_compatibility.py \
  --budgets-mib 64 256 1024 2048 4096 \
  --output results/large-memory-2026-11-07
python3 scripts/plots/plots_all.py --input results/large-memory-2026-11-07 \
  --budget-position middle
```

`--datasets memory_pressure` can restrict the runner to one workload. Capacity
arguments are integer MiB. Custom grids need not start at zero or end above the
catalog size: full-cache checks run only when the tested capacity actually
holds the catalog. For larger capacities to distinguish policies, future traces
must also have larger active working sets, instead of merely repeating the
same small set of entries.

For the newly generated multi-GiB trace suite, use
`scripts/replay_large_traces.py` rather than the small-fixture runner. See
[large-trace evaluation](../../docs/large-trace-evaluation.md). Its results
contain `family` and `seed` columns, enabling the `seed_summary` plot family.
The batch plotter skips seed summaries when these columns are absent. For an
overview containing only those three figures, pass
`--skip capacity tradeoffs reconstruction snapshots scaling paper`.

## Input contract and checks

`summary.csv` uses the schema produced by `scripts/benchmark_compatibility.py`:
engine, snapshot mode, workload, policy, budget, evaluator metrics, and Rust
timing columns. Older `results/lru-lfu/summary.csv` has a different schema;
regenerate with the compatibility runner rather than inventing its missing net
metrics. New datasets and policy names are discovered from rows. No four-panel
or six-policy requirement is hardcoded into the layout.

Missing files/columns, nonfinite metric values, duplicate selected experiment
keys, and absent matched original baselines produce clear errors. Undefined
normalized savings for a zero baseline are omitted, not converted to zero; an
entirely undefined figure is skipped with a message.
Optional load data and Python reference data are skipped by the batch runner
when absent; individual scripts fail clearly if their own inputs are missing.
Use `--skip FAMILY ...` to request a subset. Unknown costs must be encoded and
handled upstream; these scripts never fill blank costs or create measurements.

The original enforcer's callback CPU time is not instrumented, so it is omitted
from that figure. Other overhead values exclude candidate construction. Curves
are single observations without uncertainty bars; intermediate segments connect
tested capacities rather than claim extra measurements. Snapshot figures always
use Python reference policies regardless of the primary engine selection; their
captions identify this explicitly. No Python curve is merged into a Rust policy.

## Comparing with the paper

References are in [`references/tvcache-v1`](references/tvcache-v1/README.md),
including exact source locations. Paper Figure 5 motivates hit-rate plots, Table
2 motivates speedup context, and Figure 8 motivates server scaling measurements.
Our current inputs support capacity curves and aggregate modeled work savings;
they do not supply matched training epochs, real TCG workloads, measured median
tool execution speedup, training rewards, GPU makespan, or process RSS. Those
require further measurements. The original repository enforcer is labeled
"Original enforcer" and must not be read as the paper's published result.

Paper panels keep real published measurements and synthetic replay estimates on
separate axes. In particular, local `speedup` divides total uncached tool time
by total modeled request time; the paper's Table 2 divides median tool-call
execution times. Local burst throughput also differs from controlled offered
RPS. These figures provide context, not a claim of reproducing or beating the
paper. Adding another paper/version means adding its own reference directory
with provenance and a plot using compatible metric definitions.

## Seed averaging and error bars

When inputs contain `family` and `seed`, capacity, tradeoff, reconstruction,
paper-context local panels, and seed-summary plots combine seeds by workload
family. Each point/bar is an equal-weight mean; error bars span the observed
minimum and maximum across seeds (not confidence intervals). Ratios are computed
per seed before averaging; comparisons against the original enforcer are paired
by seed and capacity. CSVs include the mean, minimum, maximum, standard deviation,
and seed count. Unseeded inputs retain their existing single-workload layout.

## Imported learned-policy results

A canonical per-run neural CSV can be validated and organized without replaying
experiments:

```sh
python3 scripts/import_neural_results.py SOURCE.csv \
  --output results/neural-validation-2026-11-08 --plot
```

The importer preserves the source CSV, checks the complete matched run grid and
metric identities, and writes summaries and provenance. The full gallery uses
all supplied policies. Additional `views/` galleries show baselines, fitted
linear models, small networks and large networks; model views retain the
original enforcer and persistent LFU as common controls. CSVs from different
trace suites are kept separate. Reported eviction counts and callback timings
retain the source's definitions/measurement limitations.

Policy curves use solid lines and distinct colors; fitted `lin-belady` uses the
blue previously used for untuned Linear TCG, which is hidden by default. Every positive
capacity plot labels the actual tested budgets, including non-doubling values
such as 1536 MiB. A run's optional `run.json` can supply `plot_notes` and
`related_galleries` for the Markdown/browser gallery.

### Saved policy selection

A run's `run.json` may set `plot_policies` to keep its default figures focused
without deleting any CSV rows. The neural importer defaults to baseline
policies except untuned `linear`, plus `lin-belady` (fitted linear), `small-belady`
and `big-belady`.
The same selection is applied to curves, error bars, legends and pressure audits.
Override it explicitly when needed:

```sh
python3 scripts/plots/plots_all.py --input results/neural-validation-2026-11-08 \
  --policies original-ttl-and-watermark lfu-persistent lin-belady small-belady big-belady
# Optional complete audit view:
python3 scripts/plots/plots_all.py --input results/neural-validation-2026-11-08 --all-policies
```
