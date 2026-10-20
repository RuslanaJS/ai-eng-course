"""Quick check: run one text through the provider and print the result.

uv run python -m extractor.smoke 005 [model_key]   # model_key from configs/models.yaml
"""

import json
import sys
from pathlib import Path

from extractor.prompts import load_prompt
from extractor.run import PROVIDERS, load_config

TEXTS = Path(__file__).resolve().parents[2] / "data" / "texts"


def main() -> None:
    text_id = sys.argv[1] if len(sys.argv) > 1 else "005"
    text = (TEXTS / f"{text_id}.txt").read_text(encoding="utf-8")
    cfg = load_config("models.yaml")[sys.argv[2] if len(sys.argv) > 2 else "anthropic_haiku"]
    args = {"model": cfg["model"]}
    if "num_ctx" in cfg:
        args["num_ctx"] = cfg["num_ctx"]
    provider = PROVIDERS[cfg["provider"]](**args)
    result = provider.extract(text, load_prompt("extract_v1"), {"temperature": 0})
    print(
        f"model={result.model} valid={result.valid} latency={result.latency_s:.1f}s "
        f"tokens in/out={result.input_tokens}/{result.output_tokens}"
    )
    if result.error:
        print("error:", result.error)
    if result.record:
        print(json.dumps(result.record.model_dump(mode="json"), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
