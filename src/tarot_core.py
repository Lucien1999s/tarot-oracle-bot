# -*- coding: utf-8 -*-
"""
tarot_core.py — Core Tarot mechanisms (deck / shuffle / draw / spread mapping)

Responsibilities:
- Define the RWS (Rider–Waite–Smith) 78-card deck (id / name / suit / rank)
- Define spreads (single / three_card / five_card / celtic_cross)
- Provide unbiased shuffling (Fisher–Yates) and drawing (with upright/reversed probability)
- Provide reproducible randomness (seed can be int or str; str will be hashed)
- Public API: list_spreads / get_spread / build_deck / shuffle_deck / draw_cards

Note:
- This module only implements Tarot mechanics and is UI/LLM agnostic.
  Higher orchestration should live in logic.py (e.g., RAG + LLM assembly).
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from typing import Dict, List, Optional, TypedDict, Union, Literal


# =========================
# Types & Error classes
# =========================

class TarotCoreError(Exception):
    """Base class for tarot-core errors."""


class InvalidSpreadError(TarotCoreError):
    """Raised when a spread id is not registered or has a card-count mismatch."""


class InvalidParameterError(TarotCoreError):
    """Raised when an input parameter is invalid."""


Orientation = Literal["upright", "reversed"]


class DrawnCard(TypedDict):
    """A single drawn card (structured for front-end/LLM)."""
    card_id: str
    card_name: str
    suit: Literal["major", "wands", "cups", "swords", "pentacles"]
    rank: str            # major: "0".."21"; minor: "ace","2",...,"king"
    orientation: Orientation
    position: Optional[str]
    index: int           # draw order in this session (0-based)


class SpreadDef(TypedDict):
    """Spread definition."""
    id: str
    name: str
    positions: List[str]


@dataclass(frozen=True)
class CardDef:
    """Card definition (RWS)."""
    id: str              # e.g., "major_00_the_fool", "minor_wands_ace"
    name: str            # e.g., "The Fool", "Ace of Wands"
    suit: Literal["major", "wands", "cups", "swords", "pentacles"]
    rank: str            # major: "0".."21"; minor: "ace","2",...,"king"


# =========================
# Spread registry (includes five-card)
# =========================

SPREAD_REGISTRY: Dict[str, SpreadDef] = {
    "single": {
        "id": "single",
        "name": "Single Card",
        "positions": ["focus"],  # central message for this draw
    },
    "three_card": {
        "id": "three_card",
        "name": "Three Card (Past / Present / Future)",
        "positions": ["past", "present", "future"],
    },
    "five_card": {
        "id": "five_card",
        "name": "Five Card (Issue / Action / Obstacle / Resource / Outcome)",
        "positions": ["issue", "action", "obstacle", "resource", "outcome"],
    },
    "celtic_cross": {
        "id": "celtic_cross",
        "name": "Celtic Cross (10)",
        # Common naming; different schools may use slight variants
        "positions": [
            "situation",       # current situation
            "challenge",       # obstacle / challenge
            "subconscious",    # root / underlying influence
            "past",            # recent past
            "conscious",       # conscious goal / intention
            "near_future",     # near future
            "self",            # self / inner attitude
            "environment",     # environment / others' influence
            "hopes_fears",     # hopes & fears
            "outcome",         # outcome / trajectory
        ],
    },
}


def list_spreads() -> List[SpreadDef]:
    """Return all available spreads."""
    return list(SPREAD_REGISTRY.values())


def get_spread(spread_id: str) -> SpreadDef:
    """Get a single spread definition; raise if not registered."""
    if spread_id not in SPREAD_REGISTRY:
        raise InvalidSpreadError(f"Spread '{spread_id}' is not registered.")
    return SPREAD_REGISTRY[spread_id]


# =========================
# RWS 78-card deck definition
# =========================

def _slug(s: str) -> str:
    return (
        s.lower()
        .replace(" ", "_")
        .replace("-", "_")
        .replace("’", "")
        .replace("'", "")
    )


def _build_rws_registry() -> List[CardDef]:
    """Build the RWS 78-card registry (stable order; useful for tests/repro)."""
    majors = [
        "The Fool", "The Magician", "The High Priestess", "The Empress",
        "The Emperor", "The Hierophant", "The Lovers", "The Chariot",
        "Strength", "The Hermit", "Wheel of Fortune", "Justice",
        "The Hanged Man", "Death", "Temperance", "The Devil",
        "The Tower", "The Star", "The Moon", "The Sun",
        "Judgement", "The World",
    ]

    registry: List[CardDef] = []
    for i, name in enumerate(majors):
        cid = f"major_{i:02d}_{_slug(name)}"
        registry.append(CardDef(id=cid, name=name, suit="major", rank=str(i)))

    # Minor Arcana
    suits = [
        ("wands", "Wands"),
        ("cups", "Cups"),
        ("swords", "Swords"),
        ("pentacles", "Pentacles"),
    ]
    ranks = [
        ("ace", "Ace"),
        ("2", "Two"),
        ("3", "Three"),
        ("4", "Four"),
        ("5", "Five"),
        ("6", "Six"),
        ("7", "Seven"),
        ("8", "Eight"),
        ("9", "Nine"),
        ("10", "Ten"),
        ("page", "Page"),
        ("knight", "Knight"),
        ("queen", "Queen"),
        ("king", "King"),
    ]

    for suit_key, suit_name in suits:
        for rank_key, rank_name in ranks:
            cid = f"minor_{suit_key}_{rank_key}"
            cname = f"{rank_name} of {suit_name}"
            registry.append(CardDef(
                id=cid, name=cname, suit=suit_key, rank=rank_key
            ))

    assert len(registry) == 78, f"RWS registry size should be 78, got {len(registry)}"
    return registry


CARD_REGISTRY: List[CardDef] = _build_rws_registry()
CARD_ID_INDEX: Dict[str, int] = {c.id: idx for idx, c in enumerate(CARD_REGISTRY)}  # quick lookup by id


def build_deck(deck_type: str = "rws") -> List[str]:
    """
    Build an ordered list of card IDs for the given deck type.
    Currently supported: 'rws'. Future: 'thoth' / 'marseille'.
    """
    if deck_type != "rws":
        raise InvalidParameterError(f"Unsupported deck_type: {deck_type}")
    return [c.id for c in CARD_REGISTRY]


# =========================
# RNG / Shuffling
# =========================

def _norm_seed(seed: Optional[Union[int, str]]) -> Optional[int]:
    """
    Normalize seed to int. If str, hash with sha256 and take the first 8 bytes
    as an unsigned 64-bit integer. None stays None.
    """
    if seed is None:
        return None
    if isinstance(seed, int):
        return seed
    if isinstance(seed, str):
        h = hashlib.sha256(seed.encode("utf-8")).digest()
        return int.from_bytes(h[:8], byteorder="big", signed=False)
    raise InvalidParameterError("seed must be int | str | None")


def _fisher_yates_shuffle(items: List[str], rng: random.Random) -> List[str]:
    """
    Fisher–Yates (Knuth) shuffle.
    Returns a new list and does not mutate the input.
    """
    arr = items[:]
    n = len(arr)
    for i in range(n - 1, 0, -1):
        j = rng.randint(0, i)  # inclusive
        arr[i], arr[j] = arr[j], arr[i]
    return arr


def shuffle_deck(deck: List[str], seed: Optional[Union[int, str]] = None) -> List[str]:
    """
    Shuffle a deck using Fisher–Yates. Seed controls reproducibility.
    Returns a new list and does not mutate the input.
    """
    norm = _norm_seed(seed)
    rng = random.Random(norm)
    return _fisher_yates_shuffle(deck, rng)


# =========================
# Draw
# =========================

def _serialize_drawn_card(card_id: str, orientation: Orientation, position: Optional[str], index: int) -> DrawnCard:
    """
    Resolve card metadata from the registry and bundle it as a DrawnCard record.
    """
    idx = CARD_ID_INDEX.get(card_id)
    if idx is None:
        # Should not happen with a valid deck; provide a fallback
        return DrawnCard(
            card_id=card_id, card_name=card_id, suit="major", rank="?",
            orientation=orientation, position=position, index=index
        )
    c = CARD_REGISTRY[idx]
    return DrawnCard(
        card_id=c.id,
        card_name=c.name,
        suit=c.suit,
        rank=c.rank,
        orientation=orientation,
        position=position,
        index=index,
    )


def draw_cards(
    num_cards: int,
    spread: Optional[str] = None,
    seed: Optional[Union[int, str]] = None,
    orientation_prob: float = 0.5,
    deck_type: str = "rws",
) -> Dict[str, object]:
    """
    Core entry point: shuffle, draw, determine orientation, map positions.

    Args:
        num_cards: number of cards to draw (>0 and <= 78)
        spread: spread id; if provided, positions length must equal num_cards
        seed: reproducibility seed (int or str). str is hashed internally
        orientation_prob: probability of a reversed card in [0, 1]
        deck_type: deck identifier ("rws" only for now)

    Returns:
        dict:
        {
          "seed": <int | None>,
          "spread": <str | None>,
          "deck_type": "rws",
          "meta": {"num_cards": int, "orientation_prob": float},
          "cards": [
            {
              "card_id": "...", "card_name": "...", "suit": "...", "rank": "...",
              "orientation": "upright|reversed", "position": "past|...", "index": 0
            },
            ...
          ]
        }
    """
    # Validate parameters
    if not isinstance(num_cards, int) or num_cards <= 0:
        raise InvalidParameterError("num_cards must be a positive integer")
    if not (0.0 <= float(orientation_prob) <= 1.0):
        raise InvalidParameterError("orientation_prob must be within [0.0, 1.0]")

    deck = build_deck(deck_type=deck_type)
    if num_cards > len(deck):
        raise InvalidParameterError(f"num_cards cannot exceed deck size (78); got {num_cards}")

    spread_def: Optional[SpreadDef] = None
    if spread is not None:
        spread_def = get_spread(spread)
        if len(spread_def["positions"]) != num_cards:
            raise InvalidSpreadError(
                f"Spread '{spread}' expects {len(spread_def['positions'])} cards, got {num_cards}"
            )

    # RNG
    norm_seed = _norm_seed(seed)
    rng = random.Random(norm_seed)

    # Shuffle & pick
    shuffled = _fisher_yates_shuffle(deck, rng)
    picked = shuffled[:num_cards]

    # Orientation & position mapping
    result_cards: List[DrawnCard] = []
    for idx, cid in enumerate(picked):
        orient: Orientation = "reversed" if rng.random() < float(orientation_prob) else "upright"
        pos: Optional[str] = None
        if spread_def:
            pos = spread_def["positions"][idx]
        result_cards.append(_serialize_drawn_card(cid, orient, pos, idx))

    return {
        "seed": norm_seed,
        "spread": spread_def["id"] if spread_def else None,
        "deck_type": deck_type,
        "meta": {"num_cards": num_cards, "orientation_prob": float(orientation_prob)},
        "cards": result_cards,
    }


# =========================
# __main__ demo (structured pprint)
# =========================

if __name__ == "__main__":
    from pprint import pprint

    # Single card
    draw1 = draw_cards(num_cards=1, spread="single", seed="demo-user-001", orientation_prob=0.35)
    print("=== Example #1: Single Card (structured) ===")
    pprint(draw1, sort_dicts=False)
    print()

    # Three cards (Past / Present / Future)
    draw2 = draw_cards(num_cards=3, spread="three_card", seed="demo-user-002", orientation_prob=0.5)
    print("=== Example #2: Three Card PPF (structured) ===")
    pprint(draw2, sort_dicts=False)
    print()

    # Five cards (Issue / Action / Obstacle / Resource / Outcome)
    draw3 = draw_cards(num_cards=5, spread="five_card", seed="demo-user-005", orientation_prob=0.45)
    print("=== Example #3: Five Card (structured) ===")
    pprint(draw3, sort_dicts=False)
    print()

    # Ten cards (Celtic Cross)
    draw4 = draw_cards(num_cards=10, spread="celtic_cross", seed="demo-user-010", orientation_prob=0.4)
    print("=== Example #4: Celtic Cross (structured) ===")
    pprint(draw4, sort_dicts=False)
    print()
