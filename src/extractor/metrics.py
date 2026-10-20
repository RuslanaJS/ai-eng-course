"""Metrics for extraction runs: field accuracy vs the golden set, validity, latency, cost.

    uv run python -m extractor.metrics                 # one row per results/*.jsonl run
    uv run python -m extractor.metrics results/x.jsonl # one specific run, with per-field detail

Accuracy is measured only on texts that have a golden label (data/golden/NNN.json).
An invalid model answer counts as wrong for every field of that text.
"""

import argparse
import json
import re
from pathlib import Path
from typing import Any

from extractor.run import ROOT, cost_usd, load_config

# (field name, path inside the record). Amenities are scored separately (soft match).
FIELDS: list[tuple[str, tuple[str, ...]]] = [
    ("project_name", ("project_name",)),
    ("developer", ("developer",)),
    ("street", ("address", "street")),
    ("district", ("address", "district")),
    ("city", ("address", "city")),
    ("completion_date", ("completion_date",)),
    ("area_m2", ("area_m2",)),
    ("rooms", ("rooms",)),
    ("floor", ("floor",)),
    ("price_per_m2_pln", ("price_per_m2_pln",)),
    ("finish", ("finish",)),
    ("parking", ("parking",)),
]

LEGAL_FORMS = re.compile(
    r"\b(sp\.? ?z ?o\.? ?o\.?|sp\.? ?k\.?|s\.? ?a\.?|spółka z ograniczoną odpowiedzialnością|"
    r"spółka akcyjna|spółka komandytowa|ska)\b"
)
STREET_PREFIX = re.compile(r"^(ul|al|pl|os)\.? ")


def norm_text(value: str) -> str:
    """Lowercase, drop punctuation and repeated spaces."""
    value = re.sub(r"[.,;:()\"']", " ", value.casefold())
    return re.sub(r"\s+", " ", value).strip()


def norm_developer(value: str) -> str:
    """Compare company names without the legal form (Sp. z o.o., S.A., ...)."""
    return re.sub(r"\s+", " ", LEGAL_FORMS.sub(" ", norm_text(value))).strip()


def norm_street(value: str) -> str:
    return STREET_PREFIX.sub("", norm_text(value))


def get_path(record: dict[str, Any] | None, path: tuple[str, ...]) -> Any:
    value: Any = record
    for key in path:
        value = value.get(key) if isinstance(value, dict) else None
    return value


def is_null(value: Any) -> bool:
    """None, an enum 'not_stated' or an empty list all mean 'the text does not say'."""
    return value is None or value == "not_stated" or value == []


def values_match(field: str, gold: Any, pred: Any) -> bool:
    if is_null(gold) or is_null(pred):
        return is_null(gold) and is_null(pred)
    if field == "price_per_m2_pln":
        return all(abs((gold.get(k) or 0) - (pred.get(k) or 0)) < 0.5 for k in ("min", "max"))
    if field == "area_m2":
        return abs(gold - pred) < 0.01
    if field == "developer":
        return norm_developer(gold) == norm_developer(pred)
    if field == "street":
        return norm_street(gold) == norm_street(pred)
    if isinstance(gold, str) and isinstance(pred, str) and field not in ("finish", "parking"):
        return norm_text(gold) == norm_text(pred)
    return gold == pred


def amenities_f1(gold: list[str], pred: list[str]) -> float:
    """Soft F1: two items match when one normalized string contains the other."""
    if not gold and not pred:
        return 1.0
    if not gold or not pred:
        return 0.0
    g, p = [norm_text(x) for x in gold], [norm_text(x) for x in pred]

    def same(a: str, b: str) -> bool:
        return a in b or b in a

    recall = sum(any(same(a, b) for b in p) for a in g) / len(g)
    precision = sum(any(same(a, b) for a in g) for b in p) / len(p)
    return 0.0 if recall + precision == 0 else 2 * recall * precision / (recall + precision)


def percentile(values: list[float], q: float) -> float:
    """Linear-interpolated percentile, q in 0..100."""
    if not values:
        return 0.0
    xs = sorted(values)
    pos = (len(xs) - 1) * q / 100
    lo, hi = int(pos), min(int(pos) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def load_golden(folder: str = "golden") -> dict[str, dict[str, Any]]:
    """folder: "golden" (development set) or "golden_test" (held-out test set)."""
    return {
        p.stem: json.loads(p.read_text(encoding="utf-8"))
        for p in sorted((ROOT / "data" / folder).glob("0*.json"))
    }


def load_rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def compute_metrics(
    rows: list[dict[str, Any]],
    golden: dict[str, dict[str, Any]],
    price_per_mtok: dict[str, float],
) -> dict[str, Any]:
    n = len(rows)
    # results written before the correction step have no status: infer it from validity
    statuses = [r.get("status") or ("ok" if r["valid"] else "failed") for r in rows]
    latencies = [r["latency_s"] for r in rows]
    hits = {name: 0 for name, _ in FIELDS}
    gold_rows = [r for r in rows if r["id"] in golden]
    missing = sorted(set(golden) - {r["id"] for r in rows})  # labeled texts with no result
    null_fields = hallucinated = 0
    amenity_scores = []
    for row in gold_rows:
        gold, pred = golden[row["id"]], row["record"]  # pred is None for an invalid answer
        for name, path in FIELDS:
            g, p = get_path(gold, path), get_path(pred, path)
            if pred is not None and values_match(name, g, p):
                hits[name] += 1
            if is_null(g):
                null_fields += 1
                hallucinated += pred is not None and not is_null(p)
        amenity_scores.append(
            amenities_f1(gold.get("amenities", []), (pred or {}).get("amenities", []))
        )
    g_n = len(gold_rows)
    accuracy = {name: hits[name] / g_n if g_n else 0.0 for name in hits}
    first = rows[0] if rows else {}
    return {
        "run": f"{first.get('model_key')} / {first.get('prompt_version')} / {first.get('sampling')}",
        "n_texts": n,
        "valid_rate": sum(r["valid"] for r in rows) / n if n else 0.0,
        "first_try_rate": statuses.count("ok") / n if n else 0.0,
        "fixed": statuses.count("fixed"),
        "failed": statuses.count("failed"),
        "latency_p50_s": percentile(latencies, 50),
        "latency_p95_s": percentile(latencies, 95),
        "cost_per_1000_docs_usd": 1000 * sum(cost_usd(r, price_per_mtok) for r in rows) / n
        if n
        else 0.0,
        "golden_n": g_n,
        "golden_missing": missing,
        "field_accuracy": accuracy,
        "overall_accuracy": sum(accuracy.values()) / len(accuracy) if accuracy else 0.0,
        "amenities_f1": sum(amenity_scores) / len(amenity_scores) if amenity_scores else 0.0,
        "hallucination_rate": hallucinated / null_fields if null_fields else 0.0,
        "hallucinated": hallucinated,
        "null_fields": null_fields,
    }


def summary_table(all_metrics: list[dict[str, Any]]) -> str:
    head = (
        "| run | valid (1st try) | accuracy | amenities F1 | hallucination "
        "| p50 s | p95 s | $/1000 docs |"
    )
    lines = [head, "|---|---|---|---|---|---|---|---|"]
    for m in all_metrics:
        lines.append(
            f"| {m['run']} | {m['valid_rate']:.0%} ({m['first_try_rate']:.0%}) "
            f"| {m['overall_accuracy']:.1%} "
            f"| {m['amenities_f1']:.2f} | {m['hallucinated']}/{m['null_fields']} "
            f"| {m['latency_p50_s']:.1f} | {m['latency_p95_s']:.1f} "
            f"| {m['cost_per_1000_docs_usd']:.2f} |"
        )
    for m in all_metrics:
        if m["golden_missing"]:
            lines.append(f"\nWARNING {m['run']}: no result for golden ids {m['golden_missing']}")
    return "\n".join(lines)


def report_table(dev: list[dict[str, Any]], test: list[dict[str, Any]]) -> str:
    """One row per run with both labeled sets side by side (for REPORT.md)."""
    head = (
        "| Model | Prompt | Sampling | Valid (1st try) | Dev acc. | Test acc. | Amenities F1 (dev) "
        "| Halluc. dev / test | p50 s | p95 s | $ / 1000 docs |"
    )
    lines = [head, "|---|---|---|---|---|---|---|---|---|---|---|"]
    for d, t in zip(dev, test, strict=True):
        model, prompt, sampling = (x.strip() for x in d["run"].split("/"))
        lines.append(
            f"| {model} | {prompt} | {sampling} | {d['valid_rate']:.0%} ({d['first_try_rate']:.0%}) "
            f"| {d['overall_accuracy']:.1%} | {t['overall_accuracy']:.1%} | {d['amenities_f1']:.2f} "
            f"| {d['hallucinated']}/{d['null_fields']}, {t['hallucinated']}/{t['null_fields']} "
            f"| {d['latency_p50_s']:.1f} | {d['latency_p95_s']:.1f} | {d['cost_per_1000_docs_usd']:.2f} |"
        )
    return "\n".join(lines)


def field_table(metrics: dict[str, Any]) -> str:
    lines = ["| field | accuracy |", "|---|---|"]
    lines += [f"| {k} | {v:.0%} |" for k, v in metrics["field_accuracy"].items()]
    return "\n".join(lines)


def metrics_for_file(path: Path, golden: dict[str, dict[str, Any]]) -> dict[str, Any]:
    rows = load_rows(path)
    price = load_config("models.yaml")[rows[0]["model_key"]]["price_per_mtok"]
    return compute_metrics(rows, golden, price)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "files", nargs="*", type=Path, help="results files (default: all full runs)"
    )
    parser.add_argument(
        "--report", action="store_true", help="one combined table (dev and test) for REPORT.md"
    )
    parser.add_argument(
        "--set",
        choices=["dev", "test"],
        default="dev",
        help="dev = data/golden, test = data/golden_test",
    )
    args = parser.parse_args(argv)

    files = args.files or [
        p for p in sorted((ROOT / "results").glob("*.jsonl")) if "__first" not in p.name
    ]
    if args.report:
        dev = [metrics_for_file(p, load_golden("golden")) for p in files]
        test = [metrics_for_file(p, load_golden("golden_test")) for p in files]
        print(report_table(dev, test))
        return
    golden = load_golden("golden" if args.set == "dev" else "golden_test")
    print(f"golden set: {args.set} ({len(golden)} texts)\n")
    all_metrics = [metrics_for_file(p, golden) for p in files]
    print(summary_table(all_metrics))
    if len(files) == 1:
        print("\n" + field_table(all_metrics[0]))


if __name__ == "__main__":
    main()
