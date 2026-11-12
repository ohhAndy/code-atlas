
## Min-max score fusion (parked 2026-11-12, Phase 3)

Rescale BM25 and cosine scores to [0, 1] per query and add them, as an alternative to RRF.
Why it might help: it keeps the size of score gaps, which RRF discards, so a query where
one method is very confident would count more. Cost: about one session, plus a weight to
tune on 30 dev queries. Risk: one outlier score compresses the rest towards 0. The plan
lists it as optional; RRF needs no calibration. See ADR 007.

## Query cleanup for lexical search (parked 2026-11-11, Phase 2)

Strip pasted code, REPL output and tracebacks from the issue text, or weight the title
higher, before BM25 scores it. Why: query noise was the main cause in 5 of 13 BM25 dev
misses (see the Phase 2 failure analysis in `log.md`). Cost: about one session to build,
plus a new dev run and a re-check of `k1` / `b`; it is a new method (`bm25-clean`), not a
change to `bm25`. Risk: the pasted code is also where cat-1 queries carry their useful
paths and identifiers, so stripping it can hurt as much as it helps.
