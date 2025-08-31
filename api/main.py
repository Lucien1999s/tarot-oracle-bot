# api/main.py
from __future__ import annotations

import os
from typing import Optional, Literal, List, Dict, Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# 允許在 repo 根目錄直接啟動
import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.logic import perform_reading
from src import tarot_core

# ---------- Pydantic Schemas ----------
class ReadingRequest(BaseModel):
    num_cards: int = Field(..., ge=1, le=78)
    spread: Optional[str] = Field(None, description="single|three_card|five_card|celtic_cross or null")
    seed: Optional[str | int] = None
    orientation_prob: float = Field(0.5, ge=0.0, le=1.0)
    question: Optional[str] = None
    explain_with_llm: bool = False
    model: Optional[str] = None
    temperature: float = 0.2
    image_ext: Literal["png", "jpg", "webp"] = "png"

class HealthResponse(BaseModel):
    status: str
    version: str
    has_gemini_token: bool

# ---------- FastAPI app ----------
app = FastAPI(title="Tarot Oracle Bot API", version="0.1.0")

# CORS（方便前端/別人串）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"], allow_credentials=False
)

@app.get("/health", response_model=HealthResponse)
def health():
    return HealthResponse(
        status="ok",
        version=app.version,
        has_gemini_token=bool(os.getenv("GEMINI_TOKEN"))
    )

@app.get("/v1/spreads")
def list_spreads():
    return {"spreads": tarot_core.list_spreads()}

@app.post("/v1/readings")
def create_reading(req: ReadingRequest):
    result = perform_reading(
        num_cards=req.num_cards,
        spread=req.spread,
        seed=req.seed,
        orientation_prob=req.orientation_prob,
        question=req.question,
        explain_with_llm=req.explain_with_llm,
        model=req.model,
        temperature=req.temperature,
        image_ext=req.image_ext,
    )
    return result
