"""The grid: models across, questions down - readable in two seconds.

Usage: uv run python report.py <old model> <new model> [more models...]
       e.g. uv run python report.py ollama:qwen3:8b ollama:qwen3.5:9b

Prints the grid in the terminal and writes report.html (open it with: open report.html).
Uses the latest run of each model. The first two models are compared with the gate's rule;
any further models are shown for context only.
"""
from __future__ import annotations

import datetime
import html
import re
import sqlite3
import sys
from pathlib import Path

import yaml

from gate import decide, latest_runs, statuses

ROOT = Path(__file__).parent
DOC = {"zalando_2025": "Zalando", "deliveryhero_2025": "Delivery Hero", "apple_10k_2025": "Apple"}
ICON = {"reliable": "✓", "unreliable": "~", "fails": "✗", "inconclusive": "?"}
ANSI = {"reliable": "\033[32m", "unreliable": "\033[33m", "fails": "\033[31m", "inconclusive": "\033[90m"}
RESET, BOLD = "\033[0m", "\033[1m"


# Display labels only. Kept here, NOT in ground_truth.yaml: editing that file changes its
# fingerprint, and the gate would rightly refuse to compare runs graded against "another key".
LABELS = {
    "Q01": "Revenue 2025", "Q02": "EBIT 2025", "Q03": "Total net sales", "Q04": "Diluted EPS",
    "Q05": "Basic EPS shares (thousands)", "Q06": "Total assets", "Q07": "Cash & equivalents",
    "Q08": "Operating cash flow", "Q09": "Investing cash flow (negative)", "Q10": "Active customers",
    "Q11": "GMV", "Q12": "EBIT margin change (pp)", "Q13": "Average employees",
    "Q14": "Revenue (IFRS)", "Q15": "Net result (loss)", "Q16": "EPS (negative)",
    "Q17": "Operating result (negative)", "Q18": "Total assets", "Q19": "Cash & equivalents",
    "Q20": "Group GMV", "Q21": "Total Segment Revenue", "Q22": "Adjusted EBITDA",
    "Q23": "Asia GMV change (negative %)", "Q24": "Total assets", "Q25": "Cash & equivalents",
    "Q26": "Employees (FTE, approx.)", "Q27": "Greater China net sales", "Q28": "Greater China change (4)%",
    "Q29": "Highest-sales segment (text)", "Q30": "Fastest-growing segment (text)",
}


def short_label(e: dict) -> str:
    if e["id"] in LABELS:
        return LABELS[e["id"]]
    return _auto_label(e)


def _auto_label(e: dict) -> str:
    """'What was Apple's diluted earnings per share for fiscal year 2025?' -> 'diluted earnings per share'"""
    q = e["question"]
    q = re.sub(r"^(What (was|were)|How many shares did|By (how many|what) [a-z ]+? did|"
               r"Approximately how many|Which of)\s+", "", q)
    q = re.sub(r"(Zalando|Delivery Hero|Apple)('s)?\s*", "", q)
    q = re.split(r",| for | as of | in the | at the | in fiscal| to compute| from 2024| according", q)[0]
    return q.strip(" ?").replace("'s", "")[:38]


def main() -> int:
    models = sys.argv[1:]
    if len(models) < 2:
        print(__doc__); return 2
    db = sqlite3.connect(ROOT / "runs.db")
    entries = {e["id"]: e for e in yaml.safe_load((ROOT / "ground_truth.yaml").read_text(encoding="utf-8"))}
    runs, st = {}, {}
    for m in models:
        r = latest_runs(db, m)
        if not r:
            print(f"No results for {m}. Run it first."); return 2
        runs[m] = r[0]
        st[m] = statuses(db, r[0], m)
    shas = {db.execute("SELECT ground_truth_sha256 FROM runs WHERE run_id=?", (r,)).fetchone()[0] for r in runs.values()}
    if len(shas) != 1:
        print("REFUSED - these runs used different answer keys; re-run them before comparing."); return 1

    old, new = models[0], models[1]
    d = decide(st[old], st[new])
    reg, imp, unk = set(d["regressions"]), set(d["improvements"]), set(d["unknown"])
    decision = "REFUSED" if reg else "INCONCLUSIVE" if unk else "APPROVED"
    qids = sorted(entries)

    # ---------------- terminal ----------------
    names = [m.split(":", 1)[-1] for m in models]
    w = max(len(n) for n in names) + 2
    print(f"\n{BOLD}swapgate  {old}  ->  {new}{RESET}\n")
    print(f"{'':52}" + "".join(f"{n:^{w}}" for n in names))
    for q in qids:
        e = entries[q]
        label = f"{q}  {DOC[e['doc']]:13} {short_label(e)}"[:51]
        cells = "".join(f"{ANSI[st[m][q]['status']]}{ICON[st[m][q]['status']] + ' ' + st[m][q]['score']:^{w}}{RESET}" for m in models)
        flag = f"{ANSI['fails']}{BOLD}  ◀ REGRESSION{RESET}" if q in reg else "  ↑ improved" if q in imp else "  ? re-run" if q in unk else ""
        print(f"{label:52}{cells}{flag}")
    print(f"\n  ✓ reliable (3/3)   ~ unreliable   ✗ fails   ? server error\n")
    colour = ANSI["fails"] if reg else ANSI["unreliable"] if unk else ANSI["reliable"]
    print(f"{colour}{BOLD}SWAP {decision}{RESET}  - kept {len(d['kept'])}, regressions {len(reg)}, "
          f"improvements {len(imp)}, inconclusive {len(unk)}\n")

    # ---------------- html ----------------
    def cell(m, q):
        s = st[m][q]
        ex = s["examples"][0] if s["examples"] else None
        tip = f"{m}: {s['score']} right"
        if ex:
            tip += f" | said {ex[1]!r} {ex[2] or ''} -> {ex[0]}: {ex[3]}"
        regc = " regcell" if (q in reg and m == new) else ""
        return (f'<td class="c {s["status"]}{regc}" title="{html.escape(tip)}">'
                f'<span class="i">{ICON[s["status"]]}</span> {s["score"]}</td>')

    rows = []
    for q in qids:
        e = entries[q]
        flag = ('<span class="flag reg">◀ regression</span>' if q in reg else
                '<span class="flag imp">↑ improved</span>' if q in imp else
                '<span class="flag unk">? re-run</span>' if q in unk else "")
        rows.append(f'<tr{" class=regrow" if q in reg else ""}><th scope="row"><span class="qid">{q}</span> '
                    f'<span class="doc">{DOC[e["doc"]]}</span> {html.escape(short_label(e))}</th>'
                    + "".join(cell(m, q) for m in models) + f"<td>{flag}</td></tr>")

    details = []
    for q in sorted(reg):
        e, s = entries[q], st[new][q]
        verdict, raw, unit, detail = s["examples"][0]
        value_ok = verdict in ("loose_quote", "bad_citation")   # value right, only the evidence failed
        vcls, vnote = ("v", " <span class=why>(value correct)</span>") if value_ok else ("v bad", "")
        details.append(
            f'<div class="reg-card"><div class="rc-head"><span class="qid">{q}</span> {html.escape(e["question"])}</div>'
            f'<div class="rc-grid"><div><div class="k">Answer key (verified in the PDF, p.{e["page"]})</div>'
            f'<div class="v">{html.escape(e["answer"])}</div></div>'
            f'<div><div class="k">{html.escape(old)}</div><div class="v ok">✓ {st[old][q]["score"]} right</div></div>'
            f'<div><div class="k">{html.escape(new)} said</div><div class="{vcls}">{html.escape(str(raw))} {html.escape(unit or "")}{vnote}</div>'
            f'<div class="why">{html.escape(verdict)}: {html.escape(detail)}</div></div></div></div>')

    banner = {"REFUSED": "critical", "INCONCLUSIVE": "warning", "APPROVED": "good"}[decision]
    page = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>swapgate - {html.escape(old)} → {html.escape(new)}</title>
<style>
:root{{--surface:#fcfcfb;--plane:#f9f9f7;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;--line:#e1e0d9;
--good:#0ca30c;--warning:#fab219;--critical:#d03b3b;--neutral:#c3c2b7;--goodtext:#006300}}
@media (prefers-color-scheme:dark){{:root{{--surface:#1a1a19;--plane:#0d0d0d;--ink:#f0efec;--ink2:#c3c2b7;
--line:#2c2c2a;--neutral:#383835;--goodtext:#0ca30c}}}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--plane);color:var(--ink);
font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:1040px;margin:0 auto;padding:32px 20px 48px}}
h1{{font-size:20px;margin:0 0 4px}} .sub{{color:var(--ink2);margin:0 0 20px}}
.banner{{display:flex;align-items:center;gap:14px;padding:16px 18px;border-radius:10px;background:var(--surface);
border:1px solid var(--line);border-left:6px solid var(--{banner});margin-bottom:16px}}
.banner .big{{font-size:22px;font-weight:700}} .banner .txt{{color:var(--ink2)}}
.tiles{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:22px}}
.tile{{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:12px 14px}}
.tile .n{{font-size:26px;font-weight:700}} .tile .l{{color:var(--ink2);font-size:12px}}
table{{width:100%;border-collapse:separate;border-spacing:3px;background:var(--surface);border:1px solid var(--line);
border-radius:10px;padding:8px}}
thead th{{font-size:12px;color:var(--ink2);font-weight:600;text-align:center;padding:6px 8px}}
thead th:first-child{{text-align:left}}
tbody th{{text-align:left;font-weight:400;padding:5px 8px;white-space:nowrap}}
.qid{{font-variant-numeric:tabular-nums;font-weight:600}} .doc{{color:var(--muted);font-size:12px;margin:0 4px}}
td.c{{text-align:center;font-variant-numeric:tabular-nums;padding:5px 8px;border-radius:4px;color:#fff;font-weight:600;
min-width:120px;cursor:help}}
td.reliable{{background:var(--good)}} td.unreliable{{background:var(--warning);color:#0b0b0b}}
td.fails{{background:var(--critical)}} td.inconclusive{{background:var(--neutral);color:var(--ink)}}
td.c .i{{display:inline-block;width:1.1em}}
td.regcell{{outline:3px solid var(--ink);outline-offset:-3px}}
tr.regrow th{{font-weight:600}}
.flag{{font-size:12px;white-space:nowrap;padding-left:8px}} .flag.reg{{color:var(--critical);font-weight:700}}
.flag.imp{{color:var(--goodtext)}} .flag.unk{{color:var(--muted)}}
.legend{{display:flex;gap:16px;flex-wrap:wrap;color:var(--ink2);font-size:12px;margin:10px 2px 26px}}
.sw{{display:inline-block;width:12px;height:12px;border-radius:3px;vertical-align:-1px;margin-right:5px}}
h2{{font-size:16px;margin:0 0 10px}}
.reg-card{{background:var(--surface);border:1px solid var(--line);border-left:6px solid var(--critical);
border-radius:10px;padding:14px 16px;margin-bottom:10px}}
.rc-head{{margin-bottom:10px}} .rc-grid{{display:grid;grid-template-columns:1.2fr 1fr 1.6fr;gap:14px}}
.k{{color:var(--muted);font-size:12px}} .v{{font-weight:600}} .v.ok{{color:var(--goodtext)}} .v.bad{{color:var(--critical)}}
.why{{color:var(--ink2);font-size:12px;margin-top:2px}}
footer{{color:var(--muted);font-size:12px;margin-top:26px}}
@media (max-width:700px){{.tiles{{grid-template-columns:repeat(2,1fr)}} .rc-grid{{grid-template-columns:1fr}}}}
</style></head><body><main>
<h1>Model swap check: {html.escape(old)} → {html.escape(new)}</h1>
<p class="sub">30 hand-verified questions on 3 public annual reports (Zalando, Delivery Hero, Apple). Each question asked 3 times per model.</p>
<div class="banner"><span class="big">SWAP {decision}</span><span class="txt">{
    f"{len(reg)} question(s) the old model answered reliably are no longer answered reliably." if reg else
    "Some answers could not be judged (server errors) - re-run them." if unk else
    "Everything the old model answered reliably, the new model still does."}</span></div>
<div class="tiles">
<div class="tile"><div class="n">{len(d["kept"])}</div><div class="l">still reliable</div></div>
<div class="tile"><div class="n" style="color:var(--critical)">{len(reg)}</div><div class="l">regressions</div></div>
<div class="tile"><div class="n" style="color:var(--goodtext)">{len(imp)}</div><div class="l">improvements</div></div>
<div class="tile"><div class="n">{len(unk)}</div><div class="l">inconclusive</div></div></div>
{"<h2>What broke</h2>" + "".join(details) if details else ""}
<h2 style="margin-top:22px">All questions</h2>
<table><thead><tr><th scope="col">Question</th>{"".join(f'<th scope="col">{html.escape(m)}</th>' for m in models)}<th></th></tr></thead>
<tbody>{"".join(rows)}</tbody></table>
<div class="legend"><span><span class="sw" style="background:var(--good)"></span>✓ reliable - right 3/3</span>
<span><span class="sw" style="background:var(--warning)"></span>~ unreliable - right sometimes</span>
<span><span class="sw" style="background:var(--critical)"></span>✗ fails - right 0/3</span>
<span><span class="sw" style="background:var(--neutral)"></span>? server error - re-run</span>
<span>Hover a cell for the model's answer.</span></div>
<footer>Rule: every question the old model answers reliably must still be answered reliably by the new one.
Runs {", ".join(f"{html.escape(m)} #{r}" for m, r in runs.items())} · answer key sha256 {list(shas)[0][:12]}… ·
generated {datetime.datetime.now():%Y-%m-%d %H:%M}</footer>
</main></body></html>"""
    (ROOT / "report.html").write_text(page, encoding="utf-8")
    print("Wrote report.html  (open it with: open report.html)")
    return 1 if reg else 2 if unk else 0


if __name__ == "__main__":
    sys.exit(main())
