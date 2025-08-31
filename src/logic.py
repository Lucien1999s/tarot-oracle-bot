"""
logic.py — Orchestration layer that ties tarot_core mechanics to UI/API needs.

Responsibilities:
- Provide a single high-level entry point `perform_reading(...)` for the UI/API.
- Perform the draw via tarot_core, attach asset image paths, and (optionally)
  call the LLM to generate explanations/advice.
- Return a fully structured JSON-like dict that the UI can consume directly.

Notes:
- Image assets are expected under: ./assets/cards/{card_id}.png
- This module is LLM-provider agnostic at the callsite level; it depends on
  src.llm.chat() which wraps the Gemini SDK you configured.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Union

from . import tarot_core
from .llm import chat as llm_chat


# -----------------------------------------------------------------------------
# Paths & utilities
# -----------------------------------------------------------------------------

# Project root (resolve relative to this file)
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
# Card assets directory (you decided: assets/cards without the rws subfolder)
CARD_ASSETS_DIR = os.path.join(_PROJECT_ROOT, "assets", "cards")


def get_card_image_path(card_id: str, ext: str = "png") -> str:
    """
    Build a file path to a card image based on your repo layout:
      ./assets/cards/{card_id}.png

    The function returns the path string regardless of whether the file exists.
    The UI can check or attempt fallback handling as needed.
    """
    filename = f"{card_id}.{ext}"
    return os.path.join(CARD_ASSETS_DIR, filename)


# -----------------------------------------------------------------------------
# Prompt construction for the LLM
# -----------------------------------------------------------------------------

_BASE_PROMPT_ZH = """### ROLE
你是一個塔羅牌師父

### TASK
你會根據使用者的問題/人生困惑，還有抽到的塔羅牌來對抽出的塔羅牌逐個給出專業的塔羅牌解釋來解惑使用者

### OUTPUT
每個塔羅牌給一段解釋說明，最終一段是專業占卜結果給的建議
"""


def _build_llm_prompt(question: Optional[str], drawn: Dict[str, Any]) -> str:
    """
    Build a robust prompt for the LLM while preserving the exact base text you provided.

    We append structured context (cards + positions + orientations) and a request
    to keep responses concise and clearly separated per card, plus a final advice section.
    """
    q = (question or "").strip()
    # Minimal, deterministic card block for the model
    lines: List[str] = []
    lines.append("### INPUT")
    lines.append(f"使用者問題: {q if q else '(無)'}")
    lines.append("抽到的牌（依序）：")
    for c in drawn.get("cards", []):
        # e.g., 0. The Fool (major_00_the_fool) — upright — pos=past
        pos = c.get("position") or "-"
        lines.append(f"- {c['index']}. {c['card_name']} ({c['card_id']}) — {c['orientation']} — pos={pos}")
    lines.append("")
    # Light structure guidance (still compatible with your base prompt)
    lines.append("### STYLE")
    lines.append("語氣專業、溫和、具體。每張牌請 2-4 句。最後給 3 條可執行建議。")
    # We keep it textual. If later you want strict JSON from the model, we can add a JSON schema here.
    return _BASE_PROMPT_ZH + "\n" + "\n".join(lines)


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------

def perform_reading(
    num_cards: int,
    spread: Optional[str] = None,
    seed: Optional[Union[int, str]] = None,
    orientation_prob: float = 0.5,
    question: Optional[str] = None,
    explain_with_llm: bool = False,
    *,
    model: Optional[str] = None,
    temperature: float = 0.2,
    image_ext: str = "png",
) -> Dict[str, Any]:
    """
    Perform a tarot reading and (optionally) trigger an LLM explanation.

    Args:
        num_cards: Number of cards to draw.
        spread: Spread id (e.g., "single", "three_card", "five_card", "celtic_cross") or None.
        seed: Reproducibility seed (int or str).
        orientation_prob: Probability for a reversed orientation, [0, 1].
        question: User's question/pain point (can be None/empty).
        explain_with_llm: When True, call the LLM with a curated prompt.
        model: Optional LLM model name (passed to src.llm.chat).
        temperature: LLM sampling temperature.
        image_ext: Card image file extension (default "png").

    Returns:
        A JSON-serializable dict:

        {
          "meta": {
            "seed": int|null,
            "spread": str|null,
            "deck_type": "rws",
            "orientation_prob": float,
            "question": str|null,
            "explain_with_llm": bool
          },
          "cards": [
            {
              "card_id": str,
              "card_name": str,
              "suit": "major|wands|cups|swords|pentacles",
              "rank": str,
              "orientation": "upright|reversed",
              "position": str|null,
              "index": int,
              "image_path": str
            },
            ...
          ],
          "llm": {
            "prompt": str,             # only when explain_with_llm=True
            "response_text": str|null, # model's raw response (if call succeeded)
            "error": str|null          # error message if the LLM call failed
          }
        }
    """
    # 1) Draw cards via tarot_core
    draw = tarot_core.draw_cards(
        num_cards=num_cards,
        spread=spread,
        seed=seed,
        orientation_prob=orientation_prob,
        deck_type="rws",
    )

    # 2) Attach image paths for each card (assets/cards/{card_id}.png)
    enriched_cards: List[Dict[str, Any]] = []
    for c in draw["cards"]:
        enriched_cards.append(
            {
                **c,
                "image_path": get_card_image_path(c["card_id"], ext=image_ext),
            }
        )

    result: Dict[str, Any] = {
        "meta": {
            "seed": draw.get("seed"),
            "spread": draw.get("spread"),
            "deck_type": draw.get("deck_type"),
            "orientation_prob": draw.get("meta", {}).get("orientation_prob", orientation_prob),
            "question": question or None,
            "explain_with_llm": bool(explain_with_llm),
        },
        "cards": enriched_cards,
        "llm": {
            "prompt": None,
            "response_text": None,
            "error": None,
        },
    }

    # 3) Optionally call the LLM
    if explain_with_llm:
        prompt = _build_llm_prompt(question=question, drawn={**draw, "cards": enriched_cards})
        result["llm"]["prompt"] = prompt  # type: ignore[index]
        try:
            response_text = llm_chat(prompt=prompt, model=model, temperature=temperature)
            # Ensure it's a str for JSON-serializable safety
            if not isinstance(response_text, str):
                response_text = str(response_text)
            if not response_text.strip():
                response_text = "塔羅牌占卜師並未給出任何意見..."
            result["llm"]["response_text"] = response_text  # type: ignore[index]
        except Exception as e:
            # Capture the error so upstream can handle UX gracefully
            result["llm"]["error"] = f"{type(e).__name__}: {e}"  # type: ignore[index]

    return result
