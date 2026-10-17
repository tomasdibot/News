---
name: improve
description: Orchestrates a change to the Newsdesk app through a loop of agents - investigator (evidence), code-writer, reviewer, implementer - and records every decision with its prediction and measured outcome in .claude/decisions.md so later decisions get better. Use for any feature request, bug report or "make X better" about the app.
model: opus
effort: medium
---

# Newsdesk improvement loop (you are the orchestrator)

You decide; the agents do the work. Never write app code yourself in this loop.
The decision log `.claude/decisions.md` is the loop's memory: read it first, write to it every round.

```
        ┌──────────────────────────── lessons ─────────────────────────────┐
        ▼                                                                  │
 1 Frame ─► 2 Investigate ─► 3 Decide ─► 4 Write ⇄ 5 Review ─► 6 Ship ─► 7 Measure ─► 8 Learn
            (investigator)   (you, log    (code-     (reviewer,  (imple-   (investigator, (you, log
                              prediction)  writer)    ≤3 rounds)  menter)   mode after)    outcome)
```

## 1. Frame
- Restate the owner's request as one measurable goal (what number or visible behaviour changes).
- Read `CLAUDE.md` and `.claude/decisions.md`. Note lessons that apply.
- Use branch `claude/news-outlet-setup` unless told otherwise.

## 2. Investigate
Run the `investigator` agent in mode **before** with the goal and the relevant lessons. Independent questions can go to several investigators in parallel (one message, several Agent calls).

## 3. Decide
- Pick one option. Prefer: evidence-backed over guessed, free over paid, small over large, reversible over not.
- If an option contradicts a logged lesson, you need new evidence, or reject it.
- If the choice is the owner's (money, privacy, a new account, changing what they see a lot), ask them first with a short dropdown-style question; otherwise decide.
- Append a decision entry to `.claude/decisions.md` (template at the top of that file) with status `open`, the **prediction** and the **measurement**.

## 4. Write
Run the `code-writer` agent with the plan (goal, option, files, prediction, owner rules that apply).

## 5. Review
Run the `reviewer` agent with the plan and the writer's summary.
- `CHANGES` with blocking findings → back to step 4 with the findings. At most 3 rounds.
- Still blocked after 3 rounds → go back to step 2 with what was learned (the plan was wrong, not the code), and log it.
- `APPROVE` → step 6.

## 6. Ship
Run the `implementer` agent with the approved plan, branch, commit summary and the commit attribution lines from your instructions. Get the run IDs.

## 7. Measure
Builds take ~15 min, audits ~8 min. Do not poll with sleep: schedule a check-in (`send_later`, ~15–20 min) and end the turn. On wake, run the `investigator` in mode **after** with the run IDs, the prediction and the baseline.

## 8. Learn
- Update the decision entry: measured result, prediction right/wrong, verdict, lesson.
- Lesson worth keeping for future decisions → add it to the **Lessons** list at the top of the log (one line, with the decision number).
- Verdict `ADJUST` → next round from step 3 (or 2 if the cause is unclear). `REVERT` → implementer reverts with a new commit, then log it. `KEEP` → done.
- Stop after the goal is met, after 3 full rounds without progress (tell the owner what blocks), or when the owner says stop.

## Matt Pocock's skills (in `.claude/skills/`)
- Big or vague request: use `grilling` sparingly, a few short questions at most (the owner is not a developer and wants short replies); prefer deciding from evidence.
- Work bigger than one session: `to-spec` / `to-tickets` (tickets as local files in `docs/tickets/`), or `wayfinder`.
- Context getting full: `handoff`. After a loop, a quick `retro` (suggestions for the agents' rules) — add accepted ones to the agent files or the Lessons.
- Agents use: investigator → `diagnosing-bugs`, `research`; code-writer → `tdd`; reviewer → `code-review`.

## Reporting to the owner
Follow CLAUDE.md: short, plain language. At the end: what changed, the measured number, and only the steps the owner must do now.
