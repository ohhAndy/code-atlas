# ADR 006: Embedding model

**Status:** Accepted (the candidates and the selection rule; the chosen model is filled
in under Outcome after the two dev runs)
**Date:** 2026-11-11

## Context
BM25 fails when the issue and the code use different words. Three of the 13 Phase 2 dev
misses were vocabulary mismatch: the issue says "templates", "changes", "restart" and the
code says `template`, `changed`, `autoreload`; or the issue writes `**` or `C[i, 0]` and
the code is `_eval_power` or `_entry`. Semantic search embeds the query and each chunk as
vectors and ranks chunks by cosine similarity, so it can match meaning without shared
tokens.

Nothing is trained in this project. The choice is which pretrained model turns text into
vectors. It decides retrieval quality, and also:

- **Cost and speed.** Every chunk of every snapshot is embedded once (cached by chunk text
  and model id). One snapshot per repo is about 44k chunks; with changes across commits
  the whole subset is roughly 10 to 20 million tokens (estimate, not measured).
- **Reproducibility.** Success criterion 1 is one command from a clean clone. A model
  behind an API needs a key and money, and the provider can retire it.
- **Input limit.** A model reads at most N tokens per input. Phase 1 left the rule for
  oversized chunks to this ADR.

Evaluation constraint: dev has 30 queries. Each candidate tried on dev is another chance
to pick a winner by noise, so the plan allows at most two.

## Options considered

| Model | Kind | Trained for code | Input limit | Cost | Notes |
|---|---|---|---|---|---|
| **Qwen3-Embedding-0.6B** | local, open weights | text + code | 32k | free | runs on a 24 GB laptop; loads with sentence-transformers |
| Qwen3-Embedding-8B | local, open weights | text + code | 32k | free | about 16 GB of weights at half precision; too tight on 24 GB |
| voyage-4-nano | local, open weights (Apache 2.0) | general | 32k | free | loading runs the repo's own Python code (`trust_remote_code`) |
| **voyage-code-4** | API | code | 32k | about $0.12 / M tokens | released 2026-08 |
| Cohere Embed v4 | API | general | 128k | about $0.12 / M tokens (third-party listing) | |
| OpenAI text-embedding-3 | API | general | 8k | | |

Prices, limits and release dates are from documentation and third-party listings checked
on 2026-11-11, not measured. Published code-retrieval scores were not used to choose:
they are mostly reported by the vendors themselves, on different benchmarks (CoIR, CoREB,
custom sets), so they cannot be compared with each other. The 30 dev queries are the
test that matters for this task.

## Decision

### Candidates
1. **Qwen3-Embedding-0.6B (local).** Free, the weights never change, and it reproduces
   from a clean clone. Trained on code as well as text. The 0.6B size fits the
   hardware; 8B does not. Preferred over voyage-4-nano, the other free local option,
   because Qwen loads without running third-party code and its training includes code.
2. **voyage-code-4 (API).** Trained specifically for code retrieval, and cheap enough
   that embedding the whole subset costs a few dollars (estimate). Preferred over Cohere
   and OpenAI because both candidates would otherwise be general models, and the pair
   would only compare local vs API.

The model version (Hugging Face revision for Qwen, model name for Voyage) is pinned in
code and written into every results file.

### Selection rule (fixed before any embedding run)
- Dev split only, one run per candidate. Metric: function-level MRR@10, the same as the
  BM25 `k1` / `b` tuning.
- **Use Qwen3-Embedding-0.6B unless voyage-code-4 beats it by 0.02 MRR@10 or more.** Why
  the default favors the local model: it reproduces from a clean clone with no key or
  cost and cannot be retired by a provider; on 30 queries a smaller gap cannot be told
  apart from noise (the same margin as Phase 2).
- Both candidates get the same chunks, the same embedded text and the same k.
- Each model's query format is set from its documentation before the run and not changed
  after seeing results: Voyage's `input_type` of `query` vs `document`; Qwen's
  `Instruct: <task>\nQuery:` prefix, with the task written for this benchmark ("Given a
  GitHub issue describing a bug, retrieve the Python code that must be changed to fix
  it") instead of the shipped web-search default, as Qwen's docs recommend. Both models embed a query differently from a document, and embedding a
  query as a document lowers quality without any error.
- The rule, the metric and the candidates do not change after results are seen. The
  losing model's dev numbers stay in the log. Only the chosen model runs on test.

### Embedded text
Path + qualified name + chunk text, the same text BM25 indexes. Why: a difference between
semantic search and BM25 then comes from the method, not from different input.

### Chunks over the input limit
Both candidates accept about 32k tokens, so truncation is expected to be rare. Before the
dev runs, count the chunks over the limit in each model's tokenizer. If the count is
small, truncate at the limit and record the count. Splitting into windows is considered
only if the count is not small. Windows cost more vectors, and a chunk scored by its best
window is favored for being long (more windows, more chances to score high), the bias
BM25's `b` corrects for.

## Consequences
- The comparison measures local vs API **and** general-plus-code vs code-only training at
  once. With two models these effects cannot be separated: if voyage-code-4 wins, this
  setup cannot say which of the two caused it.
- Qwen gets a task-specific query instruction and Voyage cannot (its API takes only an
  input type). Each model is used the way its own docs recommend; the comparison is
  "each model used as documented", not "identical inputs down to the prompt".
- If voyage-code-4 is chosen, reproducing the results needs a Voyage API key and a few
  dollars. The embedding cache makes repeat runs free, but the cache is not in git.
- A large input limit removes truncation, not the real question: whether one vector for a
  300-line function represents a bug buried in it. Only the dev results and a failure
  analysis can answer that.
- Changing the model, its version, the query format or the embedded text invalidates every
  cached embedding and every semantic result; each change is a new method with its own
  logged runs.
- Published leaderboard scores play no part in the decision, so a model that ranks lower
  on a leaderboard can still be chosen if it is better on dev.

## Outcome
*To be filled after the two dev runs: MRR@10 for each candidate, the gap, and the model
chosen by the rule.*
