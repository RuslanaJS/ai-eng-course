# Report: RAG over Polish real-estate documents, with evals (HW2)

PropDoc answers a buyer's questions about Polish housing (can a foreigner buy, how payments to a developer
are protected, what prices do) from laws and NBP reports, with a citation for every claim and "I don't
know" when the documents do not say. The HW1 report (structured extraction) is in
[`REPORT_HW1.md`](REPORT_HW1.md).

All numbers below come from files in `evals/runs/` and `data/processed/`; the commands that produce them
are listed in [Reproduce](#reproduce).

## Summary

- **Corpus:** 31 documents (8 laws, 22 NBP and market reports, 1 guide; 25 Polish, 6 English), 4204
  chunks. The laws (522 chunks) are in the repository; the reports stay local because their terms do not
  allow redistribution.
- **Retrieval:** hybrid search (BM25 + Gemini embeddings, RRF) with a cross-encoder reranker finds the
  labeled chunk in the top 5 for 16 of 16 questions (recall@5 1.00, MRR 0.88). Without the reranker MRR
  falls to 0.51; with fixed-size chunks recall@5 falls to 0.75.
- **Answers (Haiku 4.5, 29 questions x 3 runs):** pass@1 0.83, the same answers in every run (no flaky
  questions), no invented answer to the 4 questions without an answer, a false "I don't know" on 1 of 25
  answerable questions. 3.41 USD per 1000 questions, model latency p50 2.8 s, p95 3.8 s.
- **LLM judge (Opus 5.5):** agrees with my 15 manual labels in 13 of 15 cases on correctness and on
  groundedness. It caught a wrong answer (q01) that the string scorers passed.
- **CI:** every pull request lints the test set without a model; a pull request that changes the prompt,
  search, answering or test set also runs the bot on the open corpus and fails when it is worse than
  `evals/baseline_open.json`.

## Corpus and chunking

| Kind | Documents | In the repo | Traps |
|---|---|---|---|
| Laws (foreigners act, buyers act, notary law, ...) via the Sejm ELI API | 8 | yes, `data/processed/chunks.jsonl` | older consolidated texts of the same act (superseded) |
| NBP quarterly and annual reports, market reports | 22 | no, `scripts/fetch_corpus.py` + `data/manifest.csv` | quarters of the same series, an annual report older than a year (outdated) |
| Guide | 1 | no | |

Every chunk carries `doc_id`, title, type, language, version, status (`current`, `superseded`,
`upcoming`, `outdated`), section, article or page and source URL, so a citation names the document and its
part. Search uses only `current` and `upcoming` documents unless a question asks about an older period.

**Structural chunking** (`src/propdoc/ingest/chunk.py`): a chunk never crosses a section heading; an
article, table or figure is one chunk unless it is longer than 700 tokens; paragraphs are packed up to 450
tokens. **Fixed-size** chunks of the same size (450 tokens, 15% overlap) are the comparison. On five
documents (`data/processed/chunking_comparison.json`):

| Document | Strategy | Chunks | Avg tokens | Start mid-sentence | Articles/tables cut | Mixed sections |
|---|---|---|---|---|---|---|
| D001 foreigners act | structural | 30 | 241 | 0% | 5 of 20 | 0% |
| | fixed | 19 | 445 | 84% | 10 of 20 | 0% |
| D007 buyers act | structural | 151 | 325 | 0% | 22 of 88 | 0% |
| | fixed | 129 | 448 | 98% | 53 of 88 | 9% |
| D009 NBP II 2026 | structural | 153 | 312 | 0% | 6 of 29 | 0% |
| | fixed | 124 | 450 | 97% | 12 of 29 | 7% |

The structural cuts are articles longer than 700 tokens, split at sentence boundaries with the article
number repeated. Fixed-size chunks cut every second article in the buyers act and start almost always in
the middle of a sentence, so a retrieved chunk often lacks the article number it would be cited by. The
retrieval numbers below confirm it.

## Retrieval

16 questions with a labeled quote (`evals/retrieval_questions.json`); a hit is a retrieved chunk that
contains the quote. Embeddings: Gemini `gemini-embedding-2` (768 dimensions) and the local `bge-m3`
(Ollama); reranker `BAAI/bge-reranker-v2-m3` (int8, CPU).

| Configuration | Chunks | recall@5 | MRR | ms per query | Missed |
|---|---|---|---|---|---|
| BM25 | structural | 0.50 | 0.25 | 5 | 8 |
| vector, Gemini | structural | 0.94 | 0.67 | 965 | r05 |
| hybrid, Gemini | structural | 0.94 | 0.51 | 963 | r12 |
| **hybrid + rerank, Gemini** | structural | **1.00** | **0.88** | 4751 | - |
| vector, bge-m3 | structural | 0.81 | 0.64 | 555 | r05, r07, r16 |
| hybrid + rerank, bge-m3 | structural | 1.00 | 0.83 | 4616 | - |
| hybrid + rerank, Gemini | fixed | 0.75 | 0.53 | 5509 | r01, r05, r12, r14 |

- BM25 alone misses half: questions are phrased as a buyer would ask, laws use legal terms, and Polish
  inflection defeats exact matching (stemming to 6 characters did not help).
- Hybrid raises recall but lowers MRR: BM25 pushes keyword-heavy chunks above the right one. The reranker
  fixes the order (MRR 0.51 to 0.88).
- The local bge-m3 is close to Gemini after reranking (MRR 0.83 vs 0.88), a free option.
- The reranker costs about 4 seconds per query on CPU, most of the search time.
- Caveat: the fixed-size run was made before the `outdated` status existed, so on fixed chunks old reports
  could still compete; the gap is large enough that this does not change the conclusion.

Chosen configuration: hybrid + rerank with Gemini embeddings on structural chunks.

## Answers

`src/propdoc/answering/`: the top 5 chunks go into the prompt in rank order until a budget of 2500 tokens
is used up (the first chunk that does not fit stops the list), each in a `<source n=...>` tag with its
title, part and version. The model (Haiku 4.5, T=0, prompt `prompts/rag_answer_v1.md`) returns structured
JSON `{found, answer, sources}` and answers in the language of the question. A citation number that was
not in the context makes the answer `bad_citation`; `found=false` is "I don't know".

**Test set** (`evals/questions.json`, 29 questions, reviewed by me): facts (10), trends (4), no answer
(4), similar documents (2), exceptions (2), an older period that must not be answered from the newest
report (2), cross-language (1: English question, Polish law), two documents in one answer (1), comparison
(1), a law that enters into force later (1), residence (1). Each answerable question has the documents, the
quotes that hold the answer, key facts and a reference answer.

**Deterministic scorers** (`src/propdoc/evaluation/scorers.py`), per answer: key facts present (every
group of `must` has a match), recall@5 (a labeled quote among the retrieved chunks), the quote reached the
context, the answer cites a chunk with the quote, abstained on a question without an answer, false
abstain on one with an answer. An answer passes when all of these hold.

| Run | Questions | pass@1 | Facts | recall@5 | In context | Cited | Abstain (no-answer) | False abstain | p50 / p95 | $ per 1000 |
|---|---|---|---|---|---|---|---|---|---|---|
| full corpus, 3 runs | 29 | 0.83 | 0.84 | 1.00 | 1.00 | 0.88 | 4/4 | 0.04 | 2.8 / 3.8 s | 3.41 |
| open corpus (laws, CI) | 23 | 0.87 | 0.84 | 0.95 | 0.95 | 0.89 | 4/4 | 0.11 | 2.3 / 3.7 s | 3.22 |

- All three runs gave the same verdicts: pass@1 equals "passed every time", there are no flaky
  questions at T=0. The failures are systematic, not noise.
- Latency is the model call only. Search adds about 5 s per question (query embedding about 1 s, the
  reranker on CPU about 4 s; see the retrieval table).
- Cost is Haiku 4.5 at 1 / 5 USD per million input / output tokens; query embeddings with Gemini are not
  counted (fractions of a cent per 1000 queries).
- The open corpus has only laws, so the questions about reports are out of it; its baseline is what CI
  compares with.

## LLM judge and calibration

`src/propdoc/evaluation/judge.py`, Opus 5.5 (effort medium, structured output):

- **Correctness** (`prompts/judge_correct_v1.md`): does the answer agree with the reference answer.
- **Groundedness** (`prompts/judge_grounded_v2.md`): the answer is split into claims, and each claim is
  checked against the cited sources only. A repeat of the question is not checked; a direct necessary
  conclusion counts as supported; a link between two facts that the source does not make is not.

I labeled 15 answers by hand (`evals/labels.json`). The judge disagreed with me 8 times; I reviewed each
case and changed my label 4 times where the judge was right (q04, q12, q14 groundedness, q21
groundedness), and kept it 4 times (q21 and q23 correctness, q23 and q24 groundedness). Each change is
recorded in the `revised` field.

| Judge version | Correctness agreement | Groundedness agreement | False pass (judge says ok, I say no) | False fail |
|---|---|---|---|---|
| grounded v1, original labels | 0.80 | 0.40 | correct 1 of 2, grounded 0 | grounded 0.69 |
| **grounded v2, reviewed labels** | **0.87** | **0.87** | correct 1 of 2, grounded 0 | correct 0.08, grounded 0.18 |

- v1 was far too strict: it failed answers for adding a true detail from another sentence of the same
  source. v2 added the rules above.
- The judge is stricter than me rather than looser: it never passed an ungrounded answer.
- Limits: only 2 of the 15 labeled answers are wrong, so the false-pass rate on correctness rests on two
  cases; and v2 was written after seeing these 15 labels, so its agreement is optimistic. A new set of
  labels would be needed to measure it honestly.
- On the full run the judge marked 4 of 29 answers incorrect (q01, q02, q07, q23) at a cost of 0.53 USD.

## Error analysis

**q01: a wrong answer that the string scorers passed.** *"Can a foreigner on a temporary stay, or with no
stay in Poland, buy an apartment without a permit?"* Expected: yes, buying a self-contained apartment needs
no permit (Art. 8(1)(1) of the foreigners act), whatever the residence. The bot: "No ... the exception
requires the foreigner to have lived in Poland at least 5 years since a permanent residence permit". The
5-year condition is in the same article but belongs to a different point (Art. 8(1)(2), other real
estate). The answer contains the key phrase "bez zezwolenia" and cites the right chunk, so every string
check passed; the judge failed it on both correctness and groundedness. This is the case for having a
judge.

**q07: a false "I don't know".** *"Can an apartment in a border zone also be bought without a permit?"*
Expected: no, the exemptions do not apply in the border zone (Art. 8(3)). The chunk with ust. 3 was
retrieved and in the context, yet the model returned `found=false` in all three runs. The answer is a
negation of an exception two paragraphs away from the rule, and the prompt pushes hard toward abstaining
when unsure. A fix to try: a prompt rule that an exception to a rule in the sources is an answer.

**q13: the answer is right, the test set is too narrow.** *"What is the current trend of secondary-market
prices in the largest cities?"* The bot gave the NBP II 2026 figures (Warsaw +1.2% q/q, the 6-city group
-0.6% q/q, real prices falling) with citations. It failed only "cited": the one labeled quote ("ceny
ofertowe ... niewielki wzrost") is in a chunk the bot did not cite, while the chunks it cited say the same
thing in other words. The fix is in the test set: add the other chunks' quotes.

**q21 and q23: correct content, wrong framing, and a reference that is too strict.** q21 (a foreigner
from outside the EU buying a new apartment): the bot says "you need a permit, unless you buy a
self-contained apartment", which is literally true but answers the buyer's question backwards; the key fact
"no permit needed" is missing, and I marked it incorrect. q23 (prices in Q1 2026, an older quarter): the bot
used the right, older report (superseded status, retrieved because the question asks for that period) and
gave growth figures, while the reference says prices "remained stable". I accepted the answer as correct;
both are in the report. The key fact `stabiln` was too narrow.

**q22: a missing half of a comparison.** *"What is the difference between an open and a closed escrow
account?"* The bot explained the closed account correctly but said the open one lets the developer "use
the funds to finance the project", without the payouts in stages according to the schedule, which is the
actual difference. Facts failed on `schedule`; the judge passed it as correct. A borderline case where
string checks are stricter than the judge.

What the errors say: retrieval is not the bottleneck (recall@5 and "in context" are 1.00 on the full
corpus). The failures are in the step from context to answer (q01, q07, q21, q22) and in the test set
itself (q13, q23).

## CI

- `.github/workflows/ci.yml`, every push to `main` and every pull request, no keys: ruff, 137 unit tests,
  and `--lint` of the test set (unique ids, known documents, every quote present in its document's chunks;
  quotes from local-only reports are skipped).
- `.github/workflows/evals.yml`, on a pull request that changes the answer prompt, the answering, search
  or evaluation code, the test set, the baseline or the chunks, and by hand: runs the 23 open-corpus
  questions and compares with `evals/baseline_open.json`. It fails when a metric falls more than 0.05
  below the baseline (false abstain: rises more than 0.05), or when a question that passed in the baseline
  now fails. About 3 minutes and 0.1 USD; without the secrets it skips instead of failing. The first run
  passed on the pull request `feat/home_work_2` into `main`.

## Choices and what to improve

- Haiku 4.5 for answers: cheap (3.41 USD per 1000), fast, and its errors are reasoning errors that a
  larger model may reduce; it is the next experiment, at about 5 times the price.
- The judge is too expensive for every CI run (0.53 USD per full run) and runs locally (`make judge`).
- To improve, in order: a prompt v2 for the false abstain on exceptions (q07) and for answering the buyer's
  question directly (q21); a wider set of quotes and key facts for q13 and q23; more wrong answers in the
  manual labels to measure the judge's false passes; the reranker on GPU or a lighter one, which is most of
  the latency.

## Limitations

- 29 questions and one run of 3 repeats: one question is 0.03 of pass@1; differences under 0.05 are noise.
- The reports are not in the repository, so a fresh clone and CI see only the laws (23 questions).
- The labels, the reference answers and the test set were written by one person; the judge's v2 prompt was
  tuned on the same 15 labels it is measured on.
- The foreigners act in the ELI API is the 2017 consolidated text; a later amendment (Dz.U. 2026 poz. 1099)
  enters into force on 19.11.2026 and is handled as `upcoming`.

## Reproduce

```bash
make run              # the bot on the open corpus (laws), 23 questions, metrics (~3 min, ~0.1 USD)
make eval-gate        # the same, compared with evals/baseline_open.json, as CI does
make eval-retrieval   # recall@5 and MRR (needs the local reports for all 16 questions)
make eval-answers     # the full test set, 3 runs (needs the local reports, ~0.3 USD)
make judge            # LLM judge on the last full run (~0.5 USD)
make calibrate        # judge vs evals/labels.json
make check-testset    # test set lint, no model calls
```
