"""Community Hub persistence: profiles, techniques, and immutable versions.

Every public read in this module flows through a single eligibility contract so
that private, unlisted, disabled, and unpublished content cannot leak through
discovery, direct reads, counts, or aggregates. The contract is expressed once
in :data:`PUBLIC_ELIGIBILITY` / :func:`public_head_version_sql` and reused by
every query. See ``docs/community-domain-contract.md``.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

# --- Centralized public-eligibility contract -------------------------------
#
# A technique version is publicly eligible only when ALL of these hold:
#   1. its backing release is public and active (not disabled/unpublished)
#   2. its creator profile is public
#   3. its technique is not disabled
#
# Discovery additionally requires ``t.status = 'published'`` (unlisted
# techniques are reachable by direct slug but never discoverable or counted).
# These fragments assume the canonical aliases t=techniques, p=profiles,
# tv=technique_versions, r=releases.

PUBLIC_RELEASE = "r.visibility = 'public' AND r.disabled_at IS NULL"
PUBLIC_PROFILE = "p.visibility = 'public'"
TECHNIQUE_NOT_DISABLED = "t.status <> 'disabled'"
TECHNIQUE_DISCOVERABLE = "t.status = 'published'"

# A version is the *public head* of its technique when it is the highest
# version number whose backing release is currently public and active.
_HEAD_VERSION_PREDICATE = (
    "tv.version = (SELECT MAX(tv2.version) FROM technique_versions tv2 "
    "JOIN releases r2 ON r2.id = tv2.release_id "
    "WHERE tv2.technique_id = t.id "
    "AND r2.visibility = 'public' AND r2.disabled_at IS NULL)"
)

# Canonical FROM/JOIN block shared by every public read.
_PUBLIC_FROM = (
    "FROM techniques t "
    "JOIN profiles p ON p.id = t.profile_id "
    "JOIN technique_versions tv ON tv.technique_id = t.id "
    "JOIN releases r ON r.id = tv.release_id"
)

_CARD_COLUMNS = (
    "t.id, t.lesson_id, t.slug, t.title, t.status, t.workspace_id, "
    "p.handle, p.display_name, p.visibility AS profile_visibility, "
    "tv.id AS version_id, tv.version, tv.release_id, r.slug AS release_slug, "
    "tv.problem, tv.pattern, tv.use_when, tv.objective, tv.limitations, "
    "tv.summary, tv.created_at"
)


def public_eligibility_sql(*, discoverable: bool) -> str:
    """Return the WHERE predicate that gates a public community read.

    ``discoverable=True`` is used by discovery/aggregate surfaces (feed, topic
    pages, counts, search). ``discoverable=False`` additionally admits unlisted
    techniques for direct slug access. Every public query reuses this so the
    privacy boundary lives in exactly one place.
    """

    technique_clause = TECHNIQUE_DISCOVERABLE if discoverable else TECHNIQUE_NOT_DISABLED
    return (
        f"{PUBLIC_RELEASE} AND {PUBLIC_PROFILE} AND {technique_clause} "
        f"AND {_HEAD_VERSION_PREDICATE}"
    )


# --- Records ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProfileRecord:
    id: str
    user_id: str
    workspace_id: str
    handle: str
    display_name: str
    bio: str
    visibility: str
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class TopicRecord:
    id: str
    key: str
    label: str
    description: str
    created_at: str


@dataclass(frozen=True, slots=True)
class CraftSignals:
    """Public contribution signals for a creator, derived from source records.

    No opaque authority score: each signal is itemized and reproducible from the
    underlying eligible records. Reproductions/forks/citations are first-class
    but remain 0 until those features land (#18/#19), never fabricated.
    """

    published_techniques: int
    topics: tuple[TopicRecord, ...]
    latest_published_at: str | None
    reproductions: int = 0
    forks: int = 0
    citations: int = 0


@dataclass(frozen=True, slots=True)
class TechniqueRecord:
    id: str
    lesson_id: str
    profile_id: str
    workspace_id: str
    slug: str
    title: str
    status: str
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class TechniqueVersionRecord:
    id: str
    technique_id: str
    version: int
    release_id: str
    problem: str
    pattern: str
    use_when: str
    objective: str
    limitations: str
    summary: str
    content_hash: str
    created_at: str


@dataclass(frozen=True, slots=True)
class TechniqueCard:
    """A publicly presentable technique: identity, head version, and creator."""

    id: str
    lesson_id: str
    slug: str
    title: str
    status: str
    workspace_id: str
    handle: str
    display_name: str
    profile_visibility: str
    version_id: str
    version: int
    release_id: str
    release_slug: str
    problem: str
    pattern: str
    use_when: str
    objective: str
    limitations: str
    summary: str
    created_at: str


@dataclass(frozen=True, slots=True)
class TechniqueCardInput:
    """Validated teaching metadata for a technique version."""

    problem: str
    pattern: str
    use_when: str
    objective: str
    limitations: str
    summary: str
    topics: tuple[str, ...]

    def content_hash(self, release_id: str) -> str:
        payload = json.dumps(
            {
                "release_id": release_id,
                "problem": self.problem,
                "pattern": self.pattern,
                "use_when": self.use_when,
                "objective": self.objective,
                "limitations": self.limitations,
                "summary": self.summary,
                "topics": sorted(self.topics),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class TechniqueCardError(ValueError):
    """Raised when technique-card teaching metadata fails validation."""


class ProfileError(ValueError):
    """Raised when profile fields fail validation."""


def validate_display_name(value: str) -> str:
    name = " ".join(str(value or "").split())
    if not name:
        raise ProfileError("Enter a display name.")
    if len(name) > 80:
        raise ProfileError("Display name must be 80 characters or fewer.")
    return name


def validate_bio(value: str) -> str:
    bio = " ".join(str(value or "").split())
    if len(bio) > 500:
        raise ProfileError("Keep your bio to 500 characters or fewer.")
    return bio


def validate_visibility(value: str) -> str:
    if value not in {"public", "private"}:
        raise ProfileError("Profile visibility must be public or private.")
    return value


# Handles that would collide with routes or read as impersonation. Kept in one
# place so the guard and any future admin tooling share the list.
RESERVED_HANDLES = frozenset(
    {
        "about", "admin", "api", "creator", "creators", "discover", "embed",
        "health", "help", "imports", "lessons", "login", "logout", "me", "new",
        "oembed", "profile", "profiles", "ready", "releases", "settings",
        "signup", "static", "support", "technique", "techniques", "topic",
        "topics", "watch",
    }
)


def validate_handle(value: str) -> str:
    """Normalize and validate a public handle. Raises ProfileError on failure."""

    handle = str(value or "").strip().lower()
    if not handle:
        raise ProfileError("Enter a handle.")
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", handle):
        raise ProfileError(
            "Handles use lowercase letters, numbers, and hyphens, and cannot "
            "start or end with a hyphen."
        )
    if len(handle) < 3 or len(handle) > 32:
        raise ProfileError("Handles must be 3 to 32 characters.")
    if handle in RESERVED_HANDLES:
        raise ProfileError("That handle is reserved. Choose another.")
    return handle


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _slug_base(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:48]


def _slugify(value: str) -> str:
    base = _slug_base(value) or "technique"
    return f"{base}-{uuid4().hex[:7]}"


def topic_key(value: str) -> str:
    """Deterministic, URL-safe taxonomy key for a topic label."""

    return _slug_base(value)[:48]


def _handle_base(name: str, email: str) -> str:
    base = _slug_base(name)
    if not base:
        base = _slug_base(email.split("@", 1)[0])
    return (base or "creator")[:32]


def _required(value: str, field: str, *, limit: int) -> str:
    cleaned = " ".join(str(value or "").split())
    if not cleaned:
        raise TechniqueCardError(f"Add the {field} for this technique.")
    if len(cleaned) > limit:
        raise TechniqueCardError(f"Keep the {field} to {limit} characters or fewer.")
    return cleaned


def _optional(value: str, *, limit: int) -> str:
    cleaned = " ".join(str(value or "").split())
    return cleaned[:limit]


def validate_card(
    *,
    problem: str,
    pattern: str,
    use_when: str,
    objective: str,
    summary: str,
    limitations: str = "",
    topics: Any = (),
) -> TechniqueCardInput:
    """Validate and normalize technique-card fields before publication."""

    raw_topics = re.split(r"[,\n]", topics) if isinstance(topics, str) else list(topics or ())
    keys: list[str] = []
    for candidate in raw_topics:
        key = topic_key(str(candidate))
        if key and key not in keys:
            keys.append(key)
    if not keys:
        raise TechniqueCardError("Add at least one topic.")
    if len(keys) > 5:
        raise TechniqueCardError("Use five topics or fewer.")
    return TechniqueCardInput(
        problem=_required(problem, "problem", limit=400),
        pattern=_required(pattern, "pattern", limit=2000),
        use_when=_required(use_when, "use-when guidance", limit=600),
        objective=_required(objective, "learning objective", limit=400),
        summary=_required(summary, "summary", limit=600),
        limitations=_optional(limitations, limit=1000),
        topics=tuple(keys),
    )


@dataclass(frozen=True, slots=True)
class _EligibleReleaseRow:
    id: str
    lesson_id: str
    slug: str
    visibility: str
    disabled_at: str | None


class CommunityStore:
    """Command-oriented repository for community records.

    Shares the same portable data layer and transaction contract as
    ``ShowrunStore``; keeps every public read anchored on the centralized
    eligibility predicate.
    """

    def __init__(self, database: Any) -> None:
        self.db = database

    # -- Profiles -----------------------------------------------------------

    async def ensure_profile(
        self,
        *,
        user_id: str,
        workspace_id: str,
        display_name: str,
        email: str,
    ) -> ProfileRecord:
        """Return the creator's profile, provisioning a public one on first use."""

        existing = await self.get_profile_by_user(user_id)
        if existing is not None:
            return existing
        now = _now()
        handle = await self._unique_handle(_handle_base(display_name, email))
        profile_id = f"profile_{uuid4().hex}"
        await self.db.execute(
            "INSERT INTO profiles "
            "(id, user_id, workspace_id, handle, display_name, bio, visibility, "
            "created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, '', 'public', ?, ?)",
            profile_id,
            user_id,
            workspace_id,
            handle,
            display_name,
            now,
            now,
        )
        await self._register_handle(profile_id, handle)
        profile = await self.get_profile_by_user(user_id)
        if profile is None:
            raise RuntimeError("Profile was not persisted")
        return profile

    async def _register_handle(self, profile_id: str, handle: str) -> bool:
        """Record a handle in the global registry. Returns False if taken."""

        inserted = await self.db.execute(
            "INSERT INTO profile_handles (handle, profile_id, created_at) "
            "VALUES (?, ?, ?) ON CONFLICT(handle) DO NOTHING",
            handle,
            profile_id,
            _now(),
        )
        return bool(inserted)

    async def _handle_owner(self, handle: str) -> str | None:
        """profile_id that owns a handle across current handles and past aliases."""

        return await self.db.fetch_val(
            "SELECT profile_id FROM profile_handles WHERE handle = ? "
            "UNION ALL SELECT id FROM profiles WHERE handle = ? LIMIT 1",
            handle,
            handle,
        )

    async def _unique_handle(self, base: str) -> str:
        candidate = base or "creator"
        suffix = 0
        while True:
            if await self._handle_owner(candidate) is None:
                return candidate
            suffix += 1
            candidate = f"{base}-{suffix}"[:40]

    async def change_handle(self, *, user_id: str, new_handle: str) -> ProfileRecord:
        """Claim a new handle, keeping the old one as a permanent redirect alias."""

        handle = validate_handle(new_handle)
        async with self.db.transaction():
            profile = await self.get_profile_by_user(user_id)
            if profile is None:
                raise LookupError("Profile not found")
            if handle == profile.handle:
                return profile
            owner = await self._handle_owner(handle)
            if owner is not None and owner != profile.id:
                raise ProfileError("That handle is taken. Choose another.")
            # Registering is atomic; if it lost a race to another profile the
            # handle is now owned by someone else and must be rejected.
            registered = await self._register_handle(profile.id, handle)
            if not registered and await self._handle_owner(handle) != profile.id:
                raise ProfileError("That handle is taken. Choose another.")
            await self.db.execute(
                "UPDATE profiles SET handle = ?, updated_at = ? WHERE id = ?",
                handle,
                _now(),
                profile.id,
            )
        updated = await self.get_profile_by_user(user_id)
        if updated is None:
            raise RuntimeError("Handle change was not persisted")
        return updated

    async def resolve_handle(self, handle: str) -> str | None:
        """Return the current handle for a handle or one of its past aliases."""

        normalized = str(handle or "").strip().lower()
        if not normalized:
            return None
        current = await self.db.fetch_val(
            "SELECT handle FROM profiles WHERE handle = ?",
            normalized,
        )
        if current:
            return str(current)
        aliased = await self.db.fetch_val(
            "SELECT p.handle FROM profile_handles ph "
            "JOIN profiles p ON p.id = ph.profile_id WHERE ph.handle = ?",
            normalized,
        )
        return str(aliased) if aliased else None

    async def get_profile_by_user(self, user_id: str) -> ProfileRecord | None:
        return await self.db.fetch_one(
            ProfileRecord,
            "SELECT id, user_id, workspace_id, handle, display_name, bio, "
            "visibility, created_at, updated_at FROM profiles WHERE user_id = ?",
            user_id,
        )

    async def get_public_profile(
        self,
        handle: str,
        *,
        viewer_workspace_id: str | None = None,
    ) -> ProfileRecord | None:
        """Return a profile only when the viewer may see it."""

        profile = await self.db.fetch_one(
            ProfileRecord,
            "SELECT id, user_id, workspace_id, handle, display_name, bio, "
            "visibility, created_at, updated_at FROM profiles WHERE handle = ?",
            handle,
        )
        if profile is None:
            return None
        if profile.visibility == "public":
            return profile
        if viewer_workspace_id is not None and profile.workspace_id == viewer_workspace_id:
            return profile
        return None

    async def set_profile_visibility(self, *, user_id: str, visibility: str) -> None:
        if visibility not in {"public", "private"}:
            raise ValueError("Profile visibility must be public or private")
        await self.db.execute(
            "UPDATE profiles SET visibility = ?, updated_at = ? WHERE user_id = ?",
            visibility,
            _now(),
            user_id,
        )

    async def update_profile(
        self,
        *,
        user_id: str,
        display_name: str,
        bio: str,
        visibility: str,
    ) -> ProfileRecord:
        """Update the creator's editable profile fields. Validated by the caller."""

        changed = await self.db.execute(
            "UPDATE profiles SET display_name = ?, bio = ?, visibility = ?, "
            "updated_at = ? WHERE user_id = ?",
            display_name,
            bio,
            visibility,
            _now(),
            user_id,
        )
        if not changed:
            raise LookupError("Profile not found")
        profile = await self.get_profile_by_user(user_id)
        if profile is None:
            raise RuntimeError("Profile update was not persisted")
        return profile

    # -- Topics -------------------------------------------------------------

    async def _ensure_topic(self, key: str) -> str:
        topic_id = await self.db.fetch_val(
            "SELECT id FROM topics WHERE key = ?",
            key,
        )
        if topic_id:
            return str(topic_id)
        new_id = f"topic_{uuid4().hex}"
        label = key.replace("-", " ").title()
        inserted = await self.db.execute(
            "INSERT INTO topics (id, key, label, description, created_at) "
            "VALUES (?, ?, ?, '', ?) ON CONFLICT(key) DO NOTHING",
            new_id,
            key,
            label,
            _now(),
        )
        if inserted:
            return new_id
        winner = await self.db.fetch_val("SELECT id FROM topics WHERE key = ?", key)
        return str(winner)

    async def list_topics_for_technique(self, technique_id: str) -> list[TopicRecord]:
        return await self.db.fetch(
            TopicRecord,
            "SELECT tp.id, tp.key, tp.label, tp.description, tp.created_at "
            "FROM topics tp JOIN technique_topics tt ON tt.topic_id = tp.id "
            "WHERE tt.technique_id = ? ORDER BY tp.key",
            technique_id,
        )

    # -- Techniques ---------------------------------------------------------

    async def _eligible_release(
        self,
        slug: str,
        *,
        workspace_id: str,
    ) -> _EligibleReleaseRow | None:
        """Return a release the workspace owns that may back a public technique.

        Enforces #11: only the release owner may publish, and a technique
        version may reference only a public, active release (never a draft,
        unlisted, or disabled release).
        """

        return await self.db.fetch_one(
            _EligibleReleaseRow,
            "SELECT rr.id, rr.lesson_id, rr.slug, rr.visibility, rr.disabled_at "
            "FROM releases rr JOIN lessons l ON l.id = rr.lesson_id "
            "WHERE rr.slug = ? AND l.workspace_id = ?",
            slug,
            workspace_id,
        )

    async def publish_technique_version(
        self,
        *,
        user_id: str,
        workspace_id: str,
        display_name: str,
        email: str,
        release_slug: str,
        card: TechniqueCardInput,
    ) -> tuple[TechniqueRecord, TechniqueVersionRecord, bool]:
        """Publish a technique version from an eligible release.

        Transactional and idempotent: republishing identical teaching metadata
        for the same release returns the existing version (created=False);
        any change creates a new immutable version. Returns
        ``(technique, version, created)``.
        """

        async with self.db.transaction():
            release = await self._eligible_release(release_slug, workspace_id=workspace_id)
            if release is None:
                raise LookupError("Release not found")
            if not (release.visibility == "public" and release.disabled_at is None):
                raise TechniqueCardError(
                    "Publish the release publicly before publishing a technique."
                )
            profile = await self._ensure_profile_locked(
                user_id=user_id,
                workspace_id=workspace_id,
                display_name=display_name,
                email=email,
            )
            technique = await self._ensure_technique_locked(
                lesson_id=release.lesson_id,
                profile_id=profile.id,
                workspace_id=workspace_id,
                title=card.summary or card.problem,
            )
            content_hash = card.content_hash(release.id)
            existing = await self.db.fetch_one(
                TechniqueVersionRecord,
                "SELECT id, technique_id, version, release_id, problem, pattern, "
                "use_when, objective, limitations, summary, content_hash, created_at "
                "FROM technique_versions WHERE technique_id = ? AND content_hash = ?",
                technique.id,
                content_hash,
            )
            if existing is not None:
                return technique, existing, False
            now = _now()
            next_version = int(
                await self.db.fetch_val(
                    "SELECT COALESCE(MAX(version), 0) + 1 FROM technique_versions "
                    "WHERE technique_id = ?",
                    technique.id,
                )
                or 1
            )
            version_id = f"techver_{uuid4().hex}"
            await self.db.execute(
                "INSERT INTO technique_versions "
                "(id, technique_id, version, release_id, problem, pattern, use_when, "
                "objective, limitations, summary, content_hash, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                version_id,
                technique.id,
                next_version,
                release.id,
                card.problem,
                card.pattern,
                card.use_when,
                card.objective,
                card.limitations,
                card.summary,
                content_hash,
                now,
            )
            await self.db.execute(
                "DELETE FROM technique_topics WHERE technique_id = ?",
                technique.id,
            )
            for key in card.topics:
                topic_id = await self._ensure_topic(key)
                await self.db.execute(
                    "INSERT INTO technique_topics (technique_id, topic_id) "
                    "VALUES (?, ?) ON CONFLICT DO NOTHING",
                    technique.id,
                    topic_id,
                )
            await self.db.execute(
                "UPDATE techniques SET status = "
                "CASE WHEN status = 'disabled' THEN 'disabled' ELSE 'published' END, "
                "title = ?, updated_at = ? WHERE id = ?",
                card.summary[:120] or technique.title,
                now,
                technique.id,
            )
            version = await self.db.fetch_one(
                TechniqueVersionRecord,
                "SELECT id, technique_id, version, release_id, problem, pattern, "
                "use_when, objective, limitations, summary, content_hash, created_at "
                "FROM technique_versions WHERE id = ?",
                version_id,
            )
            refreshed = await self._get_technique_by_id(technique.id)
            if version is None or refreshed is None:
                raise RuntimeError("Technique version was not persisted")
            return refreshed, version, True

    async def _ensure_profile_locked(
        self,
        *,
        user_id: str,
        workspace_id: str,
        display_name: str,
        email: str,
    ) -> ProfileRecord:
        existing = await self.get_profile_by_user(user_id)
        if existing is not None:
            return existing
        now = _now()
        handle = await self._unique_handle(_handle_base(display_name, email))
        await self.db.execute(
            "INSERT INTO profiles "
            "(id, user_id, workspace_id, handle, display_name, bio, visibility, "
            "created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, '', 'public', ?, ?) "
            "ON CONFLICT(user_id) DO NOTHING",
            f"profile_{uuid4().hex}",
            user_id,
            workspace_id,
            handle,
            display_name,
            now,
            now,
        )
        profile = await self.get_profile_by_user(user_id)
        if profile is None:
            raise RuntimeError("Profile was not persisted")
        await self._register_handle(profile.id, profile.handle)
        return profile

    async def _ensure_technique_locked(
        self,
        *,
        lesson_id: str,
        profile_id: str,
        workspace_id: str,
        title: str,
    ) -> TechniqueRecord:
        existing = await self.db.fetch_one(
            TechniqueRecord,
            "SELECT id, lesson_id, profile_id, workspace_id, slug, title, status, "
            "created_at, updated_at FROM techniques WHERE lesson_id = ?",
            lesson_id,
        )
        if existing is not None:
            return existing
        now = _now()
        technique_id = f"technique_{uuid4().hex}"
        clean_title = " ".join(title.split())[:120] or "Untitled technique"
        await self.db.execute(
            "INSERT INTO techniques "
            "(id, lesson_id, profile_id, workspace_id, slug, title, status, "
            "created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'published', ?, ?) "
            "ON CONFLICT(lesson_id) DO NOTHING",
            technique_id,
            lesson_id,
            profile_id,
            workspace_id,
            _slugify(clean_title),
            clean_title,
            now,
            now,
        )
        technique = await self.db.fetch_one(
            TechniqueRecord,
            "SELECT id, lesson_id, profile_id, workspace_id, slug, title, status, "
            "created_at, updated_at FROM techniques WHERE lesson_id = ?",
            lesson_id,
        )
        if technique is None:
            raise RuntimeError("Technique was not persisted")
        return technique

    async def _get_technique_by_id(self, technique_id: str) -> TechniqueRecord | None:
        return await self.db.fetch_one(
            TechniqueRecord,
            "SELECT id, lesson_id, profile_id, workspace_id, slug, title, status, "
            "created_at, updated_at FROM techniques WHERE id = ?",
            technique_id,
        )

    async def set_technique_status(
        self,
        *,
        slug: str,
        workspace_id: str,
        status: str,
    ) -> TechniqueRecord:
        """Owner/moderator lifecycle control. Reversible; never deletes history."""

        if status not in {"published", "unlisted", "disabled"}:
            raise ValueError("Unknown technique status")
        changed = await self.db.execute(
            "UPDATE techniques SET status = ?, updated_at = ? "
            "WHERE slug = ? AND workspace_id = ?",
            status,
            _now(),
            slug,
            workspace_id,
        )
        if not changed:
            raise LookupError("Technique not found")
        technique = await self.db.fetch_one(
            TechniqueRecord,
            "SELECT id, lesson_id, profile_id, workspace_id, slug, title, status, "
            "created_at, updated_at FROM techniques WHERE slug = ?",
            slug,
        )
        if technique is None:
            raise RuntimeError("Technique status was not persisted")
        return technique

    # -- Public reads (all anchored on public_eligibility_sql) --------------

    async def get_technique_card(
        self,
        slug: str,
        *,
        viewer_workspace_id: str | None = None,
    ) -> TechniqueCard | None:
        """Return a technique for direct slug access, honoring eligibility.

        Owners always see their own technique (including unlisted/disabled).
        Everyone else sees it only when it satisfies the direct-access
        eligibility predicate (public/unlisted, public profile, public+active
        head release).
        """

        card = await self.db.fetch_one(
            TechniqueCard,
            f"SELECT {_CARD_COLUMNS} {_PUBLIC_FROM} "
            f"WHERE t.slug = ? AND {public_eligibility_sql(discoverable=False)}",
            slug,
        )
        if card is not None:
            return card
        if viewer_workspace_id is None:
            return None
        return await self._owner_card(slug, workspace_id=viewer_workspace_id)

    async def owned_card_by_lesson(
        self,
        lesson_id: str,
        *,
        workspace_id: str,
    ) -> TechniqueCard | None:
        """Latest version of the workspace's technique for a lesson, for editing."""

        return await self.db.fetch_one(
            TechniqueCard,
            f"SELECT {_CARD_COLUMNS} {_PUBLIC_FROM} "
            "WHERE t.lesson_id = ? AND t.workspace_id = ? "
            "AND tv.version = (SELECT MAX(v.version) FROM technique_versions v "
            "WHERE v.technique_id = t.id)",
            lesson_id,
            workspace_id,
        )

    async def topics_csv(self, technique_id: str) -> str:
        topics = await self.list_topics_for_technique(technique_id)
        return ", ".join(topic.key for topic in topics)

    async def _owner_card(self, slug: str, *, workspace_id: str) -> TechniqueCard | None:
        # Owner preview: latest version regardless of release/profile state.
        return await self.db.fetch_one(
            TechniqueCard,
            f"SELECT {_CARD_COLUMNS} {_PUBLIC_FROM} "
            "WHERE t.slug = ? AND t.workspace_id = ? "
            "AND tv.version = (SELECT MAX(v.version) FROM technique_versions v "
            "WHERE v.technique_id = t.id)",
            slug,
            workspace_id,
        )

    async def list_public_techniques(
        self,
        *,
        query: str = "",
        topic: str = "",
        limit: int = 50,
    ) -> list[TechniqueCard]:
        """Discovery feed: eligible, discoverable techniques only."""

        clauses = [public_eligibility_sql(discoverable=True)]
        params: list[Any] = []
        from_block = _PUBLIC_FROM
        if topic.strip():
            from_block += (
                " JOIN technique_topics tt ON tt.technique_id = t.id "
                "JOIN topics tp ON tp.id = tt.topic_id"
            )
            clauses.append("tp.key = ?")
            params.append(topic_key(topic))
        needle = query.strip().lower()[:100]
        if needle:
            clauses.append(
                "(LOWER(t.title) LIKE ? OR LOWER(tv.problem) LIKE ? "
                "OR LOWER(tv.summary) LIKE ?)"
            )
            pattern = f"%{needle}%"
            params.extend((pattern, pattern, pattern))
        bounded = max(1, min(int(limit), 100))
        return await self.db.fetch(
            TechniqueCard,
            f"SELECT {_CARD_COLUMNS} {from_block} "
            f"WHERE {' AND '.join(clauses)} "
            f"ORDER BY tv.created_at DESC, t.id ASC LIMIT {bounded}",
            *params,
        )

    async def list_techniques_by_handle(
        self,
        handle: str,
        *,
        viewer_workspace_id: str | None = None,
    ) -> list[TechniqueCard]:
        """Techniques on a creator profile. Non-owners see discoverable only."""

        profile = await self.get_public_profile(
            handle,
            viewer_workspace_id=viewer_workspace_id,
        )
        if profile is None:
            return []
        is_owner = (
            viewer_workspace_id is not None and profile.workspace_id == viewer_workspace_id
        )
        if is_owner:
            return await self.db.fetch(
                TechniqueCard,
                f"SELECT {_CARD_COLUMNS} {_PUBLIC_FROM} "
                "WHERE t.workspace_id = ? "
                "AND tv.version = (SELECT MAX(v.version) FROM technique_versions v "
                "WHERE v.technique_id = t.id) "
                "ORDER BY t.updated_at DESC",
                profile.workspace_id,
            )
        return await self.db.fetch(
            TechniqueCard,
            f"SELECT {_CARD_COLUMNS} {_PUBLIC_FROM} "
            f"WHERE p.handle = ? AND {public_eligibility_sql(discoverable=True)} "
            "ORDER BY tv.created_at DESC, t.id ASC",
            handle,
        )

    async def craft_signals(self, handle: str) -> CraftSignals:
        """Reproducible public contribution signals for a creator profile.

        Always eligibility-respecting (discoverable content only), so the
        numbers reflect public contribution and match what any viewer can see.
        """

        eligible = public_eligibility_sql(discoverable=True)
        published = await self.db.fetch_val(
            f"SELECT COUNT(DISTINCT t.id) {_PUBLIC_FROM} "
            f"WHERE p.handle = ? AND {eligible}",
            handle,
        )
        latest = await self.db.fetch_val(
            f"SELECT MAX(tv.created_at) {_PUBLIC_FROM} "
            f"WHERE p.handle = ? AND {eligible}",
            handle,
        )
        topics = await self.db.fetch(
            TopicRecord,
            "SELECT DISTINCT tp.id, tp.key, tp.label, tp.description, tp.created_at "
            f"{_PUBLIC_FROM} "
            "JOIN technique_topics tt ON tt.technique_id = t.id "
            "JOIN topics tp ON tp.id = tt.topic_id "
            f"WHERE p.handle = ? AND {eligible} "
            "ORDER BY tp.key",
            handle,
        )
        return CraftSignals(
            published_techniques=int(published or 0),
            topics=tuple(topics),
            latest_published_at=str(latest) if latest else None,
        )

    async def public_technique_count(self, *, topic: str = "") -> int:
        """Count discoverable techniques. Never counts private/unlisted/disabled."""

        from_block = _PUBLIC_FROM
        params: list[Any] = []
        clauses = [public_eligibility_sql(discoverable=True)]
        if topic.strip():
            from_block += (
                " JOIN technique_topics tt ON tt.technique_id = t.id "
                "JOIN topics tp ON tp.id = tt.topic_id"
            )
            clauses.append("tp.key = ?")
            params.append(topic_key(topic))
        value = await self.db.fetch_val(
            f"SELECT COUNT(DISTINCT t.id) {from_block} WHERE {' AND '.join(clauses)}",
            *params,
        )
        return int(value or 0)

    async def list_public_topics(self) -> list[tuple[TopicRecord, int]]:
        """Topics with at least one discoverable technique, plus their counts."""

        rows = await self.db.fetch(
            _TopicCountRow,
            "SELECT tp.id, tp.key, tp.label, tp.description, tp.created_at, "
            f"COUNT(DISTINCT t.id) AS technique_count {_PUBLIC_FROM} "
            "JOIN technique_topics tt ON tt.technique_id = t.id "
            "JOIN topics tp ON tp.id = tt.topic_id "
            f"WHERE {public_eligibility_sql(discoverable=True)} "
            "GROUP BY tp.id, tp.key, tp.label, tp.description, tp.created_at "
            "ORDER BY technique_count DESC, tp.key ASC",
        )
        return [
            (
                TopicRecord(
                    id=row.id,
                    key=row.key,
                    label=row.label,
                    description=row.description,
                    created_at=row.created_at,
                ),
                row.technique_count,
            )
            for row in rows
        ]

    async def list_versions(
        self,
        slug: str,
        *,
        viewer_workspace_id: str | None = None,
    ) -> list[TechniqueVersionRecord]:
        """Version history for a technique the viewer is allowed to read."""

        card = await self.get_technique_card(slug, viewer_workspace_id=viewer_workspace_id)
        if card is None:
            return []
        return await self.db.fetch(
            TechniqueVersionRecord,
            "SELECT id, technique_id, version, release_id, problem, pattern, "
            "use_when, objective, limitations, summary, content_hash, created_at "
            "FROM technique_versions WHERE technique_id = ? ORDER BY version DESC",
            card.id,
        )


@dataclass(frozen=True, slots=True)
class _TopicCountRow:
    id: str
    key: str
    label: str
    description: str
    created_at: str
    technique_count: int
