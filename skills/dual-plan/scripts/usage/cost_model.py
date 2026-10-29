#!/usr/bin/env python3
"""Replay the last N days of main sessions under four setups and price them.

  baseline  Opus runs everything (what actually happened)
  opt1      Sonnet main loop + Opus advisor
  opt2      Opus main loop, hook pushes chores (reads, builds, browser) to Haiku
  both      Sonnet main + Opus advisor + chore hook

Prices are API list $/1M (cache write = 1.25x input). Numbers only, no content.
"""
import json, re, sys, time
from pathlib import Path

DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 7
CUTOFF = time.time() - DAYS * 86400
ROOT = Path.home() / ".claude" / "projects"

P = {  # input, cache write, cache read, output
    "opus":   (4.00, 5.00, 0.20, 20.0),
    "sonnet": (2.00, 2.50, 0.20, 10.0),
    "haiku":  (0.10, 0.125, 0.01, 0.50),
}
# assumptions (tunable)
SONNET_EXTRA_TURNS = 1.15  # Sonnet takes ~15% more turns for the same work
ADVISOR_EVERY = 10         # Sonnet consults Opus on 1 in 10 non-chore turns
ADVISOR_OUT = 1500         # advisor reply tokens
BATCH = 5                  # chores handed to Haiku per delegation
REPORT = 400               # tokens of a Haiku report back into main context
DISPATCH_OUT = 300         # tokens Opus writes to brief the worker
WORKER_BASE = 25_000       # Haiku worker's starting context

def price(model, i, cw, cr, o):
    a, b, c, d = P[model]
    return (i * a + cw * b + cr * c + o * d) / 1e6

def is_chore(name, inp):
    if name == "Bash": return not re.search(r"\bcodex\b", inp.get("command") or "")
    return name in ("Read", "Grep", "Glob", "WebFetch") or name.startswith("mcp__Claude_Browser")

def est(c):
    if isinstance(c, str): return len(c) / 4
    if isinstance(c, list):
        return sum(1600 if isinstance(x, dict) and x.get("type") == "image"
                   else len(x.get("text", "") if isinstance(x, dict) else str(x)) / 4 for x in c)
    return len(json.dumps(c)) / 4

def load(f):
    calls, by_key, tools, seg, res = [], {}, {}, 0, {}
    for line in f.open(errors="ignore"):
        try: d = json.loads(line)
        except Exception: continue
        if d.get("type") == "system" and d.get("subtype") == "compact_boundary": seg += 1
        m = d.get("message")
        if not isinstance(m, dict): continue
        if d.get("type") == "assistant":
            key = d.get("requestId") or m.get("id")
            uses = [c for c in m.get("content") or [] if isinstance(c, dict) and c.get("type") == "tool_use"]
            for c in uses: tools[c.get("id")] = (c.get("name") or "?", c.get("input") or {})
            if key in by_key: by_key[key]["ids"] += [c.get("id") for c in uses]; continue
            u = m.get("usage")
            try: t = datetime_ts(d["timestamp"])
            except Exception: continue
            if not u or t < CUTOFF: continue
            c = dict(i=u.get("input_tokens") or 0, cw=u.get("cache_creation_input_tokens") or 0,
                     cr=u.get("cache_read_input_tokens") or 0, o=u.get("output_tokens") or 0,
                     seg=seg, ids=[x.get("id") for x in uses], model=str(m.get("model")))
            by_key[key] = c; calls.append(c)
        elif d.get("type") == "user" and isinstance(m.get("content"), list):
            for c in m["content"]:
                if isinstance(c, dict) and c.get("type") == "tool_result":
                    res[c.get("tool_use_id")] = est(c.get("content"))
    for c in calls:
        kinds = [is_chore(*tools.get(i, ("?", {}))) for i in c["ids"]]
        c["chore"] = bool(kinds) and all(kinds)
        c["chore_out"] = sum(res.get(i, 0) for i in c["ids"]) if c["chore"] else 0
    return calls

def datetime_ts(s):
    from datetime import datetime
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()

def simulate(calls, main, hook, advisor):
    cost = adv = haiku = 0.0
    carry = seg = 0; pending = core_n = 0
    for c in calls:
        if c["seg"] != seg: seg, carry = c["seg"], 0
        if hook and c["chore"]:
            # the chore runs in a Haiku worker; main pays dispatch + report per batch
            ctx_w = WORKER_BASE + pending * 3000
            haiku += price("haiku", c["i"], c["chore_out"] * 1.0, ctx_w, c["o"])
            carry += c["chore_out"]
            pending += 1
            if pending == BATCH:
                cr = max(c["cr"] - carry, 0)
                cost += 2 * price(main, c["i"], c["cw"] * 0.2, cr, 0) + price(main, 0, 0, 0, DISPATCH_OUT)
                carry -= REPORT; pending = 0
            continue
        cr = max(c["cr"] - carry, 0) if hook else c["cr"]
        k = SONNET_EXTRA_TURNS if main == "sonnet" else 1
        cost += k * price(main, c["i"], c["cw"], cr, c["o"])
        if advisor and not c["chore"]:
            core_n += 1
            if core_n % ADVISOR_EVERY == 0:  # Opus reads the whole context, half of it fresh
                ctx = c["i"] + c["cw"] + cr
                adv += price("opus", 0, ctx * 0.5, ctx * 0.5, ADVISOR_OUT)
    return cost, adv, haiku

rows = {"baseline": [0, 0, 0], "opt1": [0, 0, 0], "opt2": [0, 0, 0], "both": [0, 0, 0]}
sub_cost = 0.0; n_main = 0; chores = total = 0
for f in ROOT.rglob("*.jsonl"):
    if f.stat().st_mtime < CUTOFF: continue
    calls = load(f)
    if not calls: continue
    if "subagents" in f.parts:
        sub_cost += sum(price("haiku" if "haiku" in c["model"] else "opus", c["i"], c["cw"], c["cr"], c["o"]) for c in calls)
        continue
    n_main += 1; total += len(calls); chores += sum(c["chore"] for c in calls)
    for name, args in (("baseline", ("opus", False, False)), ("opt1", ("sonnet", False, True)),
                       ("opt2", ("opus", True, False)), ("both", ("sonnet", True, True))):
        for j, v in enumerate(simulate(calls, *args)): rows[name][j] += v

base = sum(rows["baseline"]) + sub_cost
print(f"last {DAYS} days, {n_main} main sessions, {total} main calls, {chores/total:.0%} of them pure chores")
print(f"existing Haiku subagents: ${sub_cost:,.2f} (same in every setup)\n")
print(f"{'setup':9} {'main':>9} {'advisor':>8} {'haiku':>7} {'total':>9} {'vs now':>7}")
for name, (m, a, h) in rows.items():
    t = m + a + h + sub_cost
    print(f"{name:9} ${m:8,.2f} ${a:7,.2f} ${h:6,.2f} ${t:8,.2f} {t/base - 1:+7.0%}")
