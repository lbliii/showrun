# Discovery ranking

**Issue:** [#37](https://github.com/lbliii/showrun/issues/37) · **Epic:** [#5](https://github.com/lbliii/showrun/issues/5)

The Showrun discovery feed (`/discover`) is **deterministic, explainable, and
non-personalized**. Identical data always produces identical ordering, and each
result can explain why it ranked where it did. There is no machine-learned or
per-viewer recommendation.

## Inputs

Only publicly eligible, discoverable techniques enter ranking — the feed reuses
`public_eligibility_sql(discoverable=True)`, so private, unlisted, disabled, and
unpublished content is never ranked or counted.

## Score

For each eligible technique (its public head version):

```
score = 5 · reproductions        (demonstrated reuse — strongest)
      + 4 · citations            (external/collection references)
      + 1 · (completion_quality // 10)   (0–10 points from 0–100% completion)
```

- `reproductions` and `citations` are **0 until #19/#20 land**. The weights are
  already in place, so those features change ranking without a formula rewrite.
- `completion_quality` is the completion rate (`playback.completed / playback.started`,
  capped at 100%) of the technique's backing release.

## Ordering

Results are ordered by:

1. **score** descending,
2. **recency** (`created_at`) descending — newer wins ties,
3. **id** ascending — a final stable tiebreak.

The sort is stable and uses only stored values, so it is identical on SQLite and
PostgreSQL and across runs.

## Creator diversity cap

No single creator may occupy more than **2** slots before other creators appear.
A creator's third-and-later results are deferred below everyone else's first two,
so a prolific creator cannot fill the first page by volume alone. The deferral is
deterministic (it preserves the score order within the deferred set).

## Explainability

Every result carries a plain-language explanation (e.g. *"Ranked by 40%
completion, recency"*) derived from its own score components — surfaced in the UI
and available on `RankedTechnique.explanation`.

## Non-goals

- Personalized or machine-learned ranking.
- Attention-only signals (views, followers) as primary authority — they remain
  visible analytics but do not drive ranking.
