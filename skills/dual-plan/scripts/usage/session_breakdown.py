#!/usr/bin/env python3
"""Per-session token breakdown for one day, focused on Codex delegation.

  session_breakdown.py 2026-10-25          # list that day's main sessions
  session_breakdown.py 2026-10-25 <n>      # break down the n-th listed session

Prints numbers and tool names only; never commands, paths or message text.
Weights as in usage_habits.py: input x1, cache write x1.25, cache read x0.1, output x5.
"""
import json, re, sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

DAY = sys.argv[1]
PICK = int(sys.argv[2]) if len(sys.argv) > 2 else None
ROOT = Path.home() / ".claude" / "projects"
W = dict(input_tokens=1.0, cache_creation_input_tokens=1.25,
         cache_read_input_tokens=0.1, output_tokens=5.0)

def local_day(s):
    try: return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d")
    except Exception: return None

def est(c):
    if isinstance(c, str): return len(c) / 4
    if isinstance(c, list):
        return sum(1600 if isinstance(x, dict) and x.get("type") == "image"
                   else len(x.get("text", "") if isinstance(x, dict) else str(x)) / 4 for x in c)
    return len(json.dumps(c)) / 4

def is_codex(cmd): return bool(re.search(r"\bcodex\b", cmd or ""))

def load(f):
    calls, results, tools, seen, seg = [], [], {}, {}, 0
    for line in f.open(errors="ignore"):
        try: d = json.loads(line)
        except Exception: continue
        if d.get("type") == "system" and d.get("subtype") == "compact_boundary": seg += 1
        m = d.get("message")
        if not isinstance(m, dict): continue
        if d.get("type") == "assistant":
            uses = [c for c in m.get("content") or [] if isinstance(c, dict) and c.get("type") == "tool_use"]
            for c in uses: tools[c.get("id")] = (c.get("name") or "?", c.get("input") or {})
            u, key = m.get("usage"), d.get("requestId") or m.get("id")
            if key in seen:  # one API response is logged as one record per content block
                seen[key]["tools"] += [c.get("name") for c in uses]; seen[key]["ids"] += [c.get("id") for c in uses]
                continue
            if not u or local_day(d.get("timestamp") or "") != DAY: continue
            ctx = sum(u.get(k) or 0 for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
            calls.append(dict(w=sum(W[k] * (u.get(k) or 0) for k in W), ctx=ctx, seg=seg,
                              out=(u.get("output_tokens") or 0) * 5, model=str(m.get("model")),
                              tools=[c.get("name") for c in uses], ids=[c.get("id") for c in uses]))
            seen[key] = calls[-1]
        elif d.get("type") == "user" and isinstance(m.get("content"), list):
            for c in m["content"]:
                if isinstance(c, dict) and c.get("type") == "tool_result":
                    results.append((len(calls), seg, c.get("tool_use_id"), est(c.get("content"))))
    return calls, results, tools

# list main sessions active that day, with their subagent logs
sessions = []
for f in ROOT.rglob("*.jsonl"):
    if "subagents" in f.parts: continue
    calls, results, tools = load(f)
    if not calls: continue
    subs = [s for s in (f.parent / f.stem / "subagents").glob("*.jsonl")] if (f.parent / f.stem).is_dir() else []
    sub_w = sum(c["w"] for s in subs for c in load(s)[0]) / 5  # Haiku ~1/5 Opus price
    ncodex = sum(1 for n, i in tools.values() if n == "Bash" and is_codex(i.get("command")))
    sessions.append((sum(c["w"] for c in calls), sub_w, ncodex, f, calls, results, tools))
sessions.sort(key=lambda s: -(s[0] + s[1]))

if PICK is None:
    print(f"{'#':>2} {'main Mtok':>9} {'sub(adj)':>8} {'calls':>5} {'codex':>5} {'peak ctx':>8}")
    for i, (w, sw, nc, f, calls, *_) in enumerate(sessions):
        print(f"{i:>2} {w/1e6:9.2f} {sw/1e6:8.2f} {len(calls):>5} {nc:>5} {max(c['ctx'] for c in calls)/1e3:7.0f}k")
    sys.exit()

w, sw, nc, f, calls, results, tools = sessions[PICK]
T = w
print(f"session #{PICK}: {len(calls)} API calls, {T/1e6:.2f}M weighted (main), subagents ~{sw/1e6:.2f}M Opus-equiv")
print(f"output (x5): {sum(c['out'] for c in calls)/T:.0%}   input side: {1 - sum(c['out'] for c in calls)/T:.0%}")

# what each API call was doing: the tool(s) it emitted
by_tool = defaultdict(lambda: [0.0, 0])
for c in calls:
    names = c["tools"] or ["(text reply / no tool)"]
    for n, tid in zip(names, c["ids"] or [None]):
        if n == "Bash" and tid and is_codex(tools.get(tid, ("", {}))[1].get("command")): n = "Bash: codex"
        elif n == "Bash" and tid:
            cmd = tools.get(tid, ("", {}))[1].get("command") or ""
            n = "Bash: sleep/poll" if re.search(r"\b(sleep|tail|cat)\b.*(log|out|jsonl)|\bwait\b", cmd) else "Bash: other"
        by_tool[n][0] += c["w"] / len(names); by_tool[n][1] += 1
print("\nAPI-call cost by the tool that call emitted (each call re-reads the whole context):")
for n, (v, k) in sorted(by_tool.items(), key=lambda x: -x[1][0])[:12]:
    print(f"  {v/T:6.1%}  {k:>4} calls  {n}")

# context size bands
print("\ncost by context size of the call:")
for lo, hi in [(0, 50e3), (50e3, 100e3), (100e3, 150e3), (150e3, 1e9)]:
    v = sum(c["w"] for c in calls if lo <= c["ctx"] < hi)
    k = sum(1 for c in calls if lo <= c["ctx"] < hi)
    print(f"  {v/T:6.1%}  {k:>4} calls  {int(lo/1e3)}-{'' if hi > 1e8 else int(hi/1e3)}k")

# carry cost of tool results, codex reports separated
carry = defaultdict(lambda: [0.0, 0, 0.0])
for idx, seg, tid, tok in results:
    later = sum(1 for c in calls[idx:] if c["seg"] == seg)
    n, i = tools.get(tid, ("?", {}))
    if n == "Bash": n = "Bash: codex" if is_codex(i.get("command")) else "Bash: other"
    elif n.startswith("mcp__"): n = "MCP: " + n.split("__")[1]
    carry[n][0] += tok * 1.25 + tok * 0.1 * later; carry[n][1] += 1; carry[n][2] += tok
print("\ncarry cost of tool results (bytes kept in context):")
for n, (v, k, tok) in sorted(carry.items(), key=lambda x: -x[1][0])[:10]:
    print(f"  {v/T:6.1%}  {k:>4} results  avg {tok/max(k,1):6.0f} tok  {n}")
ctxs = sorted(c["ctx"] for c in calls)
print(f"\ncontext per call: min {ctxs[0]/1e3:.0f}k  median {ctxs[len(ctxs)//2]/1e3:.0f}k")
print(f"compactions: {calls[-1]['seg']}   peak context: {max(c['ctx'] for c in calls)/1e3:.0f}k")

# what the non-Codex shell calls were doing (kind only, never the command)
KINDS = [("background/poll", r"\b(sleep|wait|jobs|ps|pgrep|lsof)\b"), ("test", r"\b(test|pytest|jest|vitest)\b"),
         ("build/run", r"\b(build|tsc|vite|xcodebuild|tauri|npm run|pnpm|bun|cargo|swift|make|node|python3?)\b"),
         ("read file/log", r"\b(cat|head|tail|sed -n|less)\b"), ("search", r"\b(grep|rg|find|ls)\b"),
         ("git", r"\bgit\b"), ("curl/http", r"\bcurl\b")]
kind = defaultdict(lambda: [0.0, 0])
for c in calls:
    for n, tid in zip(c["tools"], c["ids"]):
        cmd = tools.get(tid, ("", {}))[1].get("command") if n == "Bash" else None
        if cmd is None or is_codex(cmd): continue
        k = next((k for k, rx in KINDS if re.search(rx, cmd)), "other")
        kind[k][0] += c["w"] / len(c["tools"]); kind[k][1] += 1
print("\nnon-Codex Bash calls by kind (cost of the API call that issued them):")
for k, (v, n) in sorted(kind.items(), key=lambda x: -x[1][0]):
    print(f"  {v/T:6.1%}  {n:>4} calls  {k}")
