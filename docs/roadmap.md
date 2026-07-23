# Showrun roadmap

**Status:** directional plan, not a delivery commitment  
**Last updated:** July 23, 2026

## Product direction

Showrun has proven the central loop:

```text
import → sanitize → direct → release → watch / embed
```

The next phase should make that loop trustworthy enough for durable personal
libraries, then collaborative enough for teams. Identity infrastructure should
follow the product boundary: personal sharing first, organizations second,
enterprise federation after real demand.

## Shipped foundation

- account-isolated private drafts
- Codex, Showrun JSONL, and `dvd/1` import
- local filtering and bounded evidence
- automatic pacing and proposed chapters
- editable event/chapter director
- public and unlisted immutable releases
- watch pages, embeds, oEmbed, and artifact downloads
- private release and engagement analytics
- API tokens, `showrun` / `sr` CLI, and stdio MCP
- SQLite locally and PostgreSQL on Railway

## Wave 1: trust and controlled sharing

**Goal:** let an individual build a durable library and decide exactly who can
watch each show.

- private releases that remain owner-only
- password-protected share links
- release access model that can later accept organization membership
- passkey sign-in when Chirp exposes a stable WebAuthn integration
- recovery, session management, and security-event UX
- explicit storage and retention controls
- founding-plan interest and willingness-to-pay test

Why first: privacy and durable storage are the most plausible reasons for an
individual to pay. They also establish the authorization model required by
organizations.

## Wave 2: organizations and collaboration

**Goal:** make Showrun a shared learning library rather than a collection of
personal accounts.

- organization/workspace model
- invitations and membership lifecycle
- owner, admin, editor, and viewer roles
- move or copy a personal draft into an organization
- organization-scoped library, analytics, and API tokens
- review/approval step before organization publishing
- simple team subscription and usage boundaries

Keep the first organization model intentionally small. Custom roles, nested
groups, and elaborate policy engines should wait for evidence that teams need
them.

## Wave 3: SSO and enterprise identity

**Goal:** support organizations that cannot adopt another standalone login.

Recommended sequence:

1. OIDC sign-in for one configured organization
2. verified-domain discovery and enforced SSO
3. organization-level session and audit controls
4. SAML only when a specific customer requires it
5. SCIM provisioning after membership volume justifies automation

OIDC is achievable within the current architecture, but it should bind to the
same organization and authorization model as password/passkey users. SAML and
SCIM add operational and support weight; they are not prerequisites for
proving the core product.

## Wave 4: durable media and distribution

**Goal:** let the same structured show travel wherever learning happens.

- opt-in archival storage and retention tiers
- generated MP4/GIF exports for channels that cannot hydrate an embed
- thumbnails and social preview images
- versioned embed SDK and framework helpers
- comments, annotations, and chapter deep links
- collections, playlists, and curated organization libraries
- import adapters for additional agent-session formats

The `dvd/1` artifact remains the source of truth. Rendered media is a derivative
distribution format.

## Platform dependencies

Showrun should use Chirp primitives when they are stable instead of growing a
second authentication framework inside the app.

Likely Chirp prerequisites:

- WebAuthn/passkey enrollment, authentication, recovery, and credential
  management
- organization membership and role-aware authorization hooks
- OIDC provider configuration and account linking
- secure organization invitation flows
- reusable audit/security event primitives

Redis is not a baseline requirement for these phases. Database-backed sessions,
tokens, invitations, and authorization fit the current architecture. Add a
separate coordination service only when a measured workload—such as distributed
jobs, rate limiting, or high-volume ephemeral state—requires it.

## Sequencing rules

- Do not add billing before there is a paid entitlement worth enforcing.
- Do not add SSO before organizations and membership are coherent.
- Do not persist raw transcripts by default.
- Do not let automatic redaction remove the author review step.
- Do not make video rendering the canonical artifact.
- Do not describe roadmap features as available in product marketing.

## Exit criteria for the next phase

Wave 1 is successful when:

- a creator can keep a show private or share it with a controlled audience
- authorization tests cover drafts, releases, embeds, downloads, and analytics
- a user can understand and revoke every active access path
- at least five target users create a second show
- multiple users demonstrate willingness to pay for privacy, durability, or a
  lasting library

