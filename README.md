# dual-plan

[![skills.sh](https://skills.sh/b/akshaycj/dual-plan)](https://skills.sh/akshaycj/dual-plan)

**Use your Claude plan and your ChatGPT plan together, so neither one runs out first.**

A Claude Code skill that turns Opus into the planner and reviewer, and sends the heavy lifting to Codex CLI workers that bill to your ChatGPT subscription. A cheap Haiku subagent handles the few things Codex can't do: the browser, screenshots, computer use and MCP connectors.

## Install

```bash
git clone https://github.com/akshaycj/dual-plan.git
cd dual-plan
python3 skills/dual-plan/scripts/install.py           # dry run: lists every change it would make
python3 skills/dual-plan/scripts/install.py --apply   # backs up ~/.claude/settings.json, then applies
```

Or, skill only (no hooks, no agent):

```bash
npx skills@latest add akshaycj/dual-plan
```

The skill works on its own, but the guard hooks are what keep the split honest. To add them later, run `scripts/install.py --apply` from the installed skill folder.

### Requirements

- [Claude Code](https://claude.com/claude-code) on a Claude plan
- [Codex CLI](https://github.com/openai/codex) signed in with a ChatGPT plan (`codex login`). Check it with `codex exec "say hi"`.
- Python 3
- For UI mockups: Codex's built-in `imagegen` skill, which ships with Codex. No `OPENAI_API_KEY` needed.

## Why use it?

Opus is the most expensive tool in your setup, and most of what it does all day is chores.

In three weeks of one heavy user's logs (166 sessions, about 10.8k main-model calls), **two thirds of main-session calls were pure chores**: a read, a grep, a build, a test run, a browser check. Each of those calls re-reads the whole context at Opus prices, so a 20-line grep in a 100k-token session costs as much as a paragraph of thinking.

Replaying those sessions with the chores pushed to workers cut the modelled main-session cost by **about 42%**. Sending that work to Codex instead of a Claude subagent moves it onto a different subscription entirely.

Things that didn't help: switching the main loop to a cheaper model with Opus as an advisor came out **5% more expensive** (more turns, plus the advisor re-reading context). So Opus stays in charge and only its chores move.

Full numbers are in [`references/why.md`](./skills/dual-plan/references/why.md), and you can measure your own with the scripts in `scripts/usage/`.

## How it works

### Lanes

| Work | Goes to | Bills to |
|---|---|---|
| Backend, APIs, data, scripts; builds, tests, logs; codebase sweeps; web and docs research | Codex **fast** lane (`gpt-6-luna`, high effort) | ChatGPT |
| UI built from a spec; hard debugging; design trade-offs; diff review | Codex **strong** lane (`gpt-6.1-sol`, medium effort) | ChatGPT |
| UI mockups before new screens and redesigns | Codex imagegen | ChatGPT |
| Browser, screenshots, visual checks, computer use, simulator, MCP connectors; anything Codex failed at | `haiku-worker` subagent | Claude (cheap) |
| Planning, design decisions, specs, synthesis, final diff check | Main session (Opus) | Claude |

Lane models can be changed with `CODEX_FAST_MODEL`, `CODEX_STRONG_MODEL`, `CODEX_FAST_EFFORT` and `CODEX_STRONG_EFFORT`.

### Specs and reports live in files

For multi-step work, Opus writes the plan once to `.agents/work/<task>/SPEC.md`: the goal, the decisions made, the phases with a definition of done, and the commands that verify them. Each worker gets a brief of about 100 tokens pointing at the spec sections it needs, plus a path for its report.

The worker writes its full report to that file and returns only a summary of five lines or fewer. Opus opens the full report only when the summary says the work is partial or blocked, raises questions, or the diff looks wrong.

```
.agents/work/<task>/
  SPEC.md        # written once, updated in place
  briefs/        # short pointers into the spec
  reports/       # full worker reports
  mockups/       # imagegen output
```

The point is precision more than savings: workers re-read the spec instead of guessing, and several workers or phases share one source of truth. A detailed brief costs a few cents; a wrong guess costs a whole rework round.

### UI: mockups first

For new screens, landing pages and redesigns, the flow is:

1. **Mockups.** Codex imagegen makes two or three mockups in different directions. Opus writes the prompts, and for a redesign it attaches a screenshot of the current screen. You pick one.
2. **Spec.** Opus writes the layout, states, tokens, interactions and copy against the chosen mockup.
3. **Build.** The strong lane implements it, with the mockup attached.
4. **Check.** `haiku-worker` compares the result with the mockup in the browser.
5. **Review.** Opus reviews the diff.

Small tweaks and fixes skip the mockups. UI briefs name design skills such as [`emil-design-eng`](https://github.com/emilkowalski/skills) for the worker to load, if you have them installed.

### Guard hooks

| Hook | What it does |
|---|---|
| `subagent-model-guard` | Blocks subagents that would inherit Opus (Explore, Plan, general-purpose, unpinned plugin agents). It lets `haiku-worker` through only for browser, visual, MCP or "Codex failed" work, and points everything else to Codex. |
| `main-chore-guard` | Main session only. Blocks dumping files over 100 lines and whole-file reads over 400 lines. It allows two chores per message, then asks for the rest to go to a worker in one batch. Codex commands always pass. Set `CHORE_GUARD_OFF=1` to turn it off. |

The installer also sets `CLAUDE_CODE_SUBAGENT_MODEL=haiku` so any Claude subagent runs on Haiku.

## What's inside

```
skills/dual-plan/
  SKILL.md                       # the playbook the agent follows
  scripts/
    codex_worker.py              # run a Codex job, print only its report
    codex_image.py               # one mockup per run via Codex imagegen
    install.py                   # dry-run-first installer
    usage/                       # measure your own logs
  hooks/
    subagent-model-guard.py
    main-chore-guard.py
  agents/haiku-worker.md         # Haiku-pinned Claude subagent
  references/
    setup.md                     # install options, uninstall
    why.md                       # the evidence
```

## Usage

Once it's installed, you don't call it yourself. The skill triggers whenever a task needs more than a couple of tool calls of reading, running or building. You can also ask for it directly:

> Use dual-plan to add rate limiting to the API and cover it with tests.

> Redesign the settings page. Show me mockups first.

You can also run the workers by hand:

```bash
# Codex job; only the summary comes back
python3 skills/dual-plan/scripts/codex_worker.py --model fast --mode write --cd "$PWD" \
  --prompt-file .agents/work/rate-limit/briefs/phase-1.md \
  --report-file .agents/work/rate-limit/reports/phase-1.md

# One mockup; run several in the background for variants
python3 skills/dual-plan/scripts/codex_image.py --out "$PWD/.agents/work/settings/mockups/a.png" \
  --ref current-settings.png "Calm, dense settings page; left nav, grouped cards"
```

### Measure your own setup

```bash
python3 skills/dual-plan/scripts/usage/claude_usage.py 21     # token-burning habits, last 21 days
python3 skills/dual-plan/scripts/usage/codex_usage.py 21      # Codex tokens per week and model
python3 skills/dual-plan/scripts/usage/delegation_io.py 21    # what briefs and reports cost
python3 skills/dual-plan/scripts/usage/cost_model.py 21       # replay sessions under four setups
```

They read your local logs (`~/.claude/projects`, `~/.codex/sessions`) and print totals only, never message content.

## Installer options

| Flag | Effect |
|---|---|
| *(none)* | Dry run: prints every change |
| `--apply` | Makes the changes, after backing up `settings.json` |
| `--update` | Replaces an installed copy of the skill (the old copy goes to `~/.claude/backups/`) |
| `--no-chore-guard` | Skips the main-session chore hook |
| `--compact-window 250000` | Caps auto-compaction so the context, and the cost of re-reading it, stays smaller |

Running it again is safe: it never overwrites existing values, and it skips any hook that's already registered.

## Uninstall

Remove the three hook entries and the two env keys from `~/.claude/settings.json`, or restore the `settings.json.bak-*` backup the installer made. Then delete `~/.claude/hooks/dual-plan/` and `~/.claude/skills/dual-plan/`.

## License

MIT
