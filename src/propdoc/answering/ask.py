"""Ask one question: python -m propdoc.answering.ask "Czy cudzoziemiec potrzebuje zezwolenia?" """

import argparse
import json

from ..retrieval.search import make_configs
from ..retrieval.store import load_chunks
from .answer import CONFIG, MODEL, PROMPT, Answerer, cost_usd
from .context import DEFAULT_BUDGET


def show(result):
    print(result["answer"] or f"[{result['status']}] {result.get('error', '')}")
    if result["citations"]:
        print("\nSources:")
    for c in result["citations"]:
        page = f", p. {c['page']}" if c["page"] else ""
        where = " | ".join(x for x in (c["section"], c["part"]) if x) or "-"
        print(f"  [{c['n']}] {c['title']} | {where}{page} ({c['version']}, {c['status']})")
    if result["invalid"]:
        print(f"\nInvalid source numbers: {result['invalid']}")
    print(f"\nstatus={result['status']} found={result['found']} chunks used {result['used']} of "
          f"{result['retrieved']} ({result['context_tokens']} tokens, dropped {result['dropped']}) "
          f"{result.get('latency_s', 0):.1f}s ${cost_usd(result):.4f}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question")
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--prompt", default=PROMPT)
    parser.add_argument("--budget", type=int, default=DEFAULT_BUDGET)
    parser.add_argument("--config", default=CONFIG)
    parser.add_argument("--history", action="store_true", help="also search superseded versions")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    search = make_configs(load_chunks(), [args.config.split("[")[1].rstrip("]")])[args.config]
    result = Answerer(search, args.model, args.prompt, args.budget).ask(args.question, args.history)
    print(json.dumps(result, ensure_ascii=False, indent=1)) if args.json else show(result)
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
