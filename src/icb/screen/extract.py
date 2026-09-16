"""Screen one deck against one approved pack (CLAUDE.md §8).

Order: ingest -> cache lookup -> one model call -> slide-range check -> align to the pack ->
compute the decision. The model's output is never trusted for labels, weights or decisions.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from icb import cache
from icb.criteria.models import CriteriaPack
from icb.ingest.router import Deck, load_deck
from icb.llm import client as llm
from icb.screen.decision import align, decide
from icb.screen.models import Provenance, Screening, ScreeningExtraction
from icb.screen.prompts import EXTRACTION_SCHEMA, PROMPT_VERSION, SYSTEM, build_content, schema_fingerprint


def _cited_slides(data: dict[str, Any]) -> list[int]:
    slides: list[int] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for field, value in node.items():
                if field == "slides" and isinstance(value, list):
                    slides.extend(item for item in value if isinstance(item, int))
                elif field == "slide" and isinstance(value, int):
                    slides.append(value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return slides


def _validator(deck: Deck) -> Callable[[dict[str, Any]], ScreeningExtraction]:
    def validate(data: dict[str, Any]) -> ScreeningExtraction:
        extraction = ScreeningExtraction.model_validate(data)
        out_of_range = sorted({n for n in _cited_slides(data) if n < 1 or n > deck.page_count})
        if out_of_range:
            raise ValueError(
                f"the deck has {deck.page_count} {deck.unit}s, so these citations cannot exist: "
                f"{', '.join(str(n) for n in out_of_range)}")
        return extraction

    return validate


def screen_deck(
    *,
    slug: str,
    investor_name: str,
    filename: str,
    data: bytes,
    pack: CriteriaPack,
    use_cache: bool = True,
    on_progress: Callable[[], None] | None = None,
) -> Screening:
    deck = load_deck(filename, data)
    cache_key = cache.key("screening", 1, deck.content_hash, pack.content_hash(), llm.model_name(),
                          llm.effort(), PROMPT_VERSION, schema_fingerprint(EXTRACTION_SCHEMA))

    cached = cache.read(cache_key) if use_cache else None
    if cached:
        screening = Screening.model_validate(cached)
        screening.provenance.cached = True
        return screening

    result = llm.call_json(
        system=SYSTEM,
        content=build_content(deck, pack),
        schema=EXTRACTION_SCHEMA,
        schema_name="screening",
        validate=_validator(deck),
        on_progress=on_progress,
    )
    extraction = ScreeningExtraction.model_validate(result.data)
    aligned, warnings = align(extraction, pack)
    decision = decide(aligned, pack)

    for index, request in enumerate(sorted(aligned.evidence_requests, key=lambda r: r.priority), start=1):
        request.priority = index

    screening = Screening(
        slug=slug,
        investor_name=investor_name,
        extraction=aligned,
        decision=decision,
        provenance=Provenance(
            source_filename=deck.filename,
            slide_count=deck.page_count,
            parse_warnings=deck.warnings,
            model=result.model,
            effort=llm.effort(),
            criteria_pack={"version": pack.version, "hash": pack.content_hash(),
                           "investor_name": pack.display_name},
            generated_at=_now(),
            warnings=warnings + (["The model's first answer was corrected once."] if result.corrected else []),
        ),
    )
    cache.write(cache_key, screening.model_dump(mode="json"))
    return screening


def _now() -> str:
    from icb.criteria.models import now_iso

    return now_iso()
