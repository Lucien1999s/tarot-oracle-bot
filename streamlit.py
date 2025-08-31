# streamlit.py — Minimal MVP UI for tarot-oracle-bot
# Run:  streamlit run streamlit.py

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional

import streamlit as st

# Ensure repo root is importable (so `src` package can be imported in all environments)
REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.logic import perform_reading  # noqa: E402

# -----------------------------
# Page setup
# -----------------------------
st.set_page_config(
    page_title="Tarot Oracle Bot",
    page_icon="🔮",
    layout="wide",
)

st.title("🔮 Tarot Oracle Bot")
st.caption("MVP UI — draw cards, optionally get LLM guidance if you provide a question.")

# -----------------------------
# Sidebar controls
# -----------------------------
st.sidebar.header("Controls")

SPREAD_OPTIONS = ["single", "three_card", "five_card", "celtic_cross", "(none)"]
spread = st.sidebar.selectbox("Spread", SPREAD_OPTIONS, index=1)

def spread_card_count(spread_id: str) -> Optional[int]:
    return {
        "single": 1,
        "three_card": 3,
        "five_card": 5,
        "celtic_cross": 10,
    }.get(spread_id, None)

fixed_n = spread_card_count(spread)
if fixed_n is None:
    num_cards = st.sidebar.slider("Number of cards (no spread)", min_value=1, max_value=15, value=3, step=1)
    spread_id: Optional[str] = None
else:
    st.sidebar.markdown(f"**Number of cards:** `{fixed_n}`")
    num_cards = fixed_n
    spread_id = spread

orientation_prob = st.sidebar.slider(
    "Reversed probability",
    min_value=0.0, max_value=1.0, value=0.5, step=0.05,
    help="Probability a drawn card is reversed."
)

seed = st.sidebar.text_input(
    "Seed (optional)",
    value="",  # default OFF (empty = no seed)
    placeholder="Leave empty for random each time",
    help="Enter a value to lock results; leave empty for a fresh random draw."
)

image_ext = st.sidebar.selectbox("Image extension", options=["png", "jpg", "webp"], index=0)

with st.sidebar.expander("LLM (optional)"):
    model = st.text_input("Model override (optional)", value="", placeholder="e.g. gemini-2.5-flash")
    temperature = st.slider("Temperature", min_value=0.0, max_value=1.0, value=0.2, step=0.05)

show_paths = st.sidebar.checkbox("Show image paths (debug)", value=False)

# -----------------------------
# Main panel inputs
# -----------------------------
question = st.text_area(
    "Your question (optional)",
    placeholder="Type your life question or context... If provided, the LLM will explain the draw.",
    height=100,
)

# Auto-enable LLM if user provided a question
explain_with_llm = bool(question.strip())

col_btn1, col_btn2 = st.columns([1, 1])
with col_btn1:
    run = st.button("🔀 Draw cards", use_container_width=True)
with col_btn2:
    clear = st.button("🧹 Clear output", use_container_width=True)

if clear:
    st.session_state.pop("reading_result", None)
    st.rerun()

# -----------------------------
# Execute draw
# -----------------------------
if run:
    with st.spinner("Drawing cards..."):
        try:
            if seed.strip() == "":
                seed_val: Optional[int | str] = None
            else:
                try:
                    seed_val = int(seed)
                except ValueError:
                    seed_val = seed

            result: Dict[str, Any] = perform_reading(
                num_cards=num_cards,
                spread=spread_id,
                seed=seed_val,
                orientation_prob=orientation_prob,
                question=question,
                explain_with_llm=explain_with_llm,
                model=(model or None),
                temperature=temperature,
                image_ext=image_ext,
            )
            st.session_state["reading_result"] = result
        except Exception as e:
            st.error(f"Reading failed: {type(e).__name__}: {e}")

# -----------------------------
# Render output
# -----------------------------
result = st.session_state.get("reading_result")
if result:
    meta = result.get("meta", {})
    cards: List[Dict[str, Any]] = result.get("cards", [])
    llm_block = result.get("llm", {}) or {}

    st.subheader("Result")

    # Meta badges
    sb1, sb2, sb3, sb4 = st.columns(4)
    with sb1:
        st.metric("Spread", meta.get("spread") or "(none)")
    with sb2:
        st.metric("Cards", len(cards))
        st.caption(f"Reversed prob: `{meta.get('orientation_prob', 0.5)}`")
    with sb3:
        st.metric("Deck", meta.get("deck_type", "rws"))
        st.caption(f"Seed: `{meta.get('seed')}`")
    with sb4:
        st.metric("LLM", "ON" if meta.get("explain_with_llm") else "OFF")
        if meta.get("question"):
            st.caption(f"Q: {meta.get('question')}")

    # Cards grid
    if cards:
        cols_per_row = 5 if len(cards) >= 5 else max(3, len(cards))
        rows = (len(cards) + cols_per_row - 1) // cols_per_row

        idx = 0
        for _ in range(rows):
            cols = st.columns(cols_per_row, gap="small")
            for col in cols:
                if idx >= len(cards):
                    break
                card = cards[idx]
                cap_lines = [f"**{card['card_name']}**", f"`{card['orientation']}`"]
                if card.get("position"):
                    cap_lines.append(f"pos: `{card['position']}`")
                caption = " · ".join(cap_lines)

                # Try absolute path from logic first
                p1 = card.get("image_path")
                # Fallback: relative to this streamlit.py location
                p2 = os.path.join(REPO_ROOT, "assets", "cards", f"{card['card_id']}.{image_ext}")

                chosen_path = None
                if p1 and os.path.isfile(p1):
                    chosen_path = p1
                elif os.path.isfile(p2):
                    chosen_path = p2

                if chosen_path:
                    col.image(chosen_path, caption=caption, use_column_width=True)
                    if show_paths:
                        col.caption(f"✓ {chosen_path}")
                else:
                    col.markdown(f"🖼️ *Image not found*\n\n{caption}")
                    if show_paths:
                        col.code(f"tried:\n{p1}\n{p2}")

                idx += 1

    # LLM response
    if meta.get("explain_with_llm"):
        st.markdown("---")
        st.subheader("LLM Explanation")
        if llm_block.get("error"):
            st.error(llm_block["error"])
        elif llm_block.get("response_text"):
            st.markdown(llm_block["response_text"])
        else:
            st.info("No LLM response.")

    # Debug / JSON
    with st.expander("Debug JSON"):
        st.json(result, expanded=False)

else:
    st.info("Set your options, optionally enter a question, then click **Draw cards**.")
