---
name: dual-plan
description: >
  Split work between a Claude subscription and a ChatGPT/Codex subscription so neither
  limit runs out first. The main Claude session (Opus) plans, decides, writes specs and
  checks diffs; Codex CLI workers do research, sweeps, builds, tests, logs and
  implementation, and generate UI mockups with Codex imagegen before big designs and
  redesigns (their tokens bill to the ChatGPT plan); a cheap Haiku subagent handles
  only what Codex can't touch (browser, screenshots, computer use, MCP connectors). Use
  whenever a task needs more than a couple of tool calls of reading, running or building,
  when delegating to subagents, when the user asks to save Claude usage, or to use
  Codex as a worker, even if they don't name this skill.
argument-hint: "[fast|strong] [task]"
---

# Dual plan: Claude + Codex

Two subscriptions, one job. Every tool call in the main Claude session re-reads the whole
context at the main model's price; in measured logs about two thirds of main-session calls
were pure chores (reads, greps, builds, browser checks). Move those out and the expensive
model only does what it is best at: deciding. Background and numbers: `references/why.md`.

## Lanes

| Work | Lane | Bills to |
|---|---|---|
| Backend, APIs, data, scripts; builds, tests, logs; codebase sweeps; web/docs research | Codex **fast** (`--model fast`) | ChatGPT |
| UI implementation from a spec; hard debugging; design trade-offs; diff review | Codex **strong** (`--model strong`) | ChatGPT |
| UI mockups before big designs and redesigns (image generation) | Codex imagegen (`scripts/codex_image.py`) | ChatGPT |
| Browser / Chrome viewing, screenshots, visual checks, computer use, simulator, MCP connectors, artifacts; anything when Codex fails | `haiku-worker` subagent | Claude (cheap) |
| Planning, UI design decisions and specs, synthesis, config edits, final diff check | Main session | Claude |

Never route work to built-in Explore / Plan / general-purpose subagents: they inherit the
main model.

## Running Codex

```bash
python3 <skill-dir>/scripts/codex_worker.py --model fast --mode write --cd /abs/repo \
  --prompt-file .agents/work/<task>/briefs/phase-2.md --report-file .agents/work/<task>/reports/phase-2.md
```

| Flag | Meaning | Default |
|---|---|---|
| `--model` | `fast` / `strong` (aliases `luna` / `sol`) or any Codex model slug | `fast` |
| `--effort` | override the lane's reasoning effort: low, medium, high, xhigh | lane's |
| `--mode` | `read` (read-only sandbox) or `write` (may edit inside `--cd`) | `read` |
| `--cd` | repo/folder Codex works in (absolute) | cwd |
| `--image` | attach an image (repeatable) | none |
| `--resume` | thread id from an earlier run's footer, to continue that job | new job |
| `--report-file` | save Codex's full report there; print only its summary (≤8 lines) and the path | print whole report |

Only the summary (or, without `--report-file`, the final report) enters Claude's context,
plus a one-line footer with the thread id and Codex token counts. Lane models come from `CODEX_FAST_MODEL` / `CODEX_STRONG_MODEL`
(and `*_EFFORT`) if set. Run long jobs in the background and wait for the notification
rather than polling.

## Spec in a file, reports in files

Every worker starts cold, so it needs everything; but the main session should not carry it
twice. Put the detail on disk and pass paths. Workers read the files in their own context
(Codex: on the ChatGPT plan), and the main session only sees short summaries.

```
.agents/work/<task>/
  SPEC.md              written once by the main session; the single source of truth
  briefs/<phase>.md    ~100 tokens each: which spec section, which phase, which report path
  reports/<phase>.md   written by the worker (Codex: by --report-file)
  mockups/             design references, if any
```

**SPEC.md** (precise enough that a worker can't miss anything):
1. **Goal and why**; decisions already made that workers must not reopen.
2. **Phases**, each with scope (files to touch, files not to touch) and a definition of done.
3. **Interfaces and details**: data shapes, names, copy, tokens, states, edge cases.
4. **Verify**: exact commands to run and what passing looks like.
5. **Constraints**: no commits/pushes, style rules, design skills to use (by name).

**Brief** (example):
```text
Read .agents/work/checkout/SPEC.md (sections 1, 3, 5 and phase 2). Do phase 2 only.
Write your report to .agents/work/checkout/reports/phase-2.md.
```

**Report** (worker writes; summary first):
```text
SUMMARY (≤5 lines): status done|partial|blocked; files changed; how verified; open questions
---
Changes (paths, lines) · Verification (commands, results) · Deviations from SPEC · Open questions
```

**Main session rules**
- Write SPEC.md once; update it in place when a decision changes, then tell running workers
  to re-read the changed section.
- Read a report file only when the summary says partial/blocked, lists open questions, or
  the diff looks wrong. Check finished work with `git diff --stat` and targeted greps, not by
  reading the report. Each extra read re-reads the whole main context, so skip it when the
  summary is enough.
- For a single small task, an inline brief is fine; the spec pays off when several workers
  or phases share it.

For UI work, also name any design skills the worker should use (for example
`impeccable`, `design-taste-frontend`, `emil-design-eng`, `make-interfaces-feel-better`)
by name only; the worker loads them itself. Make them visible to Codex by symlinking each
skill folder into `~/.codex/skills/`.

## UI flow

1. **Mockup first** for new screens, landing pages, redesigns and other big visual changes
   (skip for small tweaks, bug fixes, or when a design file already exists). See below.
2. Main session writes the spec (layout, states, tokens, interactions, copy), pointing at
   the chosen mockup.
3. Codex **strong** implements it (`--mode write`, `--image <mockup>` attached, design skills
   named in the brief).
4. `haiku-worker` checks it in the browser against the mockup (text/DOM first, at most 3–4
   shrunken screenshots).
5. Main session reviews the diff.

### Mockups with Codex imagegen

Codex ships an `imagegen` skill backed by its image model; the image bills to the ChatGPT
plan. The main session only writes the prompt; Codex generates and saves the image:

```bash
python3 <skill-dir>/scripts/codex_image.py --out /abs/repo/design/mockups/home-a.png --prompt-file /tmp/home-a.md
python3 <skill-dir>/scripts/codex_image.py --out /abs/repo/design/mockups/home-redesign.png \
  --ref /abs/repo/design/current-home.png --prompt-file /tmp/redesign.md   # redesign: attach the current screen
```

- **Directions, not variants.** For a big design, write 2–3 prompts that differ in direction
  (layout, density, mood), one run each, in the background in parallel. Show them to the user
  to pick; the visual direction is their call. One mockup is enough for a smaller screen.
- **Prompt schema** (keep only lines that help):
  ```text
  Use case: ui-mockup
  Asset type: <desktop web page 1440px wide / iPhone screen / dashboard ...>
  Primary request: <what the screen is for, in the user's words>
  Content: <the real sections, data and labels it must show>
  Style/medium: flat high-fidelity UI screenshot, no device frame
  Layout: <grid, hierarchy, what is above the fold>
  Color palette / type: <existing brand tokens, or "choose"; name fonts if fixed>
  Constraints: <keep from the current UI on a redesign; platform conventions>
  Avoid: lorem ipsum, stock-photo people, watermarks, decorative gibberish text
  ```
- **The mockup is a reference, not an asset.** Never ship the image; build it in code.
  Rendered text in mockups can be wrong, so the spec owns all copy, sizes and tokens.
- **Look before you spec.** Open each mockup once, shrunk (`sips -Z 1000`), and note what to
  keep and what to drop in the spec; don't reload old images.
- One image per run; a run takes 1–3 minutes. If generation fails, say so and continue with
  a written spec rather than switching to another image service.

## Batching rules

- Do inline only what 1–2 tool calls settle: the file you are about to edit, one known
  lookup, a one-line edit. From the 3rd chore, hand the rest to one worker in one batch.
- One worker run per independent topic; at most 2–3 at once; never two writers on the same
  files. Implementation: one run per phase, not per file or screen.
- Follow-ups go to the same worker (`--resume <thread>` for Codex, SendMessage for
  haiku-worker) so it keeps what it already read.
- Check a worker's result (the diff, a rerun) before reporting it done.

## Session hygiene

- One task per session. After an hour idle (prompt cache expired) or a second compaction,
  start a fresh session with a short handoff note instead of resuming.
- Never dump whole files or logs into the main context: `grep -n` with a little context,
  Read with offset/limit, and pipe long output through `| tail -40` or an error grep.

## Setup and measurement

- One-time install (agent, guard hooks, env): `references/setup.md`, or run
  `python3 <skill-dir>/scripts/install.py` (dry run) then `--apply`.
- Measure before and after: `scripts/usage/claude_usage.py [days]` ranks habits from
  Claude Code logs; `scripts/usage/codex_usage.py [days]` shows Codex tokens per week and
  model plus your ChatGPT plan's rate-limit use; `scripts/usage/delegation_io.py [days]`
  prices the briefs and reports that cross into the main session. All print aggregates only.
