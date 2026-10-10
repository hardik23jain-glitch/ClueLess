"""
Step 5a: the vision model, behind ONE small interface.

`VisionProvider.read(images, system, user) -> str` returns the model's raw JSON
text. Nothing else in the pipeline knows which vendor is used, so switching
to a self-hosted model later (a privacy requirement for production) is a
config change, not a rewrite.

Providers
---------
gemini     google-genai (same call shape as the MediKiosk vision_llm.py)
anthropic  Claude vision
mock       reads data/mock/<doc_id>.json: tests, offline demo, no network
"""

from __future__ import annotations

import base64
import json
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from .config import Config


def encode_jpeg(img: np.ndarray, quality: int) -> bytes:
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise ValueError("JPEG encoding failed")
    return buf.tobytes()


class ProviderError(RuntimeError):
    pass


class VisionProvider(ABC):
    name = "base"
    model = ""

    @abstractmethod
    def read(self, images: list[np.ndarray], system: str, user: str, doc_id: str = "") -> str:
        """Return the model's raw text (expected to be JSON)."""


class GeminiProvider(VisionProvider):
    name = "gemini"

    def __init__(self, cfg: Config):
        key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not key:
            raise ProviderError("GEMINI_API_KEY is not set")
        from google import genai

        self.client = genai.Client(api_key=key)
        self.cfg = cfg
        self.model = cfg.gemini_model

    def read(self, images, system, user, doc_id=""):
        from google.genai import types

        parts = []
        for i, img in enumerate(images, 1):
            parts.append(types.Part.from_text(text=f"Page {i}:"))
            parts.append(types.Part.from_bytes(data=encode_jpeg(img, self.cfg.jpeg_quality), mime_type="image/jpeg"))
        parts.append(types.Part.from_text(text=user))
        resp = self.client.models.generate_content(
            model=self.model,
            contents=[types.Content(role="user", parts=parts)],
            config=types.GenerateContentConfig(
                temperature=self.cfg.temperature,
                max_output_tokens=self.cfg.max_output_tokens,
                response_mime_type="application/json",
                system_instruction=system,
                thinking_config=types.ThinkingConfig(thinking_budget=self.cfg.gemini_thinking_budget),
            ),
        )
        # A cut-off reply must be reported as such, never parsed as if it were whole.
        cand = resp.candidates[0] if resp.candidates else None
        reason = str(getattr(cand, "finish_reason", "")).upper()
        if "MAX_TOKENS" in reason:
            raise ProviderError("model reply was cut off (MAX_TOKENS); raise max_output_tokens or lower the thinking budget")
        return resp.text or "{}"


class AnthropicProvider(VisionProvider):
    name = "anthropic"

    def __init__(self, cfg: Config):
        key = os.getenv("ANTHROPIC_API_KEY")
        if not key:
            raise ProviderError("ANTHROPIC_API_KEY is not set")
        import anthropic

        self.client = anthropic.Anthropic(api_key=key)
        self.cfg = cfg
        self.model = cfg.anthropic_model

    def read(self, images, system, user, doc_id=""):
        content = []
        for i, img in enumerate(images, 1):
            content.append({"type": "text", "text": f"Page {i}:"})
            content.append({"type": "image", "source": {
                "type": "base64", "media_type": "image/jpeg",
                "data": base64.b64encode(encode_jpeg(img, self.cfg.jpeg_quality)).decode()}})
        content.append({"type": "text", "text": user})
        resp = self.client.messages.create(
            model=self.model, max_tokens=min(self.cfg.max_output_tokens, 16000),
            temperature=self.cfg.temperature, system=system,
            messages=[{"role": "user", "content": content}],
        )
        return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")


class MockProvider(VisionProvider):
    """Serves a canned model response from data/mock/<doc_id>.json."""
    name = "mock"
    model = "mock-v1"

    def __init__(self, cfg: Config):
        self.dir = Path(cfg.mock_dir)

    def read(self, images, system, user, doc_id=""):
        f = self.dir / f"{doc_id}.json"
        if not f.exists():
            raise ProviderError(f"No mock response at {f}")
        return f.read_text(encoding="utf-8")


_TRANSIENT = ("503", "429", "500", "502", "504", "unavailable", "overloaded", "timed out", "timeout",
              "rate limit", "resource_exhausted", "deadline")


def read_with_retry(provider: VisionProvider, images, system: str, user: str, doc_id: str = "",
                    attempts: int = 3) -> str:
    """Retry transient API failures (503/429/timeouts) with backoff; fail fast on anything else."""
    import time

    for i in range(attempts):
        try:
            return provider.read(images, system, user, doc_id=doc_id)
        except ProviderError:
            raise
        except Exception as e:
            if i == attempts - 1 or not any(t in str(e).lower() for t in _TRANSIENT):
                raise
            time.sleep(3 * (i + 1) ** 2)       # 3s, 12s


def get_provider(cfg: Config) -> VisionProvider:
    table = {"gemini": GeminiProvider, "anthropic": AnthropicProvider, "mock": MockProvider}
    if cfg.provider not in table:
        raise ProviderError(f"Unknown provider '{cfg.provider}'")
    return table[cfg.provider](cfg)
