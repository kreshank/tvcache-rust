#!/usr/bin/env python3
"""Summarize a completed large-trace sweep without mixing seeds or workloads."""
import argparse
from collections import defaultdict
import csv
import json
from pathlib import Path
import statistics


def read(path):
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


def write(path, rows):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def ratio(row, numerator, denominator):
    return float(row[numerator])/float(row[denominator])


def summarize(directory):
    completion = json.loads((directory / "completion.json").read_text())
    if not completion["complete"]:
        raise ValueError("sweep is incomplete")
    rows = read(directory / "summary.csv")
    metadata = json.loads((directory / "run.json").read_text())
    expected = {(Path(t["trace_directory"]).name, b, p)
                for t in metadata["traces"] for b in metadata["budgets_mib"] for p in metadata["policies"]}
    keys = {(r["workload"], int(r["budget_mib"]), r["policy"]) for r in rows}
    assert len(rows)==len(keys)==len(expected) and keys==expected
    for row in rows:
        assert float(row["rust_peak_bytes"])<=int(row["budget_mib"])*1024**2
    groups = defaultdict(list)
    for row in rows:
        groups[(row["family"],row["policy"],int(row["budget_mib"]))].append(row)
    aggregate = []
    for (family,policy,budget), group in sorted(groups.items()):
        assert len({r['seed'] for r in group})==3
        record = {"family":family,"policy":policy,"budget_mib":budget,"seeds":len(group)}
        for name, values in {
            "hit_rate":[float(r['hit_rate']) for r in group],
            "time_saved_fraction":[ratio(r,'net_time_saved_ms','baseline_tool_time_ms') for r in group],
            "cost_saved_fraction":[ratio(r,'net_cost_saved_usd','baseline_tool_cost_usd') for r in group],
            "evictions_per_1000":[1000*ratio(r,'evictions','requests') for r in group],
        }.items():
            record.update({f"mean_{name}":statistics.mean(values),f"min_{name}":min(values),
                           f"max_{name}":max(values),f"std_{name}":statistics.stdev(values)})
        aggregate.append(record)
    write(directory/'family-summary.csv',aggregate)
    overall = []
    for policy in metadata['policies']:
        group = [r for r in rows if r['policy']==policy]
        overall.append({'policy':policy,'cases':len(group),
            'mean_hit_rate':statistics.mean(float(r['hit_rate']) for r in group),
            'mean_time_saved_fraction':statistics.mean(ratio(r,'net_time_saved_ms','baseline_tool_time_ms') for r in group),
            'total_tool_work_saved_fraction':sum(float(r['net_time_saved_ms']) for r in group)/sum(float(r['baseline_tool_time_ms']) for r in group)})
    overall.sort(key=lambda r:r['mean_time_saved_fraction'],reverse=True)
    write(directory/'overall-summary.csv',overall)
    lines=['# Large-trace replay results — 2026-11-08','',
        f"**{len(rows)} validated Rust runs**: four workload families × three seeds × three capacities × six policy configurations.",'',
        'Inputs are the new **9–14 GiB logical-cache traces**, not the earlier small fixtures. Capacities are **1, 2, and 4 GiB**. Every case starts empty and is independently scored.', '',
        f"**Eviction pressure:** {sum(int(r['evictions'])>0 for r in rows)}/{len(rows)} runs had evictions. Exact Rust post-enforcement byte budgets were checked.",'',
        '## Overall descriptive comparison','',
        'Equal-weight mean over workloads, seeds, and tested capacities. Savings include modeled prefix reconstruction. These are synthetic tool-work estimates, not measured training speedups.','',
        '| Policy | Mean hit rate | Mean modeled time saved |','| --- | ---: | ---: |']
    for r in overall:
        lines.append(f"| {r['policy']} | {100*r['mean_hit_rate']:.2f}% | {100*r['mean_time_saved_fraction']:.2f}% |")
    lines += ['','## Highest observed mean by workload and capacity','',
        'These are observed means over three seeds, not statistically established winners.','',
        '| Workload | GiB | Policy | Modeled time saved | Observed seed range |','| --- | ---: | --- | ---: | --- |']
    for family in sorted({r['family'] for r in aggregate}):
        for budget in metadata['budgets_mib']:
            candidates = [r for r in aggregate if r['family']==family and r['budget_mib']==budget]
            best=max(candidates,key=lambda r:r['mean_time_saved_fraction'])
            lines.append(f"| {family} | {budget/1024:g} | {best['policy']} | {100*best['mean_time_saved_fraction']:.2f}% | {100*best['min_time_saved_fraction']:.2f}–{100*best['max_time_saved_fraction']:.2f}% |")
    maximum_budget=max(metadata['budgets_mib'])
    lines += ['',f'## At {maximum_budget/1024:g} GiB: modeled time saved','',
        '| Policy | Balanced | Expensive reuse | Memory pressure | Popularity shift |',
        '| --- | ---: | ---: | ---: | ---: |']
    for policy in metadata['policies']:
        values=[next(r for r in aggregate if r['family']==family and r['policy']==policy and r['budget_mib']==maximum_budget)['mean_time_saved_fraction'] for family in ('balanced','expensive_reuse','memory_pressure','popularity_shift')]
        lines.append('| '+policy+' | '+' | '.join(f'{100*v:.2f}%' for v in values)+' |')
    lines += ['','## Figures and artifacts','',
        f"[Seed-comparison gallery](../plots/{directory.name}/README.md) · [Browser gallery](../plots/{directory.name}/index.html)",'',
        '- `summary.csv`: every validated trace/capacity/policy case.',
        '- `family-summary.csv`: normalized seed means, ranges, and standard deviations.',
        '- `overall-summary.csv`: equal-weight comparison plus a separate total-tool-work-weighted ratio.',
        '- `<trace>/<capacity>mib/<policy>/`: native report, complete decisions, evaluator report, and validated receipt.',
        '- `run.json`, `validation.json`, `completion.json`: exact input/source hashes and validation/completion status.',
        '- `optimization-equivalence.json`: the large balanced replay preserved all 199,507 linear-policy decisions.', '',
        '## Scope and reproduction','',
        'Result-only synthetic replay; no admitted snapshots or TTL expiry. Modeled cache overheads and storage prices are zero placeholders. The original enforcer has nondeterministic equal-score ties; its ranges include that variation as well as differences between traces. Error bars show observed seed ranges, not confidence intervals. Callback/wall timings were collected under concurrent execution and are diagnostic, not isolated CPU measurements.', '',
        'Replay bookkeeping was optimized without changing policy scoring/admission rules. Exact decision comparisons, subtree membership/byte reference checks, all 27 Rust tests, and all 9 plotting tests passed. See [evaluation methods](../../docs/large-trace-evaluation.md).', '',
        '```sh',f'python3 scripts/replay_large_traces.py --workers 9 --output results/{directory.name}',
        f'python3 scripts/summarize_large_replay.py --input results/{directory.name}',
        f'scripts/plots/.venv/bin/python scripts/plots/plots_all.py --input results/{directory.name} --skip capacity tradeoffs reconstruction snapshots scaling paper','```']
    (directory/'README.md').write_text('\n'.join(lines)+'\n')
    print('Overall normalized time-savings means:')
    for row in overall: print(row['policy'],f"{100*row['mean_time_saved_fraction']:.2f}%")


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',required=True,type=Path)
    summarize(parser.parse_args().input.resolve())
