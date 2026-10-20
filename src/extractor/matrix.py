"""Run the whole matrix: every model x prompt version x sampling config.

    uv run python -m extractor.matrix                    # skips configurations that already have results
    uv run python -m extractor.matrix --models anthropic_haiku --force

Local (Ollama) configurations are slow: about 15-20 minutes each on a laptop.
"""

import argparse
import itertools

from extractor import run
from extractor.run import ROOT, load_config, output_path


def prompt_versions() -> list[str]:
    return sorted(p.stem for p in (ROOT / "prompts").glob("extract_v*.md"))


def planned_runs(
    models: list[str], prompts: list[str], samplings: list[str], force: bool = False
) -> list[tuple[str, str, str]]:
    """All (model, prompt, sampling) triples that still need a run."""
    triples = itertools.product(models, prompts, samplings)
    return [t for t in triples if force or not output_path(*t).exists()]


def split(value: str | None, default: list[str]) -> list[str]:
    return value.split(",") if value else default


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--models", default=None, help="comma-separated keys from models.yaml")
    parser.add_argument("--prompts", default=None, help="comma-separated prompt versions")
    parser.add_argument("--samplings", default=None, help="comma-separated keys from sampling.yaml")
    parser.add_argument("--force", action="store_true", help="rerun even if results exist")
    args = parser.parse_args(argv)

    models = split(args.models, list(load_config("models.yaml")))
    prompts = split(args.prompts, prompt_versions())
    samplings = split(args.samplings, list(load_config("sampling.yaml")))

    todo = planned_runs(models, prompts, samplings, args.force)
    total = len(models) * len(prompts) * len(samplings)
    print(
        f"{len(todo)} of {total} configurations to run ({total - len(todo)} already have results)"
    )
    for i, (model, prompt, sampling) in enumerate(todo, 1):
        print(f"\n=== [{i}/{len(todo)}] {model} / {prompt} / {sampling}")
        run.main(["--model", model, "--prompt", prompt, "--sampling", sampling])


if __name__ == "__main__":
    main()
