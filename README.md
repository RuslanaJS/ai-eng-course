# PropDoc: questions about buying an apartment in Poland, answered from documents

PropDoc answers a buyer's questions (can a foreigner buy, how payments to a developer are protected, what
prices do) from Polish laws and NBP reports. Every claim cites a document and its part; when the documents
do not say, it answers "I don't know". Part of the AI Engineering course project:

- **HW2 (this stage): RAG over own data, with evals.** Results in [`REPORT_HW2.md`](REPORT_HW2.md).
- **HW1: structured extraction** of one apartment record from dirty texts. Results in
  [`REPORT_HW1.md`](REPORT_HW1.md), how to run it [below](#hw1-structured-extraction).

## Run

```bash
cp .env.example .env     # add ANTHROPIC_API_KEY and GEMINI_API_KEY
make run                 # the bot on the 23 test questions the committed corpus can answer, then metrics
                         # (~3 min the first time, ~0.1 USD)
make ask Q="Czy cudzoziemiec potrzebuje zezwolenia na zakup mieszkania?"   # one question
make test                # unit tests, no network
```

Needs [uv](https://docs.astral.sh/uv/). The first run downloads the reranker model (about 0.6 GB) and
embeds the 522 law chunks with Gemini; both are cached in `data/cache/`, later runs reuse them.

**What is and is not in the repository.** The laws (8 documents, open: Polish law excludes legal acts
from copyright) are committed as chunks in `data/processed/chunks.jsonl`. The NBP and market reports (22
documents) do not allow redistribution, so only their list with URLs and checksums is committed
(`data/manifest.csv`); `make fetch` and `make ingest` rebuild them locally. Without them, `make run`
and CI use the law questions only; the full numbers in `REPORT_HW2.md` were measured locally with the reports.

Other commands:

| Command | What it does |
|---|---|
| `make eval-gate` | `make run` compared with `evals/baseline_open.json`, exit 1 if worse (what CI runs) |
| `make eval-answers` | all 29 questions, 3 runs each (needs the local reports, ~0.3 USD) |
| `make eval-retrieval` | recall@5 and MRR of every search configuration |
| `make judge`, `make calibrate` | LLM judge on the last full run, and its agreement with the manual labels |
| `make check-testset` | test set lint without a model: ids, documents, every quote present in its document |
| `make search Q="..."` | the top chunks for a query |
| `make fetch`, `make ingest`, `make check-ingest`, `make embed` | build the corpus from `data/manifest.csv` |

## How it works

```
data/manifest.csv --fetch--> data/raw/ --ingest (clean, chunk, versions)--> data/processed/chunks*.jsonl
                                                                                     |
question --> hybrid search: BM25 + Gemini vectors (RRF) --> reranker --> top 5 chunks
         --> context up to 2500 tokens, <source n=...> tags --> Haiku 4.5 --> {found, answer, sources}
         --> citation check --> answer with [n] citations, or "I don't know"
```

All code is one package, `src/propdoc/`, one folder per component:

- `ingest/`: fetch, load (HTML, PDF), clean, chunk, deduplicate and mark versions.
- `retrieval/`: embeddings (Gemini, local bge-m3), BM25 and vector indexes in Qdrant (in memory), hybrid
  search, reranking, metadata filters.
- `answering/`: context within the token budget, the answer with citations, `make ask`.
- `evaluation/`: retrieval metrics, deterministic scorers for answers, the LLM judge, the CI gate.
- `extraction/`: the HW1 record extractor.

Prompts are in `prompts/` (append-only versions, changes in `prompts/CHANGELOG.md`); the test sets,
manual labels, baselines and measured runs in `evals/`.

### Chunking

Structure-aware: a chunk never crosses a section heading; a law article, a table or a figure stays whole
unless it is longer than 700 tokens (then it is split at sentence boundaries); paragraphs are packed up to
450 tokens. The section, article or page and the document version go into the chunk's metadata, so a
citation can name them.

Why: buyers' questions are answered by one article or one table, and the citation must name it. Compared
with fixed-size chunks of the same size (450 tokens, 15% overlap) on five documents, fixed chunks start
mid-sentence 84-98% of the time and cut 53 of 88 articles and tables in the buyers act (structural: 22,
only the over-long ones). On retrieval, fixed chunks drop recall@5 from 1.00 to 0.75 and MRR from 0.88 to
0.53 with the same search. Details in [`REPORT_HW2.md`](REPORT_HW2.md#corpus-and-chunking).

Versions: older consolidated texts of a law are `superseded`, a law that enters into force later is
`upcoming`, an annual report more than a year older than the newest one is `outdated`. Search uses
`current` and `upcoming` only, unless a question asks about an older period.

### Evals and CI

- Test set: `evals/questions.json`, 29 reviewed questions including 4 without an answer and traps (similar
  documents, older versions, cross-language, two documents).
- Deterministic scorers: key facts, recall@5, quote in context, cited, abstain, false abstain; pass@1 over
  repeated runs, cost per 1000 questions, latency p50/p95.
- LLM judge (Opus 5.5) for correctness and groundedness, calibrated on 15 manual labels
  (`evals/labels.json`), 0.87 agreement on both.
- CI (`.github/workflows/`): `ci.yml` runs lint, unit tests and the test set lint on every pull request;
  `evals.yml` runs the bot on a pull request that changes the prompt, search, answering or test set, and
  fails when it falls below `evals/baseline_open.json` by more than 0.05 or a passing question regresses.
  It needs the repository secrets `ANTHROPIC_API_KEY` and `GEMINI_API_KEY` and skips without them.

## Results

| | recall@5 | MRR | pass@1 | False abstain | Judge: correct | $ / 1000 questions | p50 |
|---|---|---|---|---|---|---|---|
| hybrid + rerank, Haiku 4.5, full corpus | 1.00 | 0.88 | 0.83 | 0.04 | 25 of 29 | 3.41 | 2.8 s |

Error analysis, judge calibration and limits are in [`REPORT_HW2.md`](REPORT_HW2.md).

## HW1: structured extraction

Extracts one apartment record from dirty Polish real-estate texts with Haiku 4.5 or the local
`qwen2.5:3b-instruct` (Ollama). The source texts are not in the repository (their terms do not allow
redistribution); the labeled sets in `data/golden*` and the URLs in `data/sources.csv` are.

```bash
make run-hw1             # Haiku, prompt v2, T=0 on all texts, then metrics (~2 min, ~0.2 USD, needs data/texts/)
make run-all             # every model x prompt x sampling, skips results that already exist
make metrics             # metrics table from results/
make check-labels        # every labeled value must be findable in its source text
```

Best configuration: Haiku 4.5 with prompt v2 at T=0, 100% field accuracy on both labeled sets, 5.44 USD
per 1000 documents. The full comparison is in [`REPORT_HW1.md`](REPORT_HW1.md).

## Working with Claude Code

`CLAUDE.md` holds the project rules and `.claude/skills/` three task skills (`run-experiment`,
`prompt-iteration`, `release-check`); both are committed so every clone has them.
