#!/usr/bin/env python3
"""Import a plot-compatible learned-policy CSV into its own reproducible run directory."""
import argparse
from collections import defaultdict
import csv
import hashlib
import itertools
import json
import math
from pathlib import Path
import shutil
import statistics
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = 'original-ttl-and-watermark'
DISPLAY_LEARNED = ('lin-belady','small-belady','big-belady')
NUMERIC = ['budget_mib','seed','requests','hits','hit_rate','evictions',
           'baseline_tool_time_ms','net_time_saved_ms','modeled_request_ms',
           'baseline_tool_cost_usd','net_cost_saved_usd','rust_policy_ns_per_request','speedup']
REQUIRED = ['engine','snapshots','workload','family','policy','kind',*NUMERIC]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False)+'\n')


def write_csv(path, rows, fields=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='') as stream:
        writer=csv.DictWriter(stream, fieldnames=fields or list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def validate(rows):
    if not rows:
        raise ValueError('input CSV has no runs')
    missing=set(REQUIRED)-set(rows[0])
    if missing:
        raise ValueError('missing plot fields: '+', '.join(sorted(missing)))
    seen=set(); identities={}; baselines={}; kinds={}
    for line, row in enumerate(rows, 2):
        if row['engine']!='rust' or row['snapshots']!='False':
            raise ValueError(f'line {line}: expected result-only Rust runs (rust / False)')
        if any(not row[k] for k in ('workload','family','policy')) or row['kind'] not in ('baseline','learned'):
            raise ValueError(f'line {line}: invalid run identity or policy kind')
        if 'ALL' in (row['family'],row['budget_mib'],row['workload']):
            raise ValueError('use per-seed runs, not ALL aggregate rows')
        values={k:float(row[k]) for k in NUMERIC}
        if not all(math.isfinite(v) for v in values.values()):
            raise ValueError(f'line {line}: metrics must be finite')
        for key in ('budget_mib','seed','requests','hits','evictions'):
            if values[key]<0 or not values[key].is_integer():
                raise ValueError(f'line {line}: {key} must be a nonnegative integer')
        if values['requests']<=0 or not 0<=values['hit_rate']<=1 or values['rust_policy_ns_per_request']<0:
            raise ValueError(f'line {line}: invalid count, hit fraction, or timing')
        if values['baseline_tool_time_ms']<=0 or values['baseline_tool_cost_usd']<=0 or values['modeled_request_ms']<=0:
            raise ValueError(f'line {line}: positive baseline time/cost and served time required')
        for actual, expected in [(values['hit_rate'],values['hits']/values['requests']),
             (values['net_time_saved_ms'],values['baseline_tool_time_ms']-values['modeled_request_ms']),
             (values['speedup'],values['baseline_tool_time_ms']/values['modeled_request_ms'])]:
            if not math.isclose(actual,expected,rel_tol=1e-9,abs_tol=1e-6):
                raise ValueError(f'line {line}: hit rate, net savings, or speedup disagrees with its totals')
        if values['net_cost_saved_usd']>values['baseline_tool_cost_usd']+1e-9:
            raise ValueError(f'line {line}: net USD savings exceed the uncached cost')
        key=row['workload'],row['policy'],int(values['budget_mib'])
        if key in seen:
            raise ValueError(f'duplicate workload/policy/budget: {key}')
        seen.add(key)
        identity=row['family'],int(values['seed'])
        if identity in identities and identities[identity]!=row['workload']:
            raise ValueError('one family/seed maps to multiple trace identities')
        identities[identity]=row['workload']
        if row['policy'] in kinds and kinds[row['policy']]!=row['kind']:
            raise ValueError('policy has inconsistent baseline/learned classification')
        kinds[row['policy']]=row['kind']
        reference=tuple(values[k] for k in ('requests','baseline_tool_time_ms','baseline_tool_cost_usd'))
        if row['workload'] in baselines and any(not math.isclose(a,b,rel_tol=1e-12) for a,b in zip(reference,baselines[row['workload']])):
            raise ValueError('policies disagree on the same trace baseline totals')
        baselines[row['workload']]=reference
    families=sorted({r['family'] for r in rows}); seeds=sorted({int(r['seed']) for r in rows})
    policies=sorted(kinds); budgets=sorted({int(r['budget_mib']) for r in rows})
    actual={(r['family'],int(r['seed']),r['policy'],int(r['budget_mib'])) for r in rows}
    if actual!=set(itertools.product(families,seeds,policies,budgets)):
        raise ValueError('incomplete family/seed/policy/budget grid; do not invent missing measurements')
    if ORIGINAL not in policies:
        raise ValueError('matched original-enforcer rows are required for the complete gallery')
    return {'runs':len(rows),'families':families,'seeds':seeds,'policies':policies,
            'budgets_mib':budgets,'trace_count':len(baselines),
            'reported_evictions_positive':sum(int(r['evictions'])>0 for r in rows),
            'checks':['required fields and finite values','unique complete run grid','consistent trace baselines',
                      'hit/count identity','net time identity','speedup identity'],
            'scope':'CSV consistency checks only; source decisions, trace hashes and timing conditions were not supplied'}


def summarize(rows, output):
    groups=defaultdict(list)
    for row in rows:
        groups[row['family'],row['policy'],int(row['budget_mib'])].append(row)
    families=[]
    metrics={'hit_rate':lambda r:float(r['hit_rate']),
             'time_saved_fraction':lambda r:float(r['net_time_saved_ms'])/float(r['baseline_tool_time_ms']),
             'cost_saved_fraction':lambda r:float(r['net_cost_saved_usd'])/float(r['baseline_tool_cost_usd']),
             'policy_us_per_request':lambda r:float(r['rust_policy_ns_per_request'])/1000}
    for (family,policy,budget), group in sorted(groups.items()):
        record={'family':family,'policy':policy,'kind':group[0]['kind'],'budget_mib':budget,'seeds':len(group)}
        for name,metric in metrics.items():
            values=[metric(r) for r in group]
            record.update({f'mean_{name}':statistics.mean(values),f'min_{name}':min(values),
                           f'max_{name}':max(values),f'std_{name}':statistics.stdev(values) if len(values)>1 else 0})
        families.append(record)
    write_csv(output/'family-summary.csv',families)
    overall=[]
    for policy in sorted({r['policy'] for r in rows}):
        group=[r for r in rows if r['policy']==policy]
        record={'policy':policy,'kind':group[0]['kind'],'cases':len(group)}
        record.update({f'mean_{name}':statistics.mean(metric(r) for r in group) for name,metric in metrics.items()})
        overall.append(record)
    overall.sort(key=lambda r:r['mean_time_saved_fraction'],reverse=True)
    write_csv(output/'overall-summary.csv',overall)
    return overall


def import_results(source, output):
    source=source.resolve(); output=output.resolve()
    if source==output/'summary.csv' or output in source.parents:
        raise ValueError('import source must be outside its destination run directory')
    with source.open(newline='',encoding='utf-8-sig') as stream:
        reader=csv.DictReader(stream); fields=reader.fieldnames; rows=list(reader)
    audit=validate(rows)
    digest=sha(source)
    display=[p for p in audit['policies'] if p!='linear' and
             (any(r['policy']==p and r['kind']=='baseline' for r in rows) or p in DISPLAY_LEARNED)]
    previous=output/'run.json'
    if previous.exists() and json.loads(previous.read_text())['source_sha256']!=digest:
        raise ValueError('destination contains a different import; choose a new directory')
    output.mkdir(parents=True,exist_ok=True)
    (output/'source').mkdir(exist_ok=True)
    shutil.copyfile(source,output/'source/summary.csv')
    write_csv(output/'summary.csv',rows,fields)
    notes=[
        f"Imported {audit['runs']} reported runs: {audit['trace_count']} traces, {len(audit['policies'])} policies, seeds {audit['seeds']}, budgets {audit['budgets_mib']} MiB.",
        'Default plots show five baselines plus fitted lin-belady, small-belady and big-belady. Untuned Linear TCG and other learned variants remain in the CSV but are hidden.',
        'This validation suite has matched baseline and learned rows. It is separate from the larger seed-42/43/44 trace suite; those rows are not pooled.',
        'Means and min–max error bars use the three supplied seeds. Time/USD savings are normalized by all uncached work, not saved_fraction_of_achievable.',
        'Validation split is inferred from the known trace identities; the CSV contains no split column or trace hashes. Model-selection validation scores are not held-out test results.',
        'Evictions are source-reported counts; immediate incoming discards may be included in the source counter. No decision logs were supplied to reconcile this definition.',
        'Timing conditions were not supplied. Policy callback times are diagnostics, not isolated CPU-cost estimates.'
    ]
    view_rows={}
    controls={ORIGINAL,'lfu-persistent'}
    for view,prefix in [('baselines',None),('linear','lin-'),('small','small-'),('big','big-')]:
        selected=[r for r in rows if (r['kind']=='baseline' if prefix is None else
                  r['policy'] in controls or r['policy'].startswith(prefix) or (view=='linear' and r['policy']=='linear'))]
        if prefix and not any(r['policy'].startswith(prefix) for r in selected):
            continue
        folder=output/'views'/view
        displayed_view=sorted({r['policy'] for r in selected if r['policy'] in display})
        write_csv(folder/'summary.csv',selected,fields)
        dump(folder/'run.json',{'source_sha256':digest,'source_run':str(output),'view':view,
             'plot_policies':displayed_view,
             'plot_notes':[f"Focused {view} comparison; rows are a subset of the same imported run.",
                           'Neural model views include the original enforcer and persistent LFU as common controls.',*notes[2:]],
             'related_galleries':[{'label':f"Main {len(display)}-policy comparison and other focused views",'path':'../../index.html'}]})
        view_rows[view]=len(selected)
    metadata={'source_path':str(source),'source_sha256':digest,'imported_summary_sha256':sha(output/'summary.csv'),
              'format':'existing canonical plot CSV; all field values retained','plot_notes':notes,'plot_policies':display,
              'related_galleries':[{'label':f"{name.title()} — {len(json.loads((output/'views'/name/'run.json').read_text())['plot_policies'])} policies",
                                    'path':f'views/{name}/index.html'} for name in view_rows],
              'audit':audit,'views':view_rows}
    dump(output/'run.json',metadata)
    dump(output/'validation-report.json',audit)
    overall=summarize(rows,output)
    baseline_count=sum(r['kind']=='baseline' for r in overall)
    learned_count=len(overall)-baseline_count
    gallery=f'../plots/{output.name}'
    lines=['# Learned-policy validation results','',
           f"**{audit['runs']} imported runs**: {len(audit['families'])} workloads, {len(audit['seeds'])} seeds, {len(audit['budgets_mib'])} tested budgets, {baseline_count} baselines and {learned_count} learned variants.",'',
           f'[Selected-policy gallery]({gallery}/index.html) · [Markdown gallery]({gallery}/README.md)','',
           f"The main plots display **{len(display)} policies**: the baselines except untuned Linear TCG, plus fitted `lin-belady`, `small-belady` and `big-belady`. All imported rows are preserved; Linear TCG and the other learned targets are hidden by default.",'',
           '## Start with the focused views','']
    lines.extend(f'- [{name.title()} comparison]({gallery}/views/{name}/index.html)' for name in view_rows)
    lines += ['','Each focused view contains hit-rate, normalized net-time-savings and normalized net-USD-savings figures. The complete gallery also includes eviction pressure, paired original-baseline comparisons, callback overhead, selected-capacity net savings and paper-context panels.','',
              '## Import and comparison scope','']
    lines.extend('- '+note for note in notes)
    lines += ['','The 512/1024/2048 MiB rows overlap the earlier neural validation export; the supplied file also includes 1536 MiB. This import uses only the supplied CSV and does not replace rows with values from older exports.','',
              '## Overall descriptive means','',
              'Equal-weight means across workloads, seeds and tested budgets. These are synthetic modeled work savings, not measured training speedups. Close means are not statistically established wins.','',
              '| Policy | Kind | Hit rate | Net time saved | Net USD saved |',
              '| --- | --- | ---: | ---: | ---: |']
    lines.extend(f"| {r['policy']} | {r['kind']} | {100*r['mean_hit_rate']:.2f}% | {100*r['mean_time_saved_fraction']:.2f}% | {100*r['mean_cost_saved_fraction']:.2f}% |" for r in overall if r['policy'] in display)
    lines += ['','## Files and reproduction','',
              '- `source/summary.csv`: byte-for-byte original import.',
              '- `summary.csv`: plot input, retaining all supplied field values.',
              '- `run.json`, `validation-report.json`: source hashes, checks and interpretation limits.',
              '- `family-summary.csv`, `overall-summary.csv`: computed means/ranges and policy summaries.',
              '- `views/`: policy subsets drawn from this same file; no new measurements.',
              '- `run.json` → `plot_policies`: saved default display selection; `--policies` or `--all-policies` can override it.',
              '- No raw traces, full decision logs, model hashes or hardware/timing provenance were included in the uploaded file.','',
              '```sh',f'python3 scripts/import_neural_results.py SOURCE.csv --output results/{output.name} --plot','```','']
    (output/'README.md').write_text('\n'.join(lines))
    return metadata


def plot(output,metadata):
    executable=ROOT/'scripts/plots/.venv/bin/python'
    executable=str(executable) if executable.exists() else sys.executable
    command=[executable,str(ROOT/'scripts/plots/plots_all.py')]
    subprocess.run([*command,'--input',str(output)],cwd=ROOT,check=True)
    views=[str(output/'views'/name) for name in metadata['views']]
    subprocess.run([*command,'--inputs',*views,'--output',str(ROOT/'results/plots'/output.name/'views'),
                    '--skip','seed_summary','tradeoffs','reconstruction','snapshots','scaling','paper'],cwd=ROOT,check=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('csv',type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--plot',action='store_true',help='generate the full gallery and focused capacity views')
    args=parser.parse_args()
    try:
        output=args.output.resolve()
        metadata=import_results(args.csv,output)
        print(f"Validated and imported {metadata['audit']['runs']} runs into {output}",flush=True)
        if args.plot:
            plot(output,metadata)
    except (ValueError,OSError,KeyError,subprocess.CalledProcessError) as error:
        parser.exit(1,f'error: {error}\n')


if __name__=='__main__':
    main()
