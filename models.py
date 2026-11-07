"""Models the runner can ask. Every model has a name and ask(messages) -> reply text.

Fake models (free, instant, fully predictable) come first. They let us test the whole
pipeline before spending money:
  fake-old  answers every question correctly (it reads the answer key). If it does
            not score 100%, the PIPELINE has a bug, not the model.
  fake-new  same, but deliberately broken on a few questions in realistic ways - the
            "newer model" whose swap the gate must refuse.
Real models (OpenRouter) are added in step 3.
"""
from __future__ import annotations

import json
import re

import yaml
from pathlib import Path

ROOT = Path(__file__).parent
NUM_WITH_SIGN = re.compile(r"[-−(]?\d[\d.,']*\d?\)?")


def _truth_reply(entry: dict) -> dict:
    """What a perfect model would reply for this answer-key entry."""
    if entry["type"] == "text":
        return {"raw_value": entry["answer"], "unit": "", "source_quote": entry["quote"], "page": entry["page"]}
    m = NUM_WITH_SIGN.search(entry["answer"])
    raw = m.group()
    unit = (entry["answer"][: m.start()] + " " + entry["answer"][m.end():]).replace("$", "$ ").split()
    return {"raw_value": raw, "unit": " ".join(unit), "source_quote": entry["quote"], "page": entry["page"]}


class FakeModel:
    # question id -> how fake-new gets it wrong. "flaky" = wrong on the 2nd of every 3 asks.
    BREAKS = {
        "Q04": lambda r: {**r, "unit": "$ million"},                       # header scale applied to EPS
        "Q12": lambda r: {**r, "unit": "%"},                               # % instead of pp
        "Q15": lambda r: {**r, "raw_value": r["raw_value"].lstrip("−-")},  # minus sign dropped
        "Q22": lambda r: {**r, "source_quote": "Adjusted EBITDA reached a record 903.0"},  # made-up quote
    }
    FLAKY = {"Q20"}

    def __init__(self, name: str):
        self.name = name
        gt = yaml.safe_load((ROOT / "ground_truth.yaml").read_text(encoding="utf-8"))
        self.by_question = {e["question"]: e for e in gt}
        self.calls = {}

    def ask(self, messages: list[dict]) -> str:
        content = messages[-1]["content"]
        question = content.rsplit("Question: ", 1)[-1].strip()
        entry = self.by_question[question]
        reply = _truth_reply(entry)
        # Like a real model, it can only cite pages it was SHOWN. If the official page is
        # not among them, cite the first shown page that contains the value, quoting its line.
        shown = {int(n): t for n, t in re.findall(r"=== PAGE (\d+) ===\n(.*?)(?=\n\n=== PAGE |\n\nQuestion: )", content, re.S)}
        if entry["page"] not in shown:
            needle = reply["raw_value"]
            for page, text in shown.items():
                line = next((l for l in text.splitlines() if needle in l), None)
                if line:
                    reply = {**reply, "page": page, "source_quote": " ".join(line.split())}
                    break
        n = self.calls[entry["id"]] = self.calls.get(entry["id"], 0) + 1
        if self.name == "fake-new":
            if entry["id"] in self.BREAKS:
                reply = self.BREAKS[entry["id"]](reply)
            if entry["id"] in self.FLAKY and n % 3 == 2:
                reply = {**reply, "raw_value": "903.0"}   # occasionally grabs a neighbouring figure
        return json.dumps(reply, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Real models. Every call has a timeout; failures raise ModelError, which the
# runner records as verdict "error" instead of crashing or hanging.
# ---------------------------------------------------------------------------
import os
import time
import urllib.error
import urllib.request

# The structure every model must reply in (same fields answer.py checks).
ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "raw_value": {"type": ["string", "null"]},
        "unit": {"type": "string"},
        "source_quote": {"type": "string"},
        "page": {"type": ["integer", "null"]},
    },
    "required": ["raw_value", "unit", "source_quote", "page"],
}


class ModelError(RuntimeError):
    pass


def load_env() -> None:
    """Read KEY=value lines from .env into the environment (no extra library).
    .env is git-ignored, so keys never end up in the project history."""
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _post_json(url: str, body: dict, headers: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        raise ModelError(f"HTTP {e.code}: {detail}") from None
    except (urllib.error.URLError, TimeoutError) as e:
        raise ModelError(f"no response ({e}) - is the service running?") from None


class OllamaModel:
    """A model running locally on this Mac through Ollama (free, no limits)."""
    URL = "http://localhost:11434/api/chat"
    NUM_CTX = 16384   # how much text the model may read. Set explicitly: the default
                      # is smaller and Ollama would SILENTLY cut the start of our prompt.

    def __init__(self, model: str, timeout: float = 300):
        self.model, self.timeout = model, timeout
        self.name = f"ollama:{model}"

    def ask(self, messages: list[dict]) -> str:
        body = {
            "model": self.model, "messages": messages, "stream": False,
            "format": ANSWER_SCHEMA,                 # Ollama constrains output to our structure
            "options": {"num_ctx": self.NUM_CTX},
        }
        if self.model.startswith("qwen"):
            body["think"] = False                    # no long reasoning text before the answer
        r = _post_json(self.URL, body, {}, self.timeout)
        read = r.get("prompt_eval_count") or 0
        if read >= self.NUM_CTX - 64:
            raise ModelError(f"prompt cut off: model read {read} tokens, window is {self.NUM_CTX}")
        return r.get("message", {}).get("content", "")


class GeminiModel:
    """Google's Gemini through the free API tier. Key comes from GEMINI_API_KEY in .env."""
    BASE = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self, model: str, timeout: float = 120, min_gap: float = 7.0, retries: int = 3):
        load_env()
        self.key = os.environ.get("GEMINI_API_KEY", "")
        if not self.key:
            raise ModelError("GEMINI_API_KEY missing - put it in the .env file")
        self.model, self.timeout, self.min_gap, self.retries = model, timeout, min_gap, retries
        self.name = f"gemini:{model}"
        self._last = 0.0

    def ask(self, messages: list[dict]) -> str:
        system = next(m["content"] for m in messages if m["role"] == "system")
        user = next(m["content"] for m in messages if m["role"] == "user")
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"responseMimeType": "application/json"},
        }
        for attempt in range(1, self.retries + 1):
            wait = self.min_gap - (time.time() - self._last)   # stay under the free per-minute limit
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()
            try:
                r = _post_json(f"{self.BASE}/{self.model}:generateContent",
                               body, {"x-goog-api-key": self.key}, self.timeout)
                parts = r["candidates"][0]["content"]["parts"]
                return "".join(p.get("text", "") for p in parts)
            except ModelError as e:
                # 429 = too many requests: wait and retry, but only a few times (retries
                # that never stop can burn the whole daily allowance).
                if "HTTP 429" in str(e) and attempt < self.retries:
                    time.sleep(30 * attempt)
                    continue
                raise
            except (KeyError, IndexError):
                raise ModelError(f"unexpected reply shape: {str(r)[:200]}") from None
        raise ModelError("gave up after retries")


def get_model(name: str):
    """'fake-old', 'ollama:qwen3:8b', 'gemini:gemini-2.5-flash', ..."""
    if name in ("fake-old", "fake-new"):
        return FakeModel(name)
    provider, _, model = name.partition(":")
    if provider == "ollama" and model:
        return OllamaModel(model)
    if provider == "gemini" and model:
        return GeminiModel(model)
    raise ValueError(f"unknown model {name!r}. Use fake-old, fake-new, ollama:<model> or gemini:<model>")
