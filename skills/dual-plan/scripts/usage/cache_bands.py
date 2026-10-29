#!/usr/bin/env python3
"""Opus main-session cost split, cache rewrites, and $/call by context size (last N days)."""
import json, sys, time
from pathlib import Path
from datetime import datetime
DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 7
cut = time.time() - DAYS * 86400; seen = set()
tot = miss = 0.0; nmiss = 0; gaps = []; bands = {}; split = [0.0] * 4
def ts(s): return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
for f in (Path.home() / ".claude/projects").rglob("*.jsonl"):
    if "subagents" in f.parts or f.stat().st_mtime < cut: continue
    last = None
    for l in f.open(errors="ignore"):
        try: d = json.loads(l)
        except Exception: continue
        m = d.get("message")
        if d.get("type") != "assistant" or not isinstance(m, dict) or not m.get("usage"): continue
        if "opus" not in str(m.get("model")): continue
        k = d.get("requestId") or m.get("id")
        if k in seen: continue
        seen.add(k); u = m["usage"]
        try: t = ts(d["timestamp"])
        except Exception: continue
        if t < cut: continue
        v = [(u.get(x) or 0) for x in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")]
        p = [x * y / 1e6 for x, y in zip(v, (4, 5, .2, 20))]
        c = sum(p); tot += c; split = [a + b for a, b in zip(split, p)]
        ctx = v[0] + v[1] + v[2]
        b = min(int(ctx // 50000) * 50, 250); bands.setdefault(b, [0, 0.0]); bands[b][0] += 1; bands[b][1] += c
        if v[1] > 50000:
            miss += p[1]; nmiss += 1
            if last: gaps.append((t - last) / 60)
        last = t
print(f"Opus main cost ${tot:.2f}: input {split[0]/tot:.0%}, cache write {split[1]/tot:.0%}, cache read {split[2]/tot:.0%}, output {split[3]/tot:.0%}")
g = sorted(gaps)
print(f"big cache rewrites (>50k): {nmiss} calls, ${miss:.2f} = {miss/tot:.0%}; gap before: median {g[len(g)//2]:.0f} min, <5 min {sum(x<5 for x in g)}, >60 min {sum(x>60 for x in g)}")
print("context band  calls  avg $/call")
for b in sorted(bands): n, c = bands[b]; print(f"  {b:>3}k+   {n:5}   ${c/n:.3f}")
