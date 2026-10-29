#!/usr/bin/env python3
"""Codex CLI token usage per week and model, from ~/.codex/sessions (last N days).

  codex_usage.py [days]     # default 21

Reads only token_count events and the model name; never prints prompts, paths or ids.
Also prints the latest ChatGPT-plan rate-limit usage Codex recorded.
"""
import json, sys, time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 21
CUTOFF = time.time() - DAYS * 86400
ROOT = Path.home() / ".codex" / "sessions"
FIELDS = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")

def ts(s):
    try: return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception: return None

rows = defaultdict(lambda: defaultdict(int))  # (week, model) -> field -> tokens
runs = defaultdict(set)
limits = (0, None)
for f in ROOT.rglob("*.jsonl"):
    if f.stat().st_mtime < CUTOFF: continue
    model = "?"
    for line in f.open(errors="ignore"):
        try: d = json.loads(line)
        except Exception: continue
        p = d.get("payload") or {}
        if p.get("model"): model = str(p["model"])
        if p.get("type") != "token_count": continue
        t = ts(d.get("timestamp") or "")
        if t is None or t < CUTOFF: continue
        u = (p.get("info") or {}).get("last_token_usage") or {}
        week = datetime.fromtimestamp(t).strftime("%G-W%V")
        for k in FIELDS: rows[week, model][k] += u.get(k) or 0
        runs[week, model].add(f.name)
        if p.get("rate_limits") and t > limits[0]: limits = (t, p["rate_limits"])

print(f"Codex, last {DAYS} days (tokens in millions; input excludes cached)")
print(f"{'week':9} {'model':22} {'runs':>5} {'input':>7} {'cached':>8} {'output':>7} {'reason':>7}")
for (week, model), v in sorted(rows.items()):
    fresh = v["input_tokens"] - v["cached_input_tokens"]
    print(f"{week:9} {model[:22]:22} {len(runs[week, model]):>5} {fresh/1e6:7.2f} "
          f"{v['cached_input_tokens']/1e6:8.2f} {v['output_tokens']/1e6:7.2f} {v['reasoning_output_tokens']/1e6:7.2f}")
if limits[1]:
    for name in ("primary", "secondary"):
        w = limits[1].get(name) or {}
        if w: print(f"latest {name} limit ({(w.get('window_minutes') or 0)//60}h window): {w.get('used_percent')}% used")
