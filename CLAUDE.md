# Newsdesk: notes for Claude

Personal news site for the repo owner: ranks Spanish/English news by independent
coverage, publishes a password-encrypted page to GitHub Pages every hour, and sends a
daily phone notification (Web Push) from the installed app. See README.md for details.

## Working with the owner

- The owner sets things up from their phone and is not a developer. Use plain language
  and step-by-step instructions with the exact names of buttons, settings and secrets.
- **Keep replies short.** The owner wants less text. No long explanations or tables unless asked.
- After adding or changing a feature, end with a **short** workflow update (a few lines):
  what changed, and only the steps the owner must do now. The full setup checklist lives
  in README.md — keep it in sync there instead of repeating it in chat.
- Keep text inside the app short too.

## Project facts

- Code: `newsdesk/` (fetch → cluster → rank → render; `lock.py` encryption, `push.py`
  Web Push). Tests: `python -m pytest -q` (offline fixtures; browser tests use
  Chromium at /opt/pw-browsers/chromium when present).
- Automation: `.github/workflows/newsdesk.yml` runs hourly (build + deploy to Pages) and at
  the `NOTIFY_CRON` time (also sends the reminder). Times in that file are UTC.
- Secrets: `NEWSDESK_PASSWORD` (required), `PUSH_SUBSCRIPTIONS` (codes from the app's bell),
  optional `ANTHROPIC_API_KEY`. Neutral titles (`neutral.py`) default to a free local model (Ollama +
  qwen2.5:3b started in the workflow, NEWSDESK_LOCAL_MODEL); GitHub Models answered only "OK" in
  real runs, so it is opt-in only. Cached in build/neutral-cache.json.
  `NEWSDESK_PROFILE`, `VAPID_PRIVATE_KEY`, and WhatsApp provider secrets.
- UI preference: suggestions/choices are always shown as a dropdown list (native `<select>`,
  plus `<datalist>` autocomplete on text boxes), never as chips/buttons.
- The owner prefers free options; Claude API is an opt-in paid upgrade.
- The owner does not trust Green API; don't suggest it again. WhatsApp providers are
  optional; the default reminder is `push`.
