#!/usr/bin/env python3
"""Generate plots and per-run galleries for one or more benchmark directories."""
import html
import json
from pathlib import Path
import sys

from common import ROOT, Run, parser, read_csv, eviction_cells
import plots_capacity
import plots_tradeoffs
import plots_reconstruction
import plots_snapshots
import plots_scaling
import plots_paper
import plots_seed_summary

PLOTS = {"seed_summary": plots_seed_summary, "capacity": plots_capacity, "tradeoffs": plots_tradeoffs,
         "reconstruction": plots_reconstruction, "snapshots": plots_snapshots,
         "scaling": plots_scaling, "paper": plots_paper}


def gallery(directory, figures, source, skipped, cells, policies=None):
    cards, markdown = [], [f"# Plots: {source.name}", "", f"Input: `{source}`", "",
        "Replay estimates are not measured training speedups. Reference panels, when present, use unmatched workloads.", ""]
    metadata_path = source / "run.json"
    metadata = json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
    notes = metadata.get("plot_notes", [])
    related = metadata.get("related_galleries", [])
    for note in notes:
        markdown.extend([str(note), ""])
    if policies:
        markdown.extend(["Displayed policies: " + ", ".join(f"`{name}`" for name in policies) + ".", ""])
    if related:
        markdown.extend(["## Focused views", ""])
        markdown.extend(f"- [{item['label']}]({item['path']})" for item in related)
        markdown.append("")
    pressure_note = ""
    if cells:
        zero = sum(c["maximum_evictions"] == 0 for c in cells)
        pressure_note = (f"Eviction check: {zero} of {len(cells)} nonzero workload/capacity cells had zero evictions "
                         "across the selected policies. Such cells do not distinguish eviction strategies. "
                         "This gallery only shows the input run named above; it does not automatically benchmark newly generated traces.")
        markdown.extend([pressure_note, "", "[Capacity/eviction audit](capacity-audit.json)", ""])
    for path in figures:
        relative = path.relative_to(directory).as_posix()
        caption = json.loads(path.with_suffix(".json").read_text())["caption"]
        stem = relative[:-4]
        cards.append(f'<article><h2>{html.escape(stem)}</h2><a href="{relative}"><img src="{relative}" loading="lazy"></a>'
                     f'<p>{html.escape(caption)}</p><p><a href="{stem}.pdf">PDF</a> · '
                     f'<a href="{stem}.csv">Plot data</a> · <a href="{stem}.json">Provenance</a></p></article>')
        markdown.extend([f"## {stem}", "", f"![{stem}]({relative})", "", caption, "",
                         f"[PDF]({stem}.pdf) · [Data]({stem}.csv) · [Provenance]({stem}.json)", ""])
    if skipped:
        markdown.extend(["Skipped: " + "; ".join(skipped), ""])
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "README.md").write_text("\n".join(markdown))
    (directory / "capacity-audit.json").write_text(json.dumps(cells, indent=2) + "\n")
    page = '<!doctype html><meta charset="utf-8"><title>TVCache plots</title><style>' \
        'body{font:16px system-ui;background:#f3f5f8;color:#253047;max-width:1400px;margin:32px auto;padding:0 24px}' \
        'article{background:white;border:1px solid #dde2ea;border-radius:12px;padding:24px;margin:24px 0}' \
        'img{width:100%;height:auto}h2{font-size:18px}p{line-height:1.5;white-space:pre-line}a{color:#0072b2}</style>'
    page += f'<h1>TVCache · {html.escape(source.name)}</h1><p>Input: {html.escape(str(source))}</p>'
    page += '<p>Replay estimates are not measured training speedups. Reference panels, when present, use unmatched workloads.</p>'
    for note in notes:
        page += '<p>' + html.escape(str(note)) + '</p>'
    if policies:
        page += '<p><strong>Displayed policies:</strong> ' + html.escape(', '.join(policies)) + '</p>'
    if related:
        page += '<article><h2>Focused views</h2><ul>' + ''.join(
            f'<li><a href="{html.escape(item["path"], quote=True)}">{html.escape(item["label"])}</a></li>'
            for item in related) + '</ul></article>'
    if pressure_note:
        page += '<article><strong>Check cache pressure before comparing policies</strong><p>' + html.escape(pressure_note) + '</p></article>'
    page += "".join(cards)
    if skipped:
        page += '<p>Skipped: ' + html.escape("; ".join(skipped)) + '</p>'
    (directory / "index.html").write_text(page)


def main():
    p = parser(__doc__)
    p.add_argument("--inputs", nargs="+", type=Path, help="multiple benchmark directories; replaces --input")
    p.add_argument("--skip", nargs="+", choices=list(PLOTS), default=[])
    args = p.parse_args()
    sources = [v.resolve() for v in (args.inputs or [args.input])]
    if len({s.name for s in sources}) != len(sources):
        p.error("input directory names must be unique to avoid output collisions")
    output_root = (args.output or ROOT / "results/plots").resolve()
    for source in sources:
        args.input, args.output = source, output_root / source.name
        figures, skipped = [], []
        rows = read_csv(source / "summary.csv", ["engine"])
        for name, module in PLOTS.items():
            reason = None
            if name in args.skip:
                reason = "requested"
            elif name == "seed_summary" and not all(r.get("family") and r.get("seed") for r in rows):
                reason = "family/seed columns absent"
            elif name == "scaling" and not (source / "load-summary.csv").exists():
                reason = "load-summary.csv absent"
            elif name == "snapshots" and not any(r["engine"] == "python-reference" for r in rows):
                reason = "Python reference data absent"
            elif name == "tradeoffs" and args.engine != "rust":
                reason = "requires original Rust enforcer"
            if reason:
                skipped.append(f"{name}: {reason}")
                print(f"skip {name}: {reason}")
                continue
            figures.extend(module.render(args))
        selected = Run(args).rows
        gallery(args.output, figures, source, skipped, eviction_cells(selected), sorted({r["policy"] for r in selected}))
        print(f"Gallery: {args.output / 'index.html'}")
    output_root.mkdir(parents=True, exist_ok=True)
    links = [f'<li><a href="{html.escape(d.name)}/index.html">{html.escape(d.name)}</a></li>'
             for d in sorted(output_root.iterdir()) if d.is_dir() and (d / "index.html").is_file()]
    (output_root / "index.html").write_text('<!doctype html><meta charset="utf-8"><title>Benchmark plots</title>'
        '<h1>Benchmark plot galleries</h1><ul>' + ''.join(links) + '</ul>')
    runs = [d for d in sorted(output_root.iterdir()) if d.is_dir() and (d / "index.html").is_file()]
    (output_root / "README.md").write_text("# Benchmark plot galleries\n\n[Open browser index](index.html)\n\n" +
        "\n".join(f"- [{d.name}]({d.name}/README.md) · [Browser gallery]({d.name}/index.html)" for d in runs) + "\n")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError) as exc:
        sys.exit(f"error: {exc}")
