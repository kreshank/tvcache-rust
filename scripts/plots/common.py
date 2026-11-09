"""Shared input, styling, and output helpers; no simulation happens here."""
import argparse
import csv
import hashlib
import json
import math
import statistics
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter, LogLocator, FuncFormatter

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = ROOT / "results/compatibility-2026-11-07"
REFERENCES = Path(__file__).parent / "references/tvcache-v1"
ORIGINAL = "original-ttl-and-watermark"
POLICIES = [ORIGINAL, "fifo", "linear", "lru", "lfu", "lfu-persistent", "none"]
LABELS = {ORIGINAL: "Original enforcer", "fifo": "FIFO", "linear": "Linear TCG",
          "lru": "LRU", "lfu": "LFU", "lfu-persistent": "Persistent LFU", "none": "No cache",
          "lin-belady": "Fitted linear (Belady)", "small-belady": "Small neural (Belady)",
          "big-belady": "Big neural (Belady)"}
COLORS = dict(zip(POLICIES, ["#303846", "#999999", "#0072B2", "#009E73", "#D55E00", "#CC79A7", "#666666"]))
LEARNED_POLICIES = [f"{size}-{target}" for size in ("lin", "small", "big")
                    for target in ("belady", "logdist", "reuse", "benefit")
                    if size != "lin" or target != "benefit"]
POLICIES += LEARNED_POLICIES
COLORS.update({policy: plt.get_cmap("turbo")((i+.5)/len(LEARNED_POLICIES))
               for i, policy in enumerate(LEARNED_POLICIES)})
COLORS["lin-belady"] = COLORS["linear"]
SEED_CAPTION = ("Equal-weight means across seeds; error bars = observed min–max seed range, not confidence intervals.\n"
                "Ratios are computed per seed before averaging; unseeded inputs have no error bars.")
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
    "axes.spines.top": False, "axes.spines.right": False, "axes.titleweight": "bold",
    "axes.grid": True, "grid.alpha": .18, "axes.axisbelow": True,
    "figure.facecolor": "white", "savefig.facecolor": "white", "pdf.fonttype": 42})


def parser(description):
    p = argparse.ArgumentParser(description=description)
    p.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="benchmark directory")
    p.add_argument("--output", type=Path, help="run output directory; default results/plots/INPUT_NAME")
    p.add_argument("--engine", choices=["rust", "python-reference"], default="rust")
    p.add_argument("--snapshots", choices=["off", "on"], default="off", help="reference-policy mode")
    p.add_argument("--budget-position", choices=["smallest", "middle", "largest"], default="smallest",
                   help="nonzero capacity selected for single-capacity figures; curves always use the full sweep")
    selection = p.add_mutually_exclusive_group()
    selection.add_argument("--policies", nargs="+", help="policy names to display; overrides run.json plot_policies")
    selection.add_argument("--all-policies", action="store_true", help="display all policies, overriding the run default")
    return p


def read_csv(path, required):
    with Path(path).open(newline="") as stream:
        reader = csv.DictReader(stream)
        missing = set(required) - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path}: missing columns: {', '.join(sorted(missing))}")
        rows = list(reader)
    if not rows:
        raise ValueError(f"{path}: no data rows")
    return rows


def num(row, field):
    try:
        value = float(row[field])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{row.get('workload', 'row')} / {row.get('policy', '')}: invalid {field}") from exc
    if not math.isfinite(value):
        raise ValueError(f"nonfinite {field}")
    return value


def select_budget(rows, position):
    """Select a tested nonzero capacity; do not interpolate experiments."""
    budgets = sorted({num(r, "budget_mib") for r in rows if num(r, "budget_mib") > 0})
    if not budgets:
        raise ValueError("single-capacity figures need a nonzero tested budget")
    budget = budgets[{"smallest": 0, "middle": len(budgets)//2, "largest": -1}[position]]
    return budget, [r for r in rows if num(r, "budget_mib") == budget]


def ordered(rows):
    names = {r["policy"] for r in rows}
    return [p for p in POLICIES if p in names] + sorted(names - set(POLICIES))


def aggregate_seeds(rows, fields):
    """Average derived metrics by family/policy/capacity, keeping matched seed sets."""
    if not rows:
        return []
    seeded = any(r.get("family") or r.get("seed") for r in rows)
    if seeded and any(not r.get("family") or str(r.get("seed", "")) == "" for r in rows):
        raise ValueError("seed aggregation requires family and seed for every row")
    groups = {}
    for row in rows:
        family = row["family"] if seeded else row["workload"]
        key = family, row["policy"], num(row, "budget_mib")
        groups.setdefault(key, []).append(row)
    seed_sets = [{str(r["seed"]) for r in group} for group in groups.values()] if seeded else []
    if seeded and (any(len(s) != len(g) for s, g in zip(seed_sets, groups.values())) or
                   any(s != seed_sets[0] for s in seed_sets)):
        raise ValueError("seed aggregation requires the same completed seeds in every policy/capacity cell, without duplicates")
    result = []
    for (family, policy, budget), group in sorted(groups.items()):
        if not seeded and len(group) != 1:
            raise ValueError("duplicate unseeded workload/policy/capacity")
        row = ({"workload": family, "family": family, "policy": policy, "budget_mib": budget,
                "seed_ids": ",".join(sorted(str(r["seed"]) for r in group))}
               if seeded else dict(group[0]))
        row["seeds"] = len(group)
        row["display_role"] = "curve" if budget > 0 else "off-axis zero control"
        for field in fields:
            values = [num(r, field) for r in group]
            row.update({field: statistics.mean(values), field+"_minimum": min(values),
                        field+"_maximum": max(values),
                        field+"_standard_deviation": statistics.stdev(values) if len(values)>1 else 0})
        result.append(row)
    return result


def seed_errors(rows, field):
    """Asymmetric observed ranges around each mean, in Matplotlib's yerr format."""
    if all(num(r, "seeds") <= 1 for r in rows):
        return None
    return [[max(0, num(r, field)-num(r, field+"_minimum")) for r in rows],
            [max(0, num(r, field+"_maximum")-num(r, field)) for r in rows]]


def eviction_cells(rows):
    """Describe observed eviction pressure without assuming equal hits mean saturation."""
    if not rows or any(r.get("evictions", "") == "" for r in rows):
        return []
    groups = {}
    for row in rows:
        budget = num(row, "budget_mib")
        if budget > 0:
            groups.setdefault((row["workload"], budget), []).append(row)
    return [{"workload": workload, "budget_mib": budget,
             "policies": len(group), "minimum_evictions": min(num(r, "evictions") for r in group),
             "maximum_evictions": max(num(r, "evictions") for r in group),
             "hit_rate_spread": max(num(r, "hit_rate") for r in group)-min(num(r, "hit_rate") for r in group)}
            for (workload, budget), group in sorted(groups.items())]


def label(policy):
    return LABELS.get(policy, policy)


def color(policy):
    return COLORS.get(policy, plt.get_cmap("tab10")(int(hashlib.sha256(policy.encode()).hexdigest()[:6], 16) % 10))


def line_style(policy):
    """Policy curves use solid lines; colors identify the displayed policies."""
    return "-"


class Run:
    def __init__(self, args, *, summary=True):
        self.source = args.input.resolve()
        base_output = (args.output or ROOT / "results/plots" / self.source.name).resolve()
        if base_output == self.source or base_output in self.source.parents:
            raise ValueError("output must be a separate plot directory, not the input or its parent")
        self.output = base_output / f"{args.engine}-snapshots-{args.snapshots}"
        if args.engine == "rust" and args.snapshots == "on":
            raise ValueError("Rust replay does not admit snapshots; use --engine python-reference")
        self.engine = args.engine
        self.budget_position = args.budget_position
        self.mode = f"{args.engine}, snapshots {args.snapshots}"
        self.rows = []
        if summary:
            rows = read_csv(self.source / "summary.csv", ["engine", "snapshots", "workload", "policy", "budget_mib"])
            for row in rows:
                if row["snapshots"] not in {"True", "False"}:
                    raise ValueError("snapshots column must contain True or False")
                if row["engine"] == args.engine and (row["snapshots"] == "True") == (args.snapshots == "on"):
                    self.rows.append(row)
            if not self.rows:
                raise ValueError(f"no rows for {self.mode} in {self.source}")
            metadata_path = self.source / "run.json"
            metadata = json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
            requested = (None if getattr(args, "all_policies", False) else
                         getattr(args, "policies", None) or metadata.get("plot_policies"))
            if requested:
                missing = set(requested)-{r["policy"] for r in self.rows}
                if missing:
                    raise ValueError("requested policies absent from selected mode: " + ", ".join(sorted(missing)))
                self.rows = [r for r in self.rows if r["policy"] in requested]
            seen = set()
            for row in self.rows:
                key = row["workload"], row["policy"], num(row, "budget_mib")
                if key in seen:
                    raise ValueError(f"duplicate workload/policy/budget: {key}")
                if key[2] < 0:
                    raise ValueError("budget_mib must be nonnegative")
                seen.add(key)

    def grid(self, title):
        workloads = sorted({r["workload"] for r in self.rows})
        columns = min(2, len(workloads))
        fig, axes = plt.subplots(math.ceil(len(workloads)/columns), columns,
                                 figsize=(12, 4.0*math.ceil(len(workloads)/columns)), squeeze=False)
        fig.suptitle(title, fontsize=17, y=.98)
        for ax in axes.flat[len(workloads):]:
            ax.set_visible(False)
        for ax, name in zip(axes.flat, workloads):
            ax.set_title(name.replace("_", " "))
        return fig, list(zip(axes.flat, workloads))

    def save(self, fig, stem, rows, caption, *, bottom=.14, top=.84, wspace=.27, hspace=.45):
        path = self.output / stem
        path.parent.mkdir(parents=True, exist_ok=True)
        fig.text(.02, .016, caption, fontsize=8, color="#4B5563", va="bottom")
        if any(len(item.get_texts()) > 12 for item in fig.legends):
            top = min(top, .76)
        fig.subplots_adjust(top=top, bottom=bottom, left=.09, right=.97, hspace=hspace, wspace=wspace)
        for extension in ("png", "pdf"):
            fig.savefig(path.with_suffix("." + extension), dpi=180, bbox_inches="tight")
        plt.close(fig)
        with path.with_suffix(".csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=sorted(set().union(*(r.keys() for r in rows))))
            writer.writeheader()
            writer.writerows(rows)
        sources = [self.source / n for n in ("summary.csv", "validation.json", "run.json", "load-summary.csv")]
        sources += sorted(REFERENCES.glob("*.csv")) if stem.startswith("paper/") else []
        provenance = {"caption": caption, "input_directory": str(self.source), "mode": self.mode,
                      "budget_position": self.budget_position,
                      "plotted_policies": sorted({r["policy"] for r in rows if r.get("policy")}),
                      "sources_sha256": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources if p.is_file()}}
        path.with_suffix(".json").write_text(json.dumps(provenance, indent=2) + "\n")
        print(path.with_suffix(".png"))
        return path.with_suffix(".png")


def legend(fig, ax):
    entries = {}
    for panel in [ax, *fig.axes]:
        handles, names = panel.get_legend_handles_labels()
        entries.update(zip(names, handles))
    names, handles = list(entries), list(entries.values())
    if handles:
        fig.legend(handles, names, loc="upper center", bbox_to_anchor=(.5, .94),
                   ncol=min(5 if len(names)>8 else 4, len(names)), frameon=False,
                   fontsize=8 if len(names)>8 else 9)


def percentage(ax):
    ax.yaxis.set_major_formatter(PercentFormatter(1))


def capacity_axis(ax, budgets=None):
    """Positive capacities use equal spacing for each doubling."""
    ax.set_xscale("log", base=2)
    ax.xaxis.set_major_locator(LogLocator(base=2, numticks=10))
    ax.xaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:g}"))
    ax.set_xlabel("Cache capacity (MiB)")
    if budgets is not None:
        tested = sorted({float(b) for b in budgets if float(b)>0})
        ax.set_xticks(tested)
        ax.set_xlim(tested[0]/1.12, tested[-1]*1.12)


def zero_capacity_control(ax, values):
    """Show measured zero-budget values without inventing a positive x coordinate."""
    if values:
        lo, hi = min(values), max(values)
        value = f"{lo:.1%}" if math.isclose(lo, hi, abs_tol=1e-12) else f"{lo:.1%} to {hi:.1%}"
        ax.text(.03, .97, f"0 MiB control: {value} (off log axis)", transform=ax.transAxes,
                ha="left", va="top", fontsize=8, color="#475569",
                bbox={"facecolor": "white", "edgecolor": "#cbd5e1", "alpha": .9})


def main(render):
    try:
        render(parser(render.__doc__).parse_args())
    except (ValueError, OSError) as exc:
        sys.exit(f"error: {exc}")
