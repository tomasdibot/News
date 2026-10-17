---
name: grilling
description: Grill the user relentlessly about a plan, decision, or idea. Use when the user wants to stress-test their thinking, or uses any 'grill' trigger phrases.
---

Interview the user relentlessly until you reach a shared understanding. Map this as a **design tree**: every decision branches into the decisions that hang off it.

Work the tree in **rounds**. The **frontier** is every decision whose prerequisites are already settled: the questions you can ask _now_ without guessing at answers you haven't heard yet. Ask the frontier in one round, then wait for the user's answers before the next round.

**Ask with interactive options, never as written options in the chat.** Put each round to the user with the `AskUserQuestion` tool (load it with ToolSearch `select:AskUserQuestion` if it is deferred):

- Up to 4 questions per call. If the frontier has more, ask the 4 that unblock the most, and the rest in the next call of the same round.
- Each question: a short `header` (≤12 chars), a plain-language `question` ending in "?", and 2–4 `options`. Each option gets a short `label` (1–5 words) and a one-line `description` of what it means or what happens next.
- Put your recommended answer **first**, with " (Recommended)" at the end of its label.
- Use `multiSelect: true` only when the choices can be combined.
- Use `preview` only to compare concrete artefacts (a mock-up, a snippet).
- The user can always pick "Other" and type their own answer. Treat it as a full answer, and turn it into follow-up questions if it opens new branches.

Before the call, write at most one short line of context in the chat. Do not repeat the questions or options as text.

Each round the user answers reshapes the tree: settled decisions push the frontier outward and unblock questions that depended on them. Recompute the frontier and ask the next round. A question whose answer depends on another question still open in this round belongs to a _later_ round, not this one.

Finding _facts_ is your job, never the user's. When a frontier question needs a fact from the environment (filesystem, tools, etc.), dispatch a sub-agent to find it; don't ask the user for anything you could look up yourself. Don't block on it: a running exploration is an unsettled prerequisite, so only the questions downstream of it wait for the sub-agent to report; ask the rest of the frontier now. The _decisions_ are the user's: put each to them and wait.

The session is done when the frontier is empty: every branch of the design tree visited, nothing left silently assumed. Do not act on it until the user confirms you have reached a shared understanding.
