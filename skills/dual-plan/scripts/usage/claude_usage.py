#!/usr/bin/env python3
"""Rank token-burning habits in Claude Code session logs (last N days).

Prints aggregate numbers only: never commands, file paths, or message text.

Usage is "weighted tokens" so cheap cache reads don't swamp everything:
  input x1, cache write x1.25, cache read x0.1, output x5  (API price ratios).

A tool result is charged what it costs to carry: one cache write, then a
cache read on every later API call in the same context (until compaction).
"""
import json, re, sys, time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 7
ROOT = Path.home() / ".claude" / "projects"
CUTOFF = time.time() - DAYS * 86400
W = dict(input_tokens=1.0, cache_creation_input_tokens=1.25,
         cache_read_input_tokens=0.1, output_tokens=5.0)
BIG = 2000            # tokens: a tool result above this counts as "big"
LONG_SESSION_H = 2    # hours: calls after this point count as "long session"
HUGE_CTX = 150_000    # tokens of context per call

BASH_KINDS = [
    ("test", r"\b(pytest|jest|vitest|mocha|go test|cargo test|npm (run )?test|pnpm (run )?test|yarn test|bun test|xcodebuild test|swift test)\b"),
    ("build", r"\b(build|tsc|webpack|vite|next build|cargo build|xcodebuild|gradle|make|swift build|tauri)\b"),
    ("install", r"\b(npm (i|install|ci)|pnpm (i|install|add)|yarn( add| install)?|pip3? install|brew install|bun (i|install|add))\b"),
    ("codex/worker", r"\bcodex\b"),
    ("logs/cat", r"\b(cat|tail|head|less|journalctl|log show)\b"),
    ("git", r"\bgit\b"),
    ("search", r"\b(grep|rg|find|ls)\b"),
]

def ts(s):
    try: return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception: return None

def est(content):  # ~4 chars/token; images ~1.6k tokens each
    if isinstance(content, str): return len(content) / 4
    if isinstance(content, list):
        t = 0
        for c in content:
            if isinstance(c, dict) and c.get("type") == "image": t += 1600
            elif isinstance(c, dict) and "text" in c: t += len(c["text"]) / 4
            else: t += len(json.dumps(c)) / 4
        return t
    return len(json.dumps(content)) / 4

def bash_kind(cmd):
    for k, rx in BASH_KINDS:
        if re.search(rx, cmd or ""): return k
    return "other"

tot = defaultdict(float)
cat = defaultdict(float)   # habit -> weighted tokens
cnt = defaultdict(int)
mod = defaultdict(float)  # (main|sub, model) -> weighted tokens
both = 0.0
sub_files = main_files = 0

for f in ROOT.rglob("*.jsonl"):
    if f.stat().st_mtime < CUTOFF: continue
    is_sub = "subagents" in f.parts
    calls, results, seen = [], [], set()
    tools, first_ts, sidechain = {}, None, False
    segment = 0
    for line in f.open(errors="ignore"):
        try: d = json.loads(line)
        except Exception: continue
        t = ts(d.get("timestamp") or "")
        if d.get("type") == "system" and d.get("subtype") == "compact_boundary":
            segment += 1
        m = d.get("message")
        if not isinstance(m, dict): continue
        if d.get("isSidechain"): sidechain = True
        if d.get("type") == "assistant":
            for c in m.get("content") or []:
                if isinstance(c, dict) and c.get("type") == "tool_use":
                    tools[c.get("id")] = (c.get("name"), c.get("input") or {})
            u = m.get("usage")
            key = d.get("requestId") or m.get("id")
            if not u or key in seen or t is None or t < CUTOFF: continue
            seen.add(key)
            w = sum(W[k] * (u.get(k) or 0) for k in W)
            ctx = sum(u.get(k) or 0 for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
            first_ts = first_ts or t
            calls.append((t, w, ctx, segment, len(calls)))
            model = re.sub(r"-\d{8}$", "", str(m.get("model") or "?"))
            mod["sub" if ("subagents" in f.parts or d.get("isSidechain")) else "main", model] += w
        elif d.get("type") == "user" and isinstance(m.get("content"), list):
            for c in m["content"]:
                if isinstance(c, dict) and c.get("type") == "tool_result" and t and t >= CUTOFF:
                    results.append((len(calls), segment, c.get("tool_use_id"), est(c.get("content"))))
    if not calls: continue
    is_sub = is_sub or sidechain
    sub_files += is_sub; main_files += not is_sub
    fw = sum(c[1] for c in calls)
    tot["all"] += fw
    if is_sub:
        cat["subagent runs (whole sidechain)"] += fw; cnt["subagent runs (whole sidechain)"] += 1
    else:
        for t, w, ctx, _, _ in calls:
            if t - first_ts > LONG_SESSION_H * 3600:
                cat[f"session past {LONG_SESSION_H}h (all calls)"] += w
            if ctx > HUGE_CTX and t - first_ts > LONG_SESSION_H * 3600: both += w
            if ctx > HUGE_CTX:
                cat[f"calls with >{HUGE_CTX//1000}k context"] += w
    # carry cost of each tool result
    for idx, seg, tid, tok in results:
        later = sum(1 for c in calls[idx:] if c[3] == seg)
        cost = tok * 1.25 + tok * 0.1 * later
        name, inp = tools.get(tid, ("?", {}))
        name = name or "?"
        if name == "Read":
            whole = "limit" not in inp and "offset" not in inp
            k = "Read whole file" if whole else "Read partial"
            if whole and tok > BIG: k = "Read whole file (big)"
        elif name == "Bash":
            k = f"Bash output {'big' if tok > BIG else 'small'}: {bash_kind(inp.get('command'))}"
        elif name in ("Agent", "Task"):
            k = "subagent report into parent"
        elif name.startswith("mcp__"):
            k = "MCP: " + name.split("__")[1][:30]
        else:
            k = "tool: " + name
        cat[k] += cost; cnt[k] += 1
        tot["tool results"] += cost

A = tot["all"] or 1
print(f"last {DAYS} days: {main_files} main sessions, {sub_files} subagent logs")
print(f"total weighted usage: {A/1e6:.1f}M  (tool-result carry cost: {tot['tool results']/A:.0%})\n")
print(f"{'share':>6} {'Mtok':>7} {'n':>6}  bucket   (buckets overlap)")
for k, v in sorted(cat.items(), key=lambda x: -x[1])[:30]:
    print(f"{v/A:6.1%} {v/1e6:7.2f} {cnt.get(k, ''):>6}  {k}")
print(f"\noverlap: long session AND >{HUGE_CTX//1000}k context: {both/A:.1%}")
print("\nby model (same weights, model price not applied):")
for (k, mdl), v in sorted(mod.items(), key=lambda x: -x[1])[:8]:
    print(f"{v/A:6.1%}  {k:4} {mdl}")
