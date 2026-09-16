"""Build a Criteria Pack draft from a saved profile, and approve it (CLAUDE.md §7).

Two gates, both in code: a pack cannot be built while any §6 input is still `not_provided`,
and it cannot be approved while any element carries `needs_input` or an open question.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from icb.criteria.models import CriteriaDraft, CriteriaPack, DRAFT_SCHEMA, now_iso
from icb.criteria.prompts import SYSTEM, build_content
from icb.llm import client as llm
from icb.profile import store


def _persist(pack: CriteriaPack) -> None:
    """Store the pack with its content hash, so readers need not recompute it."""
    data = pack.model_dump(mode="json")
    data["content_hash"] = pack.content_hash()
    store.write_criteria(pack.slug, data)


def _profile_for_build(slug: str) -> dict[str, Any]:
    profile = store.read_profile(slug)
    if not profile:
        raise store.InvalidInput("No inputs have been saved for this investor yet.")
    _, open_questions = store.profile_progress(store.investor_path(slug))
    if open_questions:
        raise store.InvalidInput(
            f"{open_questions} input{'s are' if open_questions != 1 else ' is'} still needed before a "
            "Criteria Pack can be built. Complete the investor criteria first.")
    return profile


def build_draft(slug: str, on_progress: Callable[[], None] | None = None) -> CriteriaPack:
    """One model call. The draft is stored even when it carries open questions."""
    profile = _profile_for_build(slug)
    result = llm.call_json(
        system=SYSTEM,
        content=build_content(profile, store.note_texts(slug)),
        schema=DRAFT_SCHEMA,
        schema_name="criteria_draft",
        validate=CriteriaDraft.model_validate,
        on_progress=on_progress,
    )
    pack = CriteriaPack(
        version=store.next_criteria_version(slug),
        slug=slug,
        display_name=profile.get("display_name", slug),
        status="draft",
        created_at=now_iso(),
        model=result.model,
        profile_updated_at=profile.get("updated_at"),
        draft=CriteriaDraft.model_validate(result.data),
    )
    _persist(pack)
    return pack


def load_pack(slug: str, version: int | None = None, status: str = "draft") -> CriteriaPack:
    stored = store.read_criteria(slug, version=version, status=status)
    if stored is None:
        which = f"v{version}" if version else "latest"
        raise store.InvalidInput(f"No {status} Criteria Pack ({which}) exists for this investor.")
    stored.pop("content_hash", None)  # derived on write; recomputed from content
    return CriteriaPack.model_validate(stored)


def approve(slug: str, version: int | None = None) -> CriteriaPack:
    """Freeze a draft. Refuses while anything still needs the investor's input."""
    pack = load_pack(slug, version=version, status="draft")
    blocking = pack.draft.blocking_questions()
    if blocking:
        raise store.InvalidInput(
            f"{len(blocking)} question{'s' if len(blocking) != 1 else ''} must be answered before this "
            "pack can be approved.")
    if store.read_criteria(slug, version=pack.version, status="approved") is not None:
        raise store.InvalidInput(f"Criteria Pack v{pack.version} is already approved and cannot be changed.")
    approved = pack.model_copy(update={"status": "approved", "approved_at": now_iso()})
    _persist(approved)
    return approved
