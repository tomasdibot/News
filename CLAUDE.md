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
  `NEWSDESK_THEMES` (repo variable written by the app via a fine-grained token kept in the phone's
  localStorage, or a secret; one theme per line): `judge.py` has the same model read
  each candidate story and keep only exact fits (cached in build/theme-cache.json); the app
  falls back to keyword matching for themes not in the secret.
  `NEWSDESK_ARTISTS` (repo variable, same mechanism; typed or read from Spotify via PKCE in the
  app): `artists.py` searches Google News per artist; music themes get those stories.
  Theme tabs show multi-outlet (or official) stories first; titles and theme filter use qwen2.5:7b.
  `NEWSDESK_PROFILE`, `VAPID_PRIVATE_KEY`, and WhatsApp provider secrets.
- Sources: `sources.yaml` has an optional `lean` per outlet (left … right, approximate, owner-editable); the app shows a lean bar and each outlet's headline per story. Outlets without working RSS use `gnews: <domain>` (Google News site search; outlet name kept; `gnews_days` sets its window, default 2, 7 for the weekly AI blogs). The build logs `theme <name>: candidates=… accepted=… multi_outlet=…` per theme.
- Official numbers (AR only): `econdata.py` reads dolarapi.com and argentinadatos.com (no keys; each item fails alone, hidden if missing) into `edition["econ"]`; the card shows above economy theme tabs; `check-feeds` prints the 4 endpoints. Log line `econ data: n/4`.
- Música (D11): `music.py` has `artist_rank` (story -> index in your artists), `music_tier` (0 your artist, 1 show/tour, 2 release, 3 other; fields `artist`, `mtier` in each story) and `min_outlets` (2 for music/AI themes, 3 otherwise; `themes.min_outlets` by theme key). Your artists = Spotify top, then followed, then typed, max 20 (`MAX_ARTISTS`). `artists.py` also runs fixed Google News show queries (`SHOW_QUERIES`, es-AR, 9 queries, 14-day window; music outlets via `gnews:` incl. `infobae.com/teleshow` as outlet Infobae; `check-feeds` prints their status). `confirmed()` in index.html: min_outlets or official or (music + your artist), fill with 2-outlet, then single-outlet marked "1 medio". Log: `confirmed=` per theme, `music order:` + samples, `sources <theme>: Outlet cand/acc` (music and AI). D13: music candidates also take `MUSIC_CANDIDATE_WORDS` (judge.py only) and any culture-topic specialist outlet, up to 60 per music theme (40 others); Anthropic, Meta AI and Mistral blogs are official `gnews:` sources. `judge.rule_verdict` (before cache and model): AI case studies out; in music themes a lead headline with a show word, music evidence (banda, shows, world tour, venue, your artist...) and a place or year 2025-2030 is in.
- Blindspot (D9, not shown in the UI yet): `edition.blindspot()` puts `blind` ("left"/"right" = the side that ignores a local, non-soft story with ≥3 outlets) in each story; the build logs `blindspot: n flagged (left_ignores=a, right_ignores=b) of m local multi-outlet stories`.
- UI preference: suggestions/choices are always shown as a dropdown list (native `<select>`,
  plus `<datalist>` autocomplete on text boxes), never as chips/buttons.
- The owner prefers free options; Claude API is an opt-in paid upgrade.
- The owner does not trust Green API; don't suggest it again. WhatsApp providers are
  optional; the default reminder is `push`.

## Development loop

Changes to the app go through `/improve` (`.claude/skills/improve/SKILL.md`): the main session is the
orchestrator (Opus, medium effort); agents in `.claude/agents/` (Sonnet, medium effort) do the work — `investigator` (evidence and predictions,
read-only), `code-writer`, `reviewer` (APPROVE/CHANGES, up to 3 rounds), `implementer` (tests, commit,
push, start workflows). Every decision, its prediction and the measured result go in
`.claude/decisions.md`; read its Lessons before deciding.
Matt Pocock's skills (engineering + productivity) are copied into `.claude/skills/` (MIT; see
`.claude/skills/MATTPOCOCK-SKILLS.md`); the agents use `tdd`, `code-review`, `diagnosing-bugs` and `research`.
