#!/usr/bin/env python3
"""Install the dual-plan pieces into ~/.claude. Dry run unless --apply.

  install.py                      # show what would change
  install.py --apply              # do it (backs up settings.json first)
  install.py --apply --no-chore-guard --compact-window 250000
  install.py --apply --update     # replace an installed copy of the skill (old copy backed up)

Installs:
  - this skill into ~/.claude/skills/dual-plan (if run from elsewhere)
  - agents/haiku-worker.md into ~/.claude/agents/ (kept if one already exists)
  - hooks into ~/.claude/hooks/dual-plan/ and registers them in settings.json:
      PreToolUse Agent|Task              -> subagent-model-guard.py
      PreToolUse Bash|Read|browser pane  -> main-chore-guard.py   (skip with --no-chore-guard)
      UserPromptSubmit                   -> main-chore-guard.py   (resets the chore count)
  - env CLAUDE_CODE_SUBAGENT_MODEL=haiku and CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1 (unless set)
A guard whose script name is already registered (from any path) is not added again.
Never overwrites existing values; re-running is safe.
"""
import argparse, json, os, shutil, sys, time

HOME = os.path.expanduser("~/.claude")
SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL_DST = os.path.join(HOME, "skills", "dual-plan")
HOOK_DST = os.path.join(HOME, "hooks", "dual-plan")
SETTINGS = os.path.join(HOME, "settings.json")

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
ap.add_argument("--no-chore-guard", action="store_true")
ap.add_argument("--update", action="store_true", help="replace the installed skill copy")
ap.add_argument("--compact-window", type=int, help="also set autoCompactWindow (e.g. 250000)")
a = ap.parse_args()
plan = []

def step(msg, fn=None):
    plan.append(msg)
    if a.apply and fn: fn()

if shutil.which("codex") is None:
    print("warning: `codex` CLI not found on PATH; install it and sign in with your ChatGPT plan first.")

if os.path.realpath(SRC) != os.path.realpath(SKILL_DST):
    if os.path.exists(SKILL_DST) and a.update:
        bak = os.path.join(HOME, "backups", f"dual-plan-{time.strftime('%Y%m%d%H%M%S')}")
        step(f"update {SKILL_DST} (old copy to {bak})", lambda: (
            os.makedirs(os.path.dirname(bak), exist_ok=True), shutil.move(SKILL_DST, bak),
            shutil.copytree(SRC, SKILL_DST, ignore=shutil.ignore_patterns("__pycache__"))))
    elif os.path.exists(SKILL_DST):
        plan.append(f"keep existing {SKILL_DST} (pass --update to replace it)")
    else:
        step(f"copy skill to {SKILL_DST}", lambda: shutil.copytree(SRC, SKILL_DST, ignore=shutil.ignore_patterns("__pycache__")))

agent = os.path.join(HOME, "agents", "haiku-worker.md")
if os.path.exists(agent):
    plan.append(f"keep existing {agent}")
else:
    step(f"add {agent}", lambda: (os.makedirs(os.path.dirname(agent), exist_ok=True),
                                   shutil.copy(os.path.join(SRC, "agents", "haiku-worker.md"), agent)))

try:
    settings = json.load(open(SETTINGS))
except FileNotFoundError:
    settings = {}
before = json.dumps(settings, sort_keys=True)
hooks = settings.setdefault("hooks", {})

needed = set()

def add_hook(event, matcher, script):
    cmd = f"python3 {os.path.join(HOOK_DST, script)}"
    entries = hooks.setdefault(event, [])
    if any(script in (h.get("command") or "") for e in entries for h in e.get("hooks", [])):
        plan.append(f"hook already registered, skipped: {event} {matcher or ''} {script}")
        return
    needed.add(script)
    entry = {"hooks": [{"type": "command", "command": cmd, "timeout": 10}]}
    if matcher: entry = {"matcher": matcher, **entry}
    entries.append(entry)
    plan.append(f"settings.json: {event} {matcher or ''} -> {script}")

add_hook("PreToolUse", "Agent|Task", "subagent-model-guard.py")
if not a.no_chore_guard:
    add_hook("PreToolUse", "Bash|Read|mcp__Claude_Browser__.*", "main-chore-guard.py")
    add_hook("UserPromptSubmit", None, "main-chore-guard.py")

def copy_hooks():
    os.makedirs(HOOK_DST, exist_ok=True)
    for f in needed:
        shutil.copy(os.path.join(SRC, "hooks", f), os.path.join(HOOK_DST, f))
if needed:
    step(f"copy {', '.join(sorted(needed))} to {HOOK_DST}", copy_hooks)

env = settings.setdefault("env", {})
for k, v in (("CLAUDE_CODE_SUBAGENT_MODEL", "haiku"), ("CLAUDE_CODE_SUBAGENT_MODEL_FORCE", "1")):
    if k in env: plan.append(f"keep env {k}={env[k]}")
    else: env[k] = v; plan.append(f"settings.json: env {k}={v}")
if a.compact_window:
    if "autoCompactWindow" in settings: plan.append(f"keep autoCompactWindow={settings['autoCompactWindow']}")
    else: settings["autoCompactWindow"] = a.compact_window; plan.append(f"settings.json: autoCompactWindow={a.compact_window}")

if a.apply and json.dumps(settings, sort_keys=True) != before:
    if os.path.exists(SETTINGS):
        bak = f"{SETTINGS}.bak-{time.strftime('%Y%m%d%H%M%S')}"
        shutil.copy(SETTINGS, bak); plan.append(f"backed up settings to {bak}")
    os.makedirs(HOME, exist_ok=True)
    json.dump(settings, open(SETTINGS, "w"), indent=2)

print(("Applied:" if a.apply else "Dry run (add --apply):"), *("  - " + p for p in plan), sep="\n")
if a.apply: print("Restart Claude Code so the hooks and env load. Bypass the chore guard for one session with CHORE_GUARD_OFF=1.")
