"""Try ONE model on ONE question and show everything - before running all 30.

Usage: uv run python ping.py ollama:qwen3:8b Q01
       uv run python ping.py gemini:list          (list the Gemini models your key can use)
"""
import json
import sys
import time
import urllib.error
import urllib.request

import yaml

from answer import build_prompt, grade
from models import ROOT, get_model, load_env
from retrieve import Index


def list_gemini() -> None:
    import os
    load_env()
    req = urllib.request.Request("https://generativelanguage.googleapis.com/v1beta/models?pageSize=200",
                                 headers={"x-goog-api-key": os.environ.get("GEMINI_API_KEY", "")})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            models = json.loads(r.read())["models"]
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        msg = json.loads(body).get("error", {}).get("message", body[:200]) if body.startswith("{") else body[:200]
        print(f"Google refused the request (HTTP {e.code}): {msg}")
        print("Most likely the key in .env is wrong or has extra text. Re-copy it with the copy button.")
        sys.exit(1)
    for m in models:
        if "generateContent" in m.get("supportedGenerationMethods", []):
            print(" ", m["name"].removeprefix("models/"))


def main() -> None:
    if len(sys.argv) == 2 and sys.argv[1] == "gemini:list":
        return list_gemini()
    if len(sys.argv) != 3:
        print(__doc__); sys.exit(1)
    model_name, qid = sys.argv[1], sys.argv[2]
    entry = next(e for e in yaml.safe_load((ROOT / "ground_truth.yaml").read_text()) if e["id"] == qid)
    idx = Index(entry["doc"])
    shown = {p: idx.text[p] for p in idx.top(entry["question"])}
    messages = build_prompt(entry["question"], shown)
    chars = sum(len(m["content"]) for m in messages)
    print(f"Question {qid}: {entry['question']}")
    print(f"Right answer:  {entry['answer']}  (page {entry['page']})")
    print(f"Pages shown:   {sorted(shown)}   prompt size: {chars:,} characters (~{chars // 4:,} tokens)\n")
    m = get_model(model_name)
    t0 = time.time()
    print("Asking... (this can take a while; it prints the reason if it has to wait)", flush=True)
    try:
        reply = m.ask(messages)
    except Exception as ex:
        print(f"\nFAILED after {time.time() - t0:.0f}s: {ex}")
        sys.exit(1)
    print(f"Reply after {time.time() - t0:.1f}s:\n  {reply.strip()[:500]}\n")
    g = grade(entry, reply, shown)
    print(f"VERDICT: {g['verdict']}   {g['detail']}")


if __name__ == "__main__":
    main()
