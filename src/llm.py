from __future__ import annotations
import os
from typing import Optional
from dotenv import load_dotenv

# pip install google-generativeai python-dotenv
import google.generativeai as genai

load_dotenv()
GEMINI_TOKEN = os.getenv("GEMINI_TOKEN")
DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


def _extract_text(resp) -> str:
    """
    Safely extract plain text from a Gemini response, even if Parts are present.
    """
    # 1) Try the SDK's aggregated .text
    try:
        t = getattr(resp, "text", None)
        if t:
            return t
    except Exception:
        pass

    # 2) Fallback: manually join candidate parts' text
    try:
        texts = []
        for cand in getattr(resp, "candidates", []) or []:
            content = getattr(cand, "content", None)
            parts = getattr(content, "parts", None) if content else None
            if parts:
                for p in parts:
                    pt = getattr(p, "text", None)
                    if pt:
                        texts.append(pt)
        return "\n".join(texts).strip()
    except Exception:
        return ""


def chat(prompt: str, model: Optional[str] = None, temperature: float = 0.2) -> str:
    """
    Simple chat with Gemini. Returns plain text. Raises if API/key error.
    Compatible with multiple google-generativeai SDK versions.
    """
    if not GEMINI_TOKEN:
        raise RuntimeError(
            "Missing GEMINI_TOKEN in environment. "
            "Create one in Google AI Studio and set it in your .env."
        )

    genai.configure(api_key=GEMINI_TOKEN)
    model_name = model or DEFAULT_MODEL
    gmodel = genai.GenerativeModel(model_name=model_name)

    gen_cfg = {"temperature": float(temperature)}

    # First attempt (newer SDKs may accept extra fields; older ones won't)
    try:
        resp = gmodel.generate_content(prompt, generation_config=gen_cfg)
    except Exception as e:
        # If any config-related error surfaces, retry without generation_config
        # to maximize compatibility with older SDKs.
        if "GenerationConfig" in str(e) or "generation_config" in str(e):
            resp = gmodel.generate_content(prompt)
        else:
            raise

    text = _extract_text(resp)
    return text or ""
