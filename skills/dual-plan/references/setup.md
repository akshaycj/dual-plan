# Setup

## Prerequisites
- Claude Code with a Claude plan (main session on Opus or your preferred main model).
- Codex CLI installed and signed in with a ChatGPT plan (`codex login`). Check: `codex exec "say hi"`.
- Python 3.
- For mockups: Codex's built-in `imagegen` skill (ships with Codex under
  `~/.codex/skills/.system/imagegen`). Check:
  `python3 scripts/codex_image.py --out /tmp/test.png "a plain blue square"`.
  It uses Codex's own image tool on the ChatGPT plan; no `OPENAI_API_KEY` needed.

## Install
```bash
python3 scripts/install.py            # dry run: lists every change
python3 scripts/install.py --apply    # backs up ~/.claude/settings.json, then applies
```
Options: `--no-chore-guard` skips the main-session chore hook; `--compact-window 250000`
caps auto-compaction so the context (and every call's re-read cost) stays smaller.

## What gets installed
| Piece | Where | Effect |
|---|---|---|
| `haiku-worker` agent | `~/.claude/agents/haiku-worker.md` | Claude subagent pinned to Haiku, briefed to stay small (few screenshots, sliced reads). |
| `subagent-model-guard.py` | PreToolUse `Agent\|Task` | Blocks subagents without a pinned non-Opus model in `~/.claude/agents` (built-ins and plugin agents would inherit the main model). Lets `haiku-worker` through only when the brief mentions browser, screenshots, visual checks, computer use, the simulator, MCP connectors, artifacts, or "Codex failed"; otherwise points to Codex. Fails closed. |
| `main-chore-guard.py` | PreToolUse `Bash\|Read\|mcp__Claude_Browser__.*` + UserPromptSubmit | Main session only. Blocks dumping files over 100 lines and whole-file Reads over 400 lines; allows 2 builds/tests/browser calls per user message, then asks to delegate the rest in one batch. Codex commands always pass. Fails open; `CHORE_GUARD_OFF=1` disables it. |
| env `CLAUDE_CODE_SUBAGENT_MODEL=haiku`, `CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1` | settings.json | Every Claude subagent runs on Haiku. |

## Optional
- **Design skills for UI workers.** Symlink them so Codex can load them by name:
  `ln -s ~/.claude/skills/<skill> ~/.codex/skills/<skill>`.
- **Lane models.** Set `CODEX_FAST_MODEL`, `CODEX_STRONG_MODEL` (and `CODEX_FAST_EFFORT`,
  `CODEX_STRONG_EFFORT`) if your plan offers different models.
- **Instruction file.** Paste the Lanes table and Batching rules from SKILL.md into
  `~/.claude/CLAUDE.md` if you want them applied even when the skill isn't triggered.
- **Lean Codex.** Remove MCP servers you don't use from `~/.codex/config.toml`: every Codex
  run loads their tool definitions.

## Uninstall
Remove the three hook entries and the two env keys from `~/.claude/settings.json` (or restore
the `settings.json.bak-*` the installer made), then delete `~/.claude/hooks/dual-plan/`
and `~/.claude/skills/dual-plan/`.
