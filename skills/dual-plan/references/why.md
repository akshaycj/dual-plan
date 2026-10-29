# Why this split works

Numbers from one heavy user's 3 weeks of Claude Code logs (171 main sessions, ~11.6k main
model calls). Yours will differ; measure with `scripts/usage/`.

## Where the main model's money went
- **About 63% of main-session calls were pure chores**: a Read, grep, build, test or browser
  call whose only purpose was to fetch something. Each one re-reads the whole context at the
  main model's price, so a 100k-token context makes a 20-line grep cost like a paragraph of
  thinking.
- Main-model cost split: cache reads ~47%, cache writes ~27%, output ~26%. Big tool results
  are paid twice: written to cache once, then re-read on every later call until compaction.
- Calls with context past ~250k cost about 60% more per call than calls under it.
- Cache rewrites (prefix changes, idle past the cache TTL) were ~8%.

## What moving chores out does
- Replaying those sessions with chores pushed to a cheap worker in batches of ~5 (paying a
  brief out and a ~400-token report back in) cut modelled main-session cost by **~40%**.
- Sending that work to Codex instead of Haiku moves it to a different subscription entirely:
  ~95% of the Haiku subagent spend in the sample was work Codex could have done.
- Switching the main loop to a cheaper model with an expensive advisor came out **+5%** (more
  turns, advisor re-reads the context), so the main model stays; only its chores move.

## Things that turned out not to matter much
- Instruction-file size: ~0.7k tokens, under 1% of startup context. Skill descriptions and
  MCP tool definitions are the bigger fixed cost; prune unused plugins and MCP servers.
- "Keep everything in one session for the cache": the cache helps only while warm (minutes,
  not hours) and the context keeps growing. Long sessions pay more per call; quality also
  degrades gradually as context grows (context rot), with no sharp threshold.

## Briefs and reports are cheap; files buy precision
Over the same 3 weeks (~900 delegations), writing briefs and carrying worker reports in the
main context cost ~3.5% of main-session spend. Most of that is the main model *writing* the
brief, which a spec file doesn't avoid (what it writes stays in its context either way). A
spec file pays off when several workers or phases reuse it, and because workers can re-read
it instead of guessing. Report files save the carry cost of long reports, as long as the
main session opens them only when the summary isn't enough.

## Brief cost vs rework cost
An ~800-token brief costs the main model a few cents. A worker that guesses wrong costs a
rework round: another brief, another run, another report, and the main model's re-read of all
of it. Detailed briefs are the cheap side of that trade.
