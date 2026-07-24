# Community domain and public-object contract

**Status:** frozen for Milestone 1 (Foundation)
**Issue:** [#9](https://github.com/lbliii/showrun/issues/9) · **Epic:** [#4](https://github.com/lbliii/showrun/issues/4)
**Last updated:** July 24, 2026

This document freezes the terminology, lifecycle, eligibility, versioning, and
authorization contract for the Community Hub *before* the rest of the schema and
UI grow on top of it. It is the stable reference; GitHub owns live execution
state. The Foundation slice that implements this contract lives in
`showrun/community.py`, `migrations/005_community_hub.sql`, and the community
routes in `showrun/routes.py`, with the privacy matrix proven in
`tests/test_community.py` and `tests/test_community_web.py`.

## 1. Terminology

| Term | Definition |
| --- | --- |
| **Profile** | The public identity of one creator (a user and their workspace). Has a stable, URL-facing `handle`. Visibility is `public` or `private`. |
| **Technique** | The *stable identity* for a demonstrated pattern. Exactly one technique per source lesson, so its URL (`/techniques/{slug}`) and future lineage never move. Carries lifecycle status, not teaching content. |
| **Technique version** | *Immutable* teaching metadata (problem, pattern, when-to-use, objective, limitations, summary, topics) linked to exactly one immutable Showrun release. Editing metadata creates a new version; existing versions never change. |
| **Release** | The pre-existing immutable `dvd/1` snapshot (`releases` table). A technique version is *evidence-backed* because it references a real release. |
| **Topic** | A governed discovery tag with a deterministic `key`. Many-to-many with techniques. |
| **Head version** | The version currently presented publicly for a technique: the highest version number whose backing release is public and active. |

Future community objects (question, answer, fork, reproduction, citation,
reputation event) are defined in the
[Community Hub plan](./community-hub-plan.md) and land in later milestones. This
contract fixes the identity/version/eligibility spine they will attach to.

### Stable identity vs immutable version

The single most important boundary:

- **Techniques are mutable pointers.** Their `status`, `title`, and topic set
  can change. Their `slug` and `id` are stable forever.
- **Technique versions are immutable facts.** `(technique_id, version)` and the
  `(release_id, teaching-metadata)` behind a version never change after
  insertion. A change produces `version + 1`.

Idempotency is enforced by a `content_hash` over `(release_id, problem, pattern,
use_when, objective, limitations, summary, sorted topics)`. Re-submitting
identical metadata for the same release returns the existing version; any change
creates a new one. `UNIQUE (technique_id, version)` and
`UNIQUE (technique_id, content_hash)` back this in the database.

## 2. Eligibility states

Two independent axes gate whether content is public.

**Technique lifecycle (`techniques.status`):**

| Status | Meaning |
| --- | --- |
| `published` | Discoverable when a public head version exists. |
| `unlisted` | Reachable by direct slug only; never discoverable, counted, or aggregated. |
| `disabled` | Absent from every public surface. Reversible. History retained. |

**Profile visibility (`profiles.visibility`):** `public` or `private`. A
`private` profile hides the creator and *all* their techniques from every
non-owner surface.

**Backing release:** a release is eligible to back a *public* technique version
only when `visibility = 'public'` and `disabled_at IS NULL`. Draft, unlisted,
and disabled/unpublished releases can never back public teaching content.

### The single public-eligibility predicate

Every public read reuses one predicate so the privacy boundary lives in exactly
one place — `public_eligibility_sql(discoverable=…)` in `showrun/community.py`.
A technique version is publicly eligible when **all** hold:

1. its backing release is public and active (`r.visibility = 'public' AND r.disabled_at IS NULL`);
2. its creator profile is public (`p.visibility = 'public'`);
3. its technique is not disabled (`t.status <> 'disabled'`); **and**
4. it is the head version (highest version with a public, active release).

Discovery/aggregate surfaces (feed, search, counts, topic pages) additionally
require `t.status = 'published'`, excluding unlisted techniques. Direct slug
access (`discoverable=False`) admits unlisted techniques but still enforces
1, 2, and 4.

## 3. Authorization matrix

Contexts: **anonymous**, **non-owner** (signed in, different workspace),
**owner** (technique's workspace), **moderator** (reserved for Milestone 3;
today only lifecycle transitions exist, reused by the owner).

| Surface | Anonymous | Non-owner | Owner |
| --- | --- | --- | --- |
| Discovery feed `/discover`, counts, topic pages, search | eligible + discoverable only | same | same (own drafts still excluded from the shared feed) |
| Technique page `/techniques/{slug}` — published | ✅ | ✅ | ✅ |
| Technique page — unlisted | ✅ (direct link) | ✅ (direct link) | ✅ |
| Technique page — disabled | ❌ 404 | ❌ 404 | ✅ (owner preview) |
| Technique page — backing release unpublished | ❌ 404 | ❌ 404 | ✅ (owner preview) |
| Creator profile `/creators/{handle}` — public | ✅ | ✅ | ✅ |
| Creator profile — private | ❌ 404 | ❌ 404 | ✅ |
| Publish / edit a technique version (`POST /techniques`) | ❌ redirect to login | ❌ 404 (not release owner) | ✅ |
| Change technique status / profile visibility | ❌ | ❌ | ✅ |

Only the release owner (the workspace that owns the backing lesson) can publish
or version a technique. Ownership is derived from the lesson's `workspace_id`,
consistent with the rest of Showrun.

## 4. State transitions

```
                     publish technique version (owner, public+active release)
draft lesson ──────────────────────────────────────────► technique: published
                                                          version: 1 (immutable)

edit teaching metadata (owner) ─────────► new immutable version N+1 (head moves)
resubmit identical metadata (owner) ────► no-op (idempotent, same version)

owner/moderator status change:
  published ⇄ unlisted ⇄ disabled     (reversible; never deletes versions)

backing release lifecycle (existing):
  release disabled_at set (unpublish) ─► technique loses public eligibility
                                         immediately; versions & history kept
  release re-published (disabled_at NULL) ─► eligibility restored
```

Key guarantees:

- **Unpublishing is immediate and reversible.** Setting `releases.disabled_at`
  removes every dependent technique version from public reads the moment it
  commits, because eligibility joins the release row live. Re-publishing
  restores it. No community rows are deleted.
- **History is never silently removed.** Disabling a technique or unpublishing a
  release retains all `technique_versions` and topic links. This is the same
  guarantee that later protects fork/attribution ancestry: lineage records use
  `ON DELETE RESTRICT`/retained rows, never destructive cascades on
  moderation or visibility changes.

## 5. Privacy matrix (test-ready)

The following table is written to be parameterized directly into tests. Each row
is "for this content state, this surface must yield this result." It is realized
by `tests/test_community.py` (store) and `tests/test_community_web.py` (HTTP).

| Content state | Direct read | Discovery feed | Count / topic aggregate | Profile listing | Search |
| --- | --- | --- | --- | --- | --- |
| published, public profile, public+active release | visible | listed | counted | listed | matchable |
| unlisted technique | visible (direct) | absent | not counted | absent (non-owner) | absent |
| disabled technique | 404 (non-owner) | absent | not counted | absent (non-owner) | absent |
| release unpublished | 404 (non-owner) | absent | not counted | absent (non-owner) | absent |
| private profile | 404 (non-owner) | absent | not counted | 404 (non-owner) | absent |
| non-existent slug/handle | 404 / empty | n/a | 0 | 404 / empty | empty |

Invariants asserted across the matrix:

- Private and unlisted records never influence public counts or ranking.
- Every public community query reuses `public_eligibility_sql`; there is no
  second, drifting definition of "public."
- Front-end hiding is never authorization — the store returns `None`/empty for
  ineligible reads, so enumeration and direct-URL access are resisted at the
  data layer.
- Owner, non-owner, anonymous, and (reserved) moderator contexts are all
  covered.

## 6. Non-goals for this contract

- Migrations, templates, or ranking beyond what Foundation needs (owned by the
  implementation issues).
- Questions, answers, forks, reproductions, citations, reputation, moderation
  queues, organizations, or SSO (later milestones).
- Personalized or machine-learned ranking.
