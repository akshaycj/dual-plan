#!/usr/bin/env python3
"""What delegation costs the main session: briefs out, reports back (last N days).

  delegation_io.py [days]     # default 21

For every Codex run (Bash calling codex) and Claude subagent (Agent/Task) in main
sessions, estimates:
  brief   tokens Opus wrote for it (Agent prompt, or the Write/heredoc behind --prompt-file)
  report  tokens of the result that came back into context
and what each costs: output price for the brief, then cache write + a cache read on every
later call in the same context segment (carry). Prints aggregates only, never content.
Opus 5.5 list prices: output $20/M, cache write $5/M, cache read $0.20/M.
"""
import json, re, sys, time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 21
CUTOFF = time.time() - DAYS * 86400
ROOT = Path.home() / ".claude" / "projects"
OUT, CW, CR = 20 / 1e6, 5 / 1e6, 0.20 / 1e6

def ts(s):
    try: return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception: return None

def tok(x):
    if isinstance(x, str): return len(x) / 4
    if isinstance(x, list):
        return sum(1600 if isinstance(c, dict) and c.get("type") == "image"
                   else len(c.get("text", "") if isinstance(c, dict) else str(c)) / 4 for c in x)
    return len(json.dumps(x)) / 4

agg = defaultdict(lambda: defaultdict(float))
hist = defaultdict(list)
main_cost = 0.0
sessions = 0
for f in ROOT.rglob("*.jsonl"):
    if "subagents" in f.parts or f.stat().st_mtime < CUTOFF: continue
    calls, seen, seg = [], {}, 0
    deleg = {}          # tool_use id -> dict(kind, brief, idx, seg)
    writes = {}         # file path -> tokens written (Write tool or heredoc)
    results = []        # (call idx, seg, tool id, tokens)
    bgreads = set()     # Read/cat of a background task's .output file
    for line in f.open(errors="ignore"):
        try: d = json.loads(line)
        except Exception: continue
        if d.get("type") == "system" and d.get("subtype") == "compact_boundary": seg += 1
        m = d.get("message")
        if not isinstance(m, dict): continue
        t = ts(d.get("timestamp") or "")
        if d.get("type") == "assistant":
            key = d.get("requestId") or m.get("id")
            u = m.get("usage")
            if key not in seen and u and t and t >= CUTOFF:
                seen[key] = len(calls)
                calls.append((seg, (u.get("input_tokens") or 0) * 4e-6 + (u.get("cache_creation_input_tokens") or 0) * CW
                              + (u.get("cache_read_input_tokens") or 0) * CR + (u.get("output_tokens") or 0) * OUT))
            for c in m.get("content") or []:
                if not (isinstance(c, dict) and c.get("type") == "tool_use"): continue
                name, inp = c.get("name") or "", c.get("input") or {}
                if (name == "Read" and "/tasks/" in (inp.get("file_path") or "")) or \
                        (name == "Bash" and re.search(r"/tasks/\S+\.output", inp.get("command") or "")):
                    bgreads.add(c.get("id"))
                if name == "Write":
                    writes[inp.get("file_path") or ""] = tok(inp.get("content") or "")
                elif name in ("Agent", "Task"):
                    deleg[c.get("id")] = dict(kind="claude subagent", brief=tok(inp.get("prompt") or ""), idx=len(calls), seg=seg)
                elif name == "Bash":
                    cmd = inp.get("command") or ""
                    for p, body in re.findall(r"cat\s*>\s*(\S+)\s*<<\s*'?(\w+)'?\n(.*?)\n\2", cmd, re.S) and \
                            [(p, b) for p, _, b in re.findall(r"cat\s*>\s*(\S+)\s*<<\s*'?(\w+)'?\n(.*?)\n\2", cmd, re.S)] or []:
                        writes[p] = tok(body)
                    if re.search(r"\bcodex\b", cmd) and not re.search(r"codex_usage|\.codex/|grep", cmd):
                        pf = re.search(r"--prompt-file\s+(\S+)", cmd)
                        brief = writes.get(pf.group(1).strip("'\""), 0) if pf else 0
                        brief += tok(cmd) if not pf else 0
                        deleg[c.get("id")] = dict(kind="codex run", brief=brief, idx=len(calls), seg=seg)
        elif d.get("type") == "user":
            body = m.get("content")
            text = body if isinstance(body, str) else " ".join(c.get("text", "") for c in body or [] if isinstance(c, dict) and c.get("type") == "text")
            if "<task-notification>" in text:  # a background subagent/Codex run reporting back
                results.append((len(calls), seg, "bg", tok(text)))
            if not isinstance(body, list): continue
            for c in body:
                if isinstance(c, dict) and c.get("type") == "tool_result" and c.get("tool_use_id") in bgreads:
                    results.append((len(calls), seg, "bg", tok(c.get("content"))))
            for c in body:
                if isinstance(c, dict) and c.get("type") == "tool_result" and c.get("tool_use_id") in deleg:
                    results.append((len(calls), seg, c.get("tool_use_id"), tok(c.get("content"))))
    if not calls: continue
    sessions += 1
    main_cost += sum(c[1] for c in calls)
    later = lambda idx, s: sum(1 for c in calls[idx:] if c[0] == s)
    for tid, dl in deleg.items():
        a = agg[dl["kind"]]
        a["n"] += 1; a["brief_tok"] += dl["brief"]
        a["brief_out$"] += dl["brief"] * OUT
        a["brief_carry$"] += dl["brief"] * (CW + CR * later(dl["idx"] + 1, dl["seg"]))
        hist[dl["kind"] + " brief"].append(dl["brief"])
    for idx, s, tid, tk in results:
        a = agg[deleg[tid]["kind"] if tid in deleg else "background results (notifications, .output reads)"]
        a["report_tok"] += tk; a["reports"] += 1
        a["report_carry$"] += tk * (CW + CR * later(idx, s))
        a["later_calls"] += later(idx, s)
        hist[(deleg[tid]["kind"] if tid in deleg else "background results (notifications, .output reads)") + " report"].append(tk)

def pct(xs, q): xs = sorted(xs); return xs[int(q * (len(xs) - 1))] if xs else 0
print(f"last {DAYS} days: {sessions} main sessions, main-session cost ${main_cost:,.2f} (Opus list prices)\n")
tot = 0.0
for kind, a in agg.items():
    n = a["reports"] or 1
    cost = a["brief_out$"] + a["brief_carry$"] + a["report_carry$"]; tot += cost
    print(f"{kind}: {int(a['n'] or a['reports'])} {'runs' if a['n'] else 'results'}")
    if a["n"]: print(f"  brief  median {pct(hist[kind+' brief'], .5):5.0f} tok  p90 {pct(hist[kind+' brief'], .9):5.0f}   "
          f"writing ${a['brief_out$']:.2f}  carrying ${a['brief_carry$']:.2f}")
    print(f"  report median {pct(hist[kind+' report'], .5):5.0f} tok  p90 {pct(hist[kind+' report'], .9):5.0f}   "
          f"carrying ${a['report_carry$']:.2f}  (avg {a['later_calls']/n:.0f} later calls re-read it)")
print(f"\nall delegation I/O: ${tot:,.2f} = {tot/max(main_cost,1e-9):.1%} of main-session cost")
