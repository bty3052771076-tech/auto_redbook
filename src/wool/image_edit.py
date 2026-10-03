"""Reference/persona editing for the existing daily_wool column."""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Any

from src.images.opencodex_images import generate_subscription_image
from .reference_library import WoolReferenceLibrary, wool_asset_root

_PERSONAS = {
    "openai": ("OpenAI.png", "short pale-lilac bob hair, blue-grey eyes, white woven flower hair clip"),
    "chatgpt": ("OpenAI.png", "short pale-lilac bob hair, blue-grey eyes, white woven flower hair clip"),
    "codex": ("OpenAI.png", "short pale-lilac bob hair, blue-grey eyes, white woven flower hair clip"),
    "deepseek": ("DeepSeek.png", "the face, hairstyle, clothing identity and distinctive accessories of IMAGE 2"),
    "anthropic": ("Claude.png", "the face, hairstyle and distinctive accessories of IMAGE 2"),
    "claude": ("Claude.png", "the face, hairstyle and distinctive accessories of IMAGE 2"),
    "stepfun": ("StepFun.png", "the face, hairstyle and distinctive accessories of IMAGE 2"),
    "阶跃星辰": ("StepFun.png", "the face, hairstyle and distinctive accessories of IMAGE 2"),
    "workbuddy": ("workbuddy.png", "the face, hairstyle and distinctive accessories of IMAGE 2"),
    "zcode": ("ZCode.png", "the face, hairstyle and distinctive accessories of IMAGE 2"),
}


def pick_persona(provider: str) -> tuple[str, str] | None:
    normalized = provider.strip().lower().replace(" ", "").replace("-", "")
    return _PERSONAS.get(normalized)


def create_wool_image(*, post_id: str, offers: list, issue_date: str) -> tuple[Path, dict[str, Any]]:
    runtime_root = Path(os.getenv("REDBOOK_RUNTIME_ROOT") or ".").resolve()
    root = wool_asset_root(runtime_root)
    configured_reference = os.getenv("WOOL_REFERENCE_IMAGE")
    reference = Path(configured_reference) if configured_reference else None
    if reference and not reference.is_absolute():
        reference = runtime_root / reference
    selected = next(((offer, pick_persona(offer.provider)) for offer in offers
                     if pick_persona(offer.provider)), None)
    if offers and selected is None:
        raise RuntimeError("WOOL_PERSONA_NOT_CONFIGURED: configure a persona for the actual offer provider")
    # The same daily cover survives post-ID changes during checkpoint recovery.
    day = date.fromisoformat(issue_date).isoformat()
    dest_dir = runtime_root / "data/cache/wool-images" / day
    if selected:
        offer, (filename, identity) = selected
        reference, reference_meta = WoolReferenceLibrary(root).select_reference(
            issue_date=issue_date, provider=offer.provider, override=reference
        )
        persona = root / "人设图" / filename
        for asset in (reference, persona):
            if not asset.is_file():
                raise RuntimeError(f"WOOL_IMAGE_RESOURCE_MISSING: copy the required local asset to {asset}")
        prompt = (
            "Create one finished portrait illustration for an AI-benefits editorial. "
            "IMAGE 1 provides ONLY its actual pose, camera perspective, framing, expression, "
            "composition and scene layout. Observe the supplied image; do not invent a fixed action pose. "
            "Replace its character completely with the ADULT character from IMAGE 2: " + identity + ". "
            "IMAGE 2 provides ONLY character identity, including face, hair color, eyes and distinctive accessories, "
            "not a multi-view layout. Never copy IMAGE 1's character identity or mix the two faces. "
            "One clearly adult character with natural mature proportions, fully clothed in a tasteful outfit "
            "suited to IMAGE 1's scene; no nudity, fetish focus, juvenile features or sexualized exaggeration. "
            "Preserve the recognizable face and hairstyle of IMAGE 2 in the action pose of IMAGE 1. "
            "Bright clean anime illustration, coherent anatomy, light background, small gift-box accents. "
            "Exactly one complete scene, not a reference sheet or collage. "
            "No labels, captions, Japanese writing, JSON, watermarks, extra characters, logos, prices, "
            "token amounts, expiry dates or invented promotional claims."
        )
        result = generate_subscription_image(post_id=post_id, prompt=prompt, dest_dir=dest_dir,
                                             reference_paths=[reference, persona],
                                             allow_minimax_fallback=False)
        return result.path, {**result.meta, **reference_meta, "asset_mode": "reference_persona_edit",
                             "reference": str(reference), "persona": str(persona),
                             "cover_provider": offer.provider, "issue_date": issue_date,
                             "covered_providers": [offer.provider],
                             "unpictured_providers": sorted({x.provider for x in offers if x.provider != offer.provider})}
    prompt = (
        "A clean cheerful editorial illustration of one small egg-shaped gift container, closed, "
        "on a white background with teal and coral stationery. No people, brand logos, discounts, "
        "numbers, captions or written claims. Calm neutral mood, portrait format. "
        "This illustrates a factual AI benefits bulletin with no currently verified offers, "
        "not a promise that any promotion exists."
    )
    result = generate_subscription_image(post_id=post_id, prompt=prompt, dest_dir=dest_dir,
                                         allow_minimax_fallback=False)
    return result.path, {**result.meta, "asset_mode": "no_offer_neutral_ai_illustration",
                         "issue_date": issue_date, "cover_provider": None}
