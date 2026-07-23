# Showrun product strategy

**Status:** working product thesis  
**Last updated:** July 23, 2026

## The one-sentence strategy

Showrun makes agent work understandable and reusable by turning real execution
trails into sanitized, evidence-rich shows that can be watched, inspected,
shared, and embedded.

The memorable expression is:

> **Show your agent's work.**

The descriptive expression is:

> Turn real agent sessions into replayable, inspectable documentation.

## The actual value

The product is not valuable because it stores chat. Model providers already
store conversations, and generic databases can store JSON cheaply.

Showrun is valuable because it performs a difficult transformation:

```text
ephemeral execution
        ↓
curated explanation + credible evidence
        ↓
durable learning and proof artifact
```

That transformation combines five jobs that otherwise require separate tools
or manual work:

1. **Capture:** preserve the useful shape of a real agent run.
2. **Trust:** sanitize likely secrets and local-only context before upload.
3. **Direction:** turn a raw event stream into a paced, chaptered narrative.
4. **Proof:** retain inspectable evidence of tools, MCPs, sources, tests, file
   changes, and delegation.
5. **Distribution:** publish one immutable artifact as a watch page, embed, or
   portable file.

The result can shorten explanation time, make agent demos more credible, and
let one successful run keep teaching after the original conversation ends.

## Primary users

### Beachhead

- developer-relations and documentation teams explaining agent workflows
- agent, skill, prompt, and MCP authors proving their work
- AI educators, course creators, and consultants

These groups already create demos and learning material, care about
presentation, and benefit immediately from a URL or embed.

### Expansion

- engineering teams preserving debugging and research walkthroughs
- enablement teams building internal agent playbooks
- individuals publishing a portfolio of credible agent work
- organizations curating a durable library of approved workflows

### Not the initial customer

- teams seeking full production tracing, cost monitoring, or incident response
- users who only need raw chat backup
- buyers who require enterprise identity and governance before trying a product
- workflows that cannot tolerate any human publishing review

## Core jobs to be done

When I finish a useful agent run, help me turn it into something others can
learn from without rebuilding the demo by hand.

When I claim that an agent, skill, prompt, or MCP works, help me show the
observable evidence behind that claim.

When I publish an agent session, help me review and remove likely private
context before it becomes public.

When I write documentation, let me embed a living walkthrough instead of
maintaining a pile of screenshots.

## Message hierarchy

The public story should appear in this order:

1. **Promise:** Show your agent's work.
2. **Problem:** useful runs are hard to explain, unsafe to publish raw, and
   easy to lose.
3. **Transformation:** capture → sanitize → direct → publish → learn.
4. **Proof:** one real, evidence-rich Showrun and its documentation embed.
5. **Audience fit:** docs, DevRel, educators, integration authors, and builders.
6. **Boundary:** observable evidence, not hidden chain-of-thought or full
   observability.
7. **Mechanism:** artifact format, CLI/MCP, director, releases, and stack.

Avoid leading with feature inventory, framework names, “AI video,” or “chat
storage.” Those descriptions make the product sound more replaceable than it
is.

## Product principles

### Evidence over spectacle

The playback should be attractive, but trust comes from inspectable events and
sources. A polished animation without evidence is only a screen recording.

### Artifact before video

The durable product object is structured `dvd/1`, not rendered pixels. A
structured artifact remains searchable, accessible, themeable, deep-linkable,
and embeddable. Video export can be a distribution format later.

### Private draft, deliberate release

Importing creates a private draft. Publishing is a separate, explicit act that
produces an immutable release.

### Sanitize locally, review visibly

Likely secrets and host-only context should be removed before hosted
persistence. The author still reviews the result; the product must never claim
perfect automatic redaction.

### Teach the outcome, preserve the trail

The default cut should keep the narrative understandable. Readers who need
more detail can expand the evidence without forcing every viewer through every
low-level event.

## Business model hypothesis

The simplest initial test is a generous public product plus a small paid tier
for durability, privacy, and control.

| Tier | Hypothesis | Candidate value |
| --- | --- | --- |
| Free | Make sharing and embedding easy | Public/unlisted shows, embeds, portable artifacts, limited hosted library |
| Personal | **$5/month founding price** | Private/password-protected shows, larger durable library, analytics history, presentation controls |
| Team | Later, per workspace or small flat fee | Shared library, invites, roles, team analytics, approved publishing |
| Enterprise | Only after demand appears | OIDC/SAML SSO, SCIM, audit controls, retention, contractual support |

The $5 price is a discovery hypothesis, not a committed public price. Customers
should be paying for a maintained body of useful work and controlled
distribution—not for raw byte storage.

Before building a complex billing system, test the proposition with a clearly
labeled “Showrun Pro — $5/month, coming soon” interest action and conversations
with founding users.

## What to measure

The north-star behavior is **a published show that gets watched by someone
other than its author**.

Early measures:

- time from import to first publish
- percentage of imported drafts that become a release
- percentage of releases shared or embedded
- unique non-author viewers per release
- chapter completion and evidence expansion
- creators who publish a second show within 30 days
- interest in private/protected shows at the proposed price

Storage volume and account count are supporting metrics, not proof of value.

## Near-term validation plan

1. Make the golden Showrun the clearest possible product demonstration.
2. Recruit 10–20 docs, DevRel, educator, and agent-tool creators.
3. Watch each person import, review, publish, and share one real session.
4. Record where authoring takes longer than the value it produces.
5. Offer the $5 founding plan only after users ask for privacy, durability, or a
   lasting library.
6. Prioritize repeated behavior over compliments: second shows, embeds, and
   viewers are stronger signals than stated enthusiasm.

## Product claims and non-claims

Showrun can claim:

- it records and replays observable session events
- it locally filters known host-only structures and common sensitive shapes
- it creates immutable public or unlisted releases
- it presents bounded evidence for tools, MCPs, sources, tests, files, and
  delegation

Showrun should not claim:

- perfect secret detection
- access to private model reasoning or hidden chain-of-thought
- complete production observability
- compliance certification that has not been earned
- private sharing, passkeys, organizations, SSO, or billing before those
  features ship

