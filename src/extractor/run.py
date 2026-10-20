"""Run one model + prompt version + sampling config over every text and save JSONL results.

    uv run python -m extractor.run                       # defaults: anthropic_haiku, extract_v2, t0
    uv run python -m extractor.run --sampling t07 --limit 5

Each output line logs the model, prompt version and sampling parameters next to the result.
"""

import argparse
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from extractor.prompts import load_prompt
from extractor.providers.anthropic_provider import AnthropicProvider
from extractor.providers.base import Provider
from extractor.providers.ollama_provider import OllamaProvider
from extractor.repair import extract_with_repair

ROOT = Path(__file__).resolve().parents[2]
PROVIDERS: dict[str, Callable[..., Provider]] = {
    "anthropic": AnthropicProvider,
    "ollama": OllamaProvider,
}


def load_config(name: str) -> dict[str, Any]:
    return yaml.safe_load((ROOT / "configs" / name).read_text(encoding="utf-8"))


def read_texts(limit: int | None = None, ids: list[str] | None = None) -> list[tuple[str, str]]:
    """Return (id, text) for data/texts/*.txt in id order, optionally only some ids."""
    files = sorted((ROOT / "data" / "texts").glob("*.txt"))
    texts = [(f.stem, f.read_text(encoding="utf-8")) for f in files]
    if ids:
        texts = [t for t in texts if t[0] in ids]
    return texts[:limit] if limit else texts


def output_path(model: str, prompt: str, sampling: str, suffix: str = "") -> Path:
    """results/<model>__<prompt>__<sampling>[suffix].jsonl, one file per configuration."""
    return ROOT / "results" / f"{model}__{prompt}__{sampling}{suffix}.jsonl"


def merge_rows(existing: list[dict[str, Any]], new: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Replace rows with the same id, add the rest, keep id order."""
    by_id = {r["id"]: r for r in existing}
    by_id.update({r["id"]: r for r in new})
    return [by_id[i] for i in sorted(by_id)]


def cost_usd(row: dict[str, Any], price_per_mtok: dict[str, float]) -> float:
    tokens_in, tokens_out = row.get("input_tokens") or 0, row.get("output_tokens") or 0
    return (tokens_in * price_per_mtok["input"] + tokens_out * price_per_mtok["output"]) / 1e6


def run_corpus(
    provider: Provider,
    prompt: str,
    params: dict[str, Any],
    texts: list[tuple[str, str]],
    meta: dict[str, Any],
    warmup: bool = True,
    repair: bool = True,
    log: Callable[[str], None] = print,
) -> list[dict[str, Any]]:
    """Extract every text; return one JSON-serializable row per text.

    The warm-up call is not saved: the first structured-output request compiles the schema
    and is much slower (about 20 s vs 3 s), which would distort the latency percentiles.
    """
    if warmup and texts:
        log("warm-up call (not saved)")
        provider.extract(texts[0][1], prompt, params)
    rows = []
    for text_id, text in texts:
        result = extract_with_repair(provider, text, prompt, params, repair=repair)
        row = {
            "id": text_id,
            **meta,
            "params": result.params,
            "valid": result.valid,
            "status": result.status,
            "first_error": result.first_error,
            "attempts": result.attempts,
            "error": result.error,
            "latency_s": round(result.latency_s, 3),
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "record": result.record.model_dump(mode="json") if result.record else None,
            "raw": result.raw,
            "extra": result.extra,
        }
        rows.append(row)
        note = "" if result.status == "ok" else f" [{result.status}]"
        if not result.valid:
            note += f" ({(result.error or '')[:60]})"
        log(f"{text_id}: {'ok' if result.valid else 'INVALID'}{note} {result.latency_s:.1f}s")
    return rows


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--model", default="anthropic_haiku", help="key in configs/models.yaml")
    parser.add_argument("--prompt", default="extract_v2", help="file name in prompts/ without .md")
    parser.add_argument("--sampling", default="t0", help="key in configs/sampling.yaml")
    parser.add_argument("--limit", type=int, default=None, help="only the first N texts")
    parser.add_argument(
        "--ids", default=None, help="comma-separated text ids; merged into the run file"
    )
    parser.add_argument("--no-warmup", action="store_true")
    parser.add_argument("--no-repair", action="store_true", help="skip the correction attempt")
    args = parser.parse_args(argv)

    model_cfg = load_config("models.yaml")[args.model]
    params = load_config("sampling.yaml")[args.sampling]
    provider_args = {"model": model_cfg["model"]}
    for cfg_key, arg in (
        ("timeout_s", "timeout"),
        ("max_retries", "max_retries"),
        ("num_ctx", "num_ctx"),
    ):
        if cfg_key in model_cfg:
            provider_args[arg] = model_cfg[cfg_key]
    provider = PROVIDERS[model_cfg["provider"]](**provider_args)
    meta = {
        "model_key": args.model,
        "model": model_cfg["model"],
        "prompt_version": args.prompt,
        "sampling": args.sampling,
    }
    rows = run_corpus(
        provider,
        load_prompt(args.prompt),
        params,
        read_texts(args.limit, args.ids.split(",") if args.ids else None),
        meta,
        warmup=not args.no_warmup,
        repair=not args.no_repair,
    )

    # --limit runs get their own file so they never overwrite a full run;
    # --ids runs are merged into the normal file (replace or add those ids only)
    suffix = f"__first{args.limit}" if args.limit and not args.ids else ""
    out = output_path(args.model, args.prompt, args.sampling, suffix)
    out.parent.mkdir(exist_ok=True)
    if args.ids and out.exists():
        rows = merge_rows([json.loads(line) for line in out.read_text().splitlines() if line], rows)
    out.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
    )

    valid = sum(r["valid"] for r in rows)
    cost = sum(cost_usd(r, model_cfg["price_per_mtok"]) for r in rows)
    fixed = sum(r.get("status") == "fixed" for r in rows)
    print(
        f"\n{valid}/{len(rows)} valid ({fixed} after correction), cost ${cost:.3f}, saved to {out.relative_to(ROOT)}"
    )


if __name__ == "__main__":
    main()
