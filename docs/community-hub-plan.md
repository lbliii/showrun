# Showrun Community Hub plan

**Status:** approved product direction; implementation plan  
**Last updated:** July 24, 2026

## Product definition

Showrun Community Hub is a social knowledge network for agent craft.

Its public knowledge unit is not a raw chat, isolated prompt, or popularity
post. It is a demonstrated technique:

```text
task
  ↓
technique + observable run + evidence + outcome
  ↓
forks + reproductions + citations + attribution
```

The product should help someone answer three questions:

1. What technique should I use for this agent task?
2. Can I inspect a real run that demonstrates it?
3. Who created, adapted, and reproduced the technique?

The social layer turns Showrun from a replay utility into a durable body of
knowledge where creators receive credit for useful agent techniques.

## Product promise

> Learn agent craft from real runs. Show what works, preserve the evidence, and
> receive credit when others build on it.

## Community object model

Stack Overflow organizes knowledge around questions and textual answers.
Showrun organizes it around tasks and demonstrated answers:

| Community concept | Showrun object |
| --- | --- |
| Question | A concrete agent task or failure mode |
| Answer | A technique version backed by an immutable Showrun release |
| Source | The sanitized `dvd/1` artifact and its bounded evidence |
| Edit | A new immutable technique version |
| Fork | A private draft with permanent ancestry |
| Verification | A reproduction backed by another published release |
| Citation | A durable reference from a show, collection, or external document |
| Reputation | An append-only record of demonstrated reuse and contribution |

## Product principles

### Demonstration over assertion

A public technique must link to an immutable release. A creator can explain the
pattern, but the replay and evidence let the viewer inspect what happened.

### Attribution survives every fork

Forking creates a new private draft and a permanent link to the source technique
version. A descendant may earn credit for an adaptation without erasing the
original author.

### Reputation follows reuse, not attention

Verified reproductions, attributed forks, accepted demonstrated answers, and
citations are stronger signals than views or likes. Early versions should show
the underlying signals rather than manufacture one opaque ranking score.

### Private means absent

Private and unlisted content must never leak through discovery, counts, tags,
profiles, question answers, reputation, activity, or search. Community records
can reference only an access-compatible release.

### Observable evidence, not hidden reasoning

Showrun presents messages, tool calls, MCP traversal, sources, tests, files,
delegation, and outcomes. The social product must not encourage publishing
hidden chain-of-thought or claim access to private model reasoning.

### Deliberate publishing remains mandatory

Importing or forking creates a private draft. Public community actions begin
only after sanitization review and an explicit release.

## MVP user journeys

### Publish a technique

1. Import and direct a real agent session.
2. Review sanitization and publish an immutable release.
3. Add the technique card:
   - problem
   - pattern
   - when to use it
   - learning objective
   - topics
   - limitations
4. Publish a technique version linked to the release.
5. Receive a durable technique URL and public creator attribution.

### Learn a technique

1. Discover by topic, task, creator, or deterministic feed ranking.
2. Read the concise technique card.
3. Watch the directed run.
4. Expand evidence when more detail is needed.
5. Save the technique, follow the creator, or fork it into a private draft.

### Ask and answer

1. Ask a concrete task question.
2. Creators answer with published technique versions, not unsupported prose.
3. The asker can accept one demonstrated answer.
4. Future answers can improve or adapt the technique while retaining ancestry.

### Fork and reproduce

1. Fork a public technique version.
2. Showrun creates a private draft with the original attribution attached.
3. Adapt and run the technique with another agent, model, tool, or context.
4. Publish the new evidence.
5. Mark the result and limitations as a reproduction or adaptation.
6. Credit flows through the lineage to each contributor.

## MVP surfaces

- **Discover:** recent, reproduced, and useful techniques ranked by a
  transparent deterministic formula
- **Technique:** technique card, Showrun player, evidence, versions, ancestry,
  adaptations, and reproductions
- **Creator:** public craft profile, topic expertise, published techniques, and
  contribution signals
- **Questions:** task questions with demonstrated answers and accepted answers
- **Collections:** personal learning lists and curated public curricula
- **Moderation:** report flow, attribution disputes, reversible enforcement, and
  an admin queue

A personalized recommendation engine, direct messages, comments, and
notification infrastructure are not MVP requirements.

## Domain and persistence design

The current `users`, `workspaces`, `lessons`, `releases`, and `usage_events`
tables remain the product foundation. Community records layer on top of
immutable releases rather than replacing the artifact model.

| Record | Purpose |
| --- | --- |
| `profiles` | Public identity, handle, bio, and profile visibility |
| `techniques` | Stable identity, creator, slug, and lifecycle |
| `technique_versions` | Immutable teaching metadata linked to one immutable release |
| `topics` / `technique_topics` | Governed discovery taxonomy |
| `questions` | Concrete tasks or failure modes |
| `answers` | Question-to-technique-version relationship and acceptance |
| `technique_forks` | Permanent ancestry from child technique/draft to source version |
| `reproductions` | A source version, reproducing release, environment metadata, outcome, and limitations |
| `follows` | Creator-to-creator discovery preference |
| `collections` / `collection_items` | Personal or public learning lists |
| `reputation_events` | Append-only contribution ledger with unique source keys |
| `reports` / `moderation_actions` | Trust workflow and reversible enforcement |

### Versioning boundary

- `techniques` provide a stable URL and lineage identity.
- `technique_versions` are immutable after publication.
- Every technique version references exactly one active, compatible Showrun
  release.
- Editing teaching metadata creates a new version.
- Unpublishing or restricting the backing release removes the version from
  public surfaces without deleting its history.

### Reputation boundary

The ledger records attributable events. It should not initially collapse them
into one unexplained number.

Strong signals:

- verified or evidence-backed reproduction
- attributed fork that becomes a published technique
- accepted demonstrated answer
- external or collection citation

Supporting signals:

- lesson completion
- save to a collection
- useful moderation or annotation contribution
- cross-agent or cross-model reproduction

Attention-only signals such as views and follower count remain visible
analytics but do not independently establish authority.

## Application architecture

### Routes and hypermedia

Extend the current Chirp route module with bounded community services and
templates:

- `GET /discover`
- `GET /topics/{slug}`
- `GET /@{handle}`
- `GET /techniques/{slug}`
- `POST /techniques`
- `POST /techniques/{slug}/fork`
- `POST /techniques/{slug}/reproduce`
- `GET|POST /questions`
- `POST /questions/{id}/answers`
- `POST /questions/{id}/accept/{answer_id}`
- `POST /profiles/{handle}/follow`
- `GET|POST /collections`
- `POST /reports`

Mutations use Chirp form contracts, CSRF protection, explicit authorization, and
local hypermedia targets. Public read routes remain cacheable where safe.

### Store boundary

Keep SQL and transaction behavior inside `ShowrunStore` or focused community
stores with the same SQLite/PostgreSQL portability contract.

Critical transactions include:

- publishing a technique version with an eligible release
- accepting exactly one answer
- creating a fork and its ancestry record
- recording one reputation event per unique source action
- unpublishing content and removing it from every discovery surface
- applying and reversing moderation actions

### Search and ranking

MVP search uses PostgreSQL/SQLite-compatible normalized fields and topic joins.
The discovery feed is deterministic and explainable:

1. eligible public content only
2. recency window
3. reproduction and citation signals
4. completion quality
5. diversity caps by creator and topic

Do not introduce machine-learned ranking until there is enough behavior to
evaluate it.

### Analytics

Extend `usage_events` with:

- `technique.viewed`
- `technique.saved`
- `technique.forked`
- `technique.reproduction_published`
- `technique.cited`
- `question.asked`
- `question.answered`
- `answer.accepted`
- `creator.followed`
- `report.created`

The new north-star behavior is:

> A demonstrated technique is reused by someone other than its author.

Supporting measures:

- viewer-to-save conversion
- viewer-to-fork conversion
- fork-to-published-adaptation conversion
- published reproductions per technique
- questions receiving a demonstrated answer
- accepted-answer rate
- creators publishing a second technique
- percentage of public techniques reported or removed

## Trust, abuse, and governance

The community hub raises the cost of privacy and moderation mistakes.

Required before public beta:

- report categories for secrets/private data, harmful content, plagiarism,
  broken evidence, and attribution disputes
- reversible hide, remove-from-discovery, and account restriction actions
- an audit trail for moderator actions
- rate limits for publishing, questions, follows, saves, and reports
- duplicate/spam controls
- a clear attribution and takedown policy
- author controls to unpublish or restrict a release
- privacy matrix tests across every public read path and aggregate

Automatic secret detection remains a risk-reduction layer, not a guarantee.

## Identity and infrastructure dependencies

The MVP does not require Redis. PostgreSQL-backed community records, signed
cookie sessions, deterministic discovery, and database rate limits fit the
current Railway architecture.

Two leaves depend on Chirp platform work:

- [Chirp #871](https://github.com/lbliii/chirp/issues/871): preserve passkey
  ceremony state while keeping cookie sessions first-class and Redis optional
- [Chirp #872](https://github.com/lbliii/chirp/issues/872): make access-grant
  persistence portable across SQLite and PostgreSQL

Public profiles, public techniques, questions, forks, and reproductions do not
need to wait for organizations or SSO. Private/password-protected sharing
should use the portable access-grant primitive when it is ready.

## Delivery plan

### Milestone 1: Foundation

**Outcome:** one creator can publish a versioned technique backed by a public
release without weakening the current privacy boundary.

- freeze the domain and authorization contract
- add portable schema and records
- publish technique versions from releases
- prove public/unlisted/private eligibility across all queries

Exit criteria:

- schema runs on SQLite and PostgreSQL
- technique publication is transactional and idempotent
- private and unlisted releases are absent from all public community surfaces
- unpublishing immediately removes public eligibility

### Milestone 2: Private alpha

**Outcome:** invited creators can publish, discover, ask, answer, fork, and
reproduce techniques.

- creator profiles and technique pages
- governed topics, search, and deterministic discovery
- saves, follows, and collections
- questions and demonstrated answers
- fork lineage and reproduction evidence
- append-only attribution/reputation events

Exit criteria:

- 10 invited creators publish at least 25 techniques
- five techniques receive an attributed fork
- three techniques receive an evidence-backed reproduction
- every community action has authorization and transaction coverage

### Milestone 3: Public beta

**Outcome:** the community can grow without compromising trust, attribution, or
product quality.

- reports, moderation, rate limits, and attribution disputes
- private/password-protected releases when portable access grants are ready
- passkey sign-in when the Chirp ceremony contract is ready
- Claude Code and Cursor import adapters
- seeded launch curriculum and public beta analytics

Exit criteria:

- moderation actions are reversible and audited
- all privacy-matrix and abuse-path tests pass
- at least two agent formats beyond Codex produce equivalent `dvd/1` evidence
- the first curriculum contains 25 reviewed techniques across five topics

## Explicit non-goals

- hidden chain-of-thought publication
- deterministic re-execution of external side effects
- production observability, evaluation, or incident response
- opaque personalized ranking
- real-time chat or direct messages
- cryptocurrency, tradable reputation, or financial rewards
- automatic public publishing after import or fork
- Redis as a baseline deployment requirement
- organizations, SAML, or SCIM as blockers for the community MVP

## GitHub program map

The implementation backlog is organized under one program epic:

1. **Community domain, publishing contract, and privacy boundary**
2. **Creator profiles, technique pages, and discovery**
3. **Questions, forks, reproductions, and attribution**
4. **Community trust, moderation, and controlled access**
5. **Capture breadth, seeded curriculum, and public beta**

Each epic has bounded child issues with explicit acceptance criteria and a
milestone. The GitHub epic remains the live execution index; this document owns
the stable product and architecture decisions.

