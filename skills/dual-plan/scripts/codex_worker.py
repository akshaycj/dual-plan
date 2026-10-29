#!/usr/bin/env python3
"""Run a Codex CLI job as a worker for Claude and print only its final report.

  codex_worker.py [--model fast|strong|<slug>] [--effort low|medium|high|xhigh]
                  [--mode read|write] [--cd DIR] [--image FILE ...]
                  [--resume THREAD_ID] [--report-file FILE]
                  [--prompt-file FILE | PROMPT | - (stdin)]

Lanes:  fast   = $CODEX_FAST_MODEL   (default gpt-6-luna),  effort high (default lane)
        strong = $CODEX_STRONG_MODEL (default gpt-6.1-sol), effort medium
        luna / sol are aliases for fast / strong.
--effort overrides the lane's effort. --mode read (default) runs read-only;
write lets Codex edit files inside --cd. --resume continues an earlier thread
(its sandbox and folder carry over). The last line printed is a footer with the
thread id to pass to --resume. With --report-file, Codex's full report is saved to
that file and only its summary block (at most 8 lines) and the path are printed.
"""
import argparse, json, os, subprocess, sys, tempfile, time

FAST = (os.environ.get("CODEX_FAST_MODEL", "gpt-6-luna"), os.environ.get("CODEX_FAST_EFFORT", "high"))
STRONG = (os.environ.get("CODEX_STRONG_MODEL", "gpt-6.1-sol"), os.environ.get("CODEX_STRONG_EFFORT", "medium"))
LANES = {"fast": FAST, "luna": FAST, "strong": STRONG, "sol": STRONG}
PREAMBLE = """You are a worker agent called by another AI agent (Claude), which reads only your final message.
Do exactly the task below. Do not spawn sub-agents, and do not commit, push or publish anything.
Keep your own context small: read large files in line ranges, pipe long output through head/tail/grep, check pages with text before screenshots.
Your final message is a concise report (under ~300 words): what you found or changed, with file paths, line numbers and evidence. For changes, say how you verified them and anything left undone.

TASK:
"""
REPORT_RULE = """Format your final message as: a SUMMARY of at most 5 lines (status: done / partial / blocked; files changed; how you verified; open questions), then a line containing only ---, then the full report (changes with file paths and lines, verification commands and results, deviations from the spec, open questions). Only the summary is shown to Claude; the full report is saved to a file it opens when needed.

"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="fast")
    ap.add_argument("--effort")
    ap.add_argument("--mode", choices=["read", "write"], default="read")
    ap.add_argument("--cd", default=os.getcwd())
    ap.add_argument("--image", action="append", default=[])
    ap.add_argument("--resume")
    ap.add_argument("--prompt-file")
    ap.add_argument("--report-file")
    ap.add_argument("prompt", nargs="?")
    a = ap.parse_args()

    if a.prompt_file:
        prompt = open(a.prompt_file).read()
    elif a.prompt and a.prompt != "-":
        prompt = a.prompt
    else:
        prompt = sys.stdin.read()
    if not prompt.strip():
        sys.exit("codex-worker: empty prompt")

    if a.report_file:
        prompt = REPORT_RULE + prompt
    slug, effort = LANES.get(a.model, (a.model, "medium"))
    effort = a.effort or effort
    tmp = tempfile.mkdtemp(prefix="codex-worker-")
    last, events = os.path.join(tmp, "last.txt"), os.path.join(tmp, "events.jsonl")

    common = ["-m", slug, "-c", f'model_reasoning_effort="{effort}"', "--skip-git-repo-check",
              "--disable", "multi_agent", "--json", "-o", last]
    for img in a.image:
        common += ["-i", os.path.abspath(img)]
    if a.resume:
        cmd = ["codex", "exec", "resume", a.resume] + common + [prompt]
    else:
        sandbox = "read-only" if a.mode == "read" else "workspace-write"
        cmd = ["codex", "exec", "-s", sandbox, "-C", os.path.abspath(a.cd)] + common + [PREAMBLE + prompt]

    t0 = time.time()
    with open(events, "w") as ev, open(os.path.join(tmp, "stderr.txt"), "w") as er:
        rc = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=ev, stderr=er).returncode

    thread, tin, tout, errors = a.resume or "?", 0, 0, []
    for line in open(events, errors="ignore"):
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get("type") == "thread.started":
            thread = d.get("thread_id", thread)
        elif d.get("type") == "turn.completed":
            u = d.get("usage") or {}
            tin += u.get("input_tokens", 0)
            tout += u.get("output_tokens", 0)
        elif d.get("type") in ("turn.failed", "error"):
            errors.append(json.dumps(d)[:400])

    report = open(last).read().strip() if os.path.exists(last) else ""
    if report and a.report_file:
        path = os.path.abspath(os.path.expanduser(a.report_file))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(report + "\n")
        head = report.split("\n---", 1)[0].strip().splitlines()[:8]
        print(*head, f"full report: {path}", sep="\n")
    elif report:
        print(report)
    else:
        print("codex-worker: no final message.", *errors[-3:], sep="\n")
        print(open(os.path.join(tmp, "stderr.txt")).read()[-1500:])
    print(f"\n[codex-worker] thread={thread} model={slug} effort={effort} mode={'resume' if a.resume else a.mode} "
          f"exit={rc} time={time.time()-t0:.0f}s codex_tokens_in={tin} out={tout} logs={tmp}")
    sys.exit(rc if rc else (0 if report else 1))


main()
