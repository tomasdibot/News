# Decision log

Memory of the improvement loop (`/improve`). The investigator reads it before every proposal; the
orchestrator adds an entry for each decision and fills in the outcome after measuring.

## Lessons (read first)

- L1 (D1): The 3B model judging many stories in one request mixes them up (~50–75% right). Judge one story per request.
- L2 (D2): One story per request with the 7B model is accurate enough (83–95%) and fits the hourly budget.
- L3 (D3, D4): The small model applies every rule in the prompt to every section. Give each section only its own rules and examples.
- L4 (D4): Section names overlap in words ("Lanzamientos" is both music and AI). Check rule selection for every configured theme, not just the one being fixed.
- L5 (D5): GitHub Models answered only "OK" in real runs. Keep it opt-in; the free local model is the default.
- L6: Known-answer tests alone hide problems; always score today's real stories too (audit section 2).
- L8 (D6): Feed URLs guessed offline are often dead (4 of 9). Verify every new feed from the CI runner (sandbox has no network) before predicting outlet counts.
- L9 (D6): Neutral titles fill a fixed time budget, so more sources lengthen the build up to that budget; predict build time from the budget, not from fetch cost.
- L10 (D7): Google News `site:` feeds revive outlets with dead RSS (Página/12 98 items, Cronista 100); `check-feeds` in the audit run proves feeds in 15 s. No images from them.
- L11 (D8): Free no-key AR APIs (dolarapi.com, argentinadatos.com) work from CI; build time depends mostly on cache warmth — compare runs with similar cache state.
- L12 (D9): Only ~1 local story per build reaches ≥3 Argentine outlets in one cluster, so lean-based features (blindspots) have no data until AR stories cluster across outlets. Check the denominator before building on a metric; log feed outages next to lean-based flags.
- L13 (D10): Number- and entity-aware grouping raised multi-outlet stories +62% (Economía 8→12, Mundo 5→11) with 0/8 wrong merges sampled; Música and IA did not move — they need more outlets, not looser matching.
- L14 (D6–D10): Build an offline fixture and count wrong merges/false flags next to hits; log samples (titles + outlets) so real-run quality can be judged, since the page is encrypted.
- L7: The owner does not trust Green API; never propose it. Paid options (Claude API) only as opt-in.

## Entry template

```
### D<n> — <short title> (<date>) — status: open | kept | adjusted | reverted
Goal: <owner request as a measurable goal>
Evidence: <investigator findings, with numbers>
Options: <A / B / C, one line each>
Decision: <chosen option and why>
Prediction: <metric: before → expected>
Measurement: <command / workflow / log line>
Result: <measured number, run link>  — prediction right? yes/no
Verdict & lesson: <keep/adjust/revert; one-line lesson>
```

## Entries

### D1 — Batch theme judging with the 3B model (2026-10) — status: reverted
Goal: AI filter keeps only stories that fit each owner theme.
Decision: send 10–20 stories per request to qwen2.5:3b.
Prediction: ≥85% right in the audit.
Result: 50–75% right; verdicts got attached to the wrong stories. — prediction right? no
Verdict & lesson: reverted → L1.

### D2 — One story per request, 7B model (2026-10) — status: kept
Decision: `judge.py` asks qwen2.5:7b about one story at a time, JSON reply, cached verdicts.
Prediction: ≥80% right; build under 20 min.
Result: 83% (v3), 85% (v4) on live news; build ~13 min. — yes
Verdict & lesson: kept → L2.

### D3 — Single prompt with all section rules (2026-10-14) — status: adjusted
Goal: Economía stopped showing single-company stories (Bioceres case).
Decision: add "one company doesn't fit" rule to the shared prompt (judge v5).
Prediction: Economía rejects single-company stories; others unchanged.
Result: Economía fixed, but IA rejected Gemini 4 and NVIDIA launches and accepted funding rounds. — partly
Verdict & lesson: adjusted by D4 → L3.

### D4 — Per-section rules (2026-10-14) — status: kept
Decision: `one_system(theme)` adds only the rules whose words match the section (judge v6), then v7 keeps the AI-launch rule out of music sections.
Prediction: IA accepts launches; other sections not worse.
Result: known answers 39/41 (95%); IA real news now accepts Gemini 4, NVIDIA Vera Rubin, DeepMind. Music still strict (Charly García free shows rejected) → v7 fix, not yet measured. — yes for IA
Verdict & lesson: kept → L3, L4. Follow-up: measure v7 music; Economía missed "Gobierno celebró el número de la inflación"; Mundo missed the Pope's illness and Guadalajara water crisis.

### D5 — Neutral titles provider (2026-10) — status: kept
Decision: free local model (Ollama, qwen2.5) by default; GitHub Models opt-in only.
Result: GitHub Models answered "OK" instead of titles in real runs. — n/a
Verdict & lesson: → L5.

### D6 — Balanced sources + coverage/lean view + per-theme metrics (2026-10-17) — status: adjusted
Goal: interesting, unbiased news that fits the owner's themes, modelled on existing apps.
Evidence: (investigators) Página/12 feed 404 and Rolling Stone ES 403, so only 5 working AR outlets, mostly centre/centre-right; 1 economy feed (Ámbito home); no lean field anywhere; Economía accepted 6/25 in the audit, mostly single-outlet opinion; music 4/16; the build logs no per-theme counts. Ground News/AllSides/Google Full Coverage show the spread of coverage by lean and each outlet's headline; Semafor separates news from views.
Options: A) sources + lean labels + coverage bar + side-by-side headlines + per-theme log; B) economy data card (INDEC/BCRA); C) Semafor-style summaries with the 7B model; D) Blindspot tab.
Decision: A first (cheap, no model calls, makes everything else measurable). B, D next; C later (risk of invented facts, CI time).
Prediction: working AR outlets 5 → ≥8; AR economy feeds 1 → ≥3; build log prints per theme candidates/accepted/multi-outlet; every multi-outlet story shows a lean bar and per-outlet headlines; build time +<1 min.
Measurement: newsdesk.yml run log (fetch line, warnings, new per-theme line, duration); pytest.
Result: run 39002794246 — 3539 articles from 44 sources (was 3201/35). New feeds OK: elDiarioAR, Infobae/La Nación/Clarín economy, Clarín espectáculos, Chequeado. Dead: all 3 Página/12 URLs (404), El Cronista (404); Rolling Stone ES still 403. Working AR outlets 7 (predicted ≥8, missed); AR economy feeds 4 (≥3, met); per-theme line works: Economía 40/25 accepted/7 multi-outlet, Mundo 40/26/4, Música 14/4/1, IA 32/5/2. Job 14 min (+4.5; neutral titles now hit their time budget) — build-time prediction missed. — partly
Verdict & lesson: adjusted by D7 → L8, L9.

### D7 — Dead feeds via Google News site search + feed check in CI (2026-10-17) — status: kept
Goal: restore Página/12 (centre-left) and El Cronista, so AR outlets reach ≥8, and make feed checks possible from CI.
Evidence: D6 run — Página/12 /rss/secciones/... redirects to a 404; Cronista 404; sandbox cannot reach the sites to find the real URLs. `artists.py` already reads Google News search RSS with the outlet name.
Options: A) guess new URLs again (L8 says no); B) Google News `site:` search feeds for outlets without working RSS; C) drop them.
Decision: B, plus a feed-status step in CI so future URLs are verified (L8).
Prediction: no 404 for Página/12 / Cronista; working AR outlets 7 → ≥9 (incl. Chequeado); job time ≤ 15 min.
Measurement: next newsdesk.yml log (warnings, fetch line, per-theme lines); feed-check output.
Known limit: gnews links are news.google.com, so opinion detection by URL and og:image/excerpts do not work for those items; check Página/12 opinion leaks in the next run.
Result: audit run 39004075921 — check-feeds 42/42 working; Página/12 98, Cronista 100, Rolling Stone ES 64 items; 3809 articles from 42 sources; AR outlets 9 (+Rolling Stone) — met. Judge v7 known answers 39/41; real rows scored: Economía ~22/25, Música ~15/19 (Charly García now in; no Spanish shows/tours content). No Página/12 opinion leak seen. Build time: run 39004074270 job 12m40s (≤15, met). — yes
Verdict & lesson: kept → L10. D6 audit part closed.

### D8 — Economía official-data card (2026-10-17) — status: kept
Goal: "Economía Argentina, datos insesgados": show the key official numbers above the Economía stories, with source and date (Tangle/Semafor fact-first idea).
Evidence: owner theme asks for unbiased data; stories carry outlet framing; investigator ranked Blindspot (cheap) first and this second, but the data card serves the owner's explicit wording and has no lean-label subjectivity. Candidate free APIs (unverified, L8): datos.gob.ar series API (INDEC CPI), BCRA API, dolarapi.com (official/blue), argentinadatos.com (riesgo país, inflation).
Options: A) data card with fail-safe fetch + endpoint check in CI; B) Blindspot tab; C) music shows.
Decision: A now (B next). Card hides any value that fails; endpoints are checked by `check-feeds` so the next audit run verifies them (L8).
Prediction: ≥3 of 4 values (monthly inflation, official dollar, blue dollar, riesgo país) shown with source + date; build time +<30 s; 0 crashes when an API fails.
Measurement: audit run check-feeds output for the data endpoints; newsdesk log line `econ data: n/4`; pytest.
Review notes (optional, not done): card also shows for a non-Argentine economy theme; requests timeout is per read, so a slow API could add ~16 s per value when APIs are down.
Result: audit 39005508121 check-feeds — inflation 1.9% (2026-09-30), official 1535, blue 1555, riesgo país 648 (2026-10-16), all OK; build 39005506740 `econ data: 4/4`, no warnings, job 8m12s (warm cache), econ fetch ≤ a few s. — yes
Verdict & lesson: kept → L11. Untested: API-down timing, card on non-AR economy themes.

### D9 — Blindspot detection, measured before shown (2026-10-17) — status: parked
Goal: Ground News-style "blindspots": AR stories one side of the lean bar does not cover.
Evidence: leans: 23 centre, 2 centre-left (Página/12, elDiarioAR), 3 centre-right feeds (La Nación ×2, El Cronista), no left/right; ~14 sources unlabelled. Estimate 5–15 flagged/day, ~80% "left ignores" because only 2 left outlets; feed windows (Google News ~100 items) mean absence in feeds ≠ absence of coverage.
Options: A) full tab now; B) compute + log + `blind` field, no UI until a quality check passes; C) skip.
Decision: B — the investigator's risks (L6 spirit: check real data first) make a visible tab risky; measure first.
Prediction: log `blindspot: n flagged (left_ignores=a, right_ignores=b) of m local multi-outlet stories` with 3 ≤ n ≤ 15 and a/n ≥ 0.6; build time ±0; then ≥4/5 sampled flags are real (the ignoring side truly has no article).
Measurement: newsdesk log line; manual sample of 5 flagged stories via Google News search of the ignoring outlets.
Result: run 39006995957 — `blindspot: 1 flagged (left_ignores=1, right_ignores=0) of 1 local multi-outlet stories` (m counts all scored stories, edition.py:145); 3 gnews feeds had a transient 503; job 6m00s. Predicted 3–15 flags — missed: almost no AR story reaches ≥3 AR outlets in one cluster. — no
Verdict & lesson: parked (field kept, no UI) → L12. Root issue → D10.

### D10 — Why Argentine stories rarely cluster across outlets (2026-10-17) — status: kept
Goal: more stories covered by several outlets (owner request: "news should be covered by more than one source"); prerequisite for blindspots.
Evidence: D9 m=1; per-theme multi_outlet only 1–8 of accepted.
Investigation (offline fixture, 15 same-event + 10 hard different-event AR headline pairs): baseline merges 10/15 same, 6/10 wrong. Causes: figures ("1,9%", "1.555") dropped from title tokens; capitalised first words not entities when there is no summary (all gnews items); paraphrases. Lowering the threshold alone trades misses for wrong merges (0.35: 11/15, 8/10).
Options: A) number- and entity-aware score + overlap term (14/15, 7/10 measured); B) A + figure-conflict veto on decimals/≥3-digit numbers (14/15, ~4–5/10); C) B + synonym list (+1).
Decision: B (guards against merging different INDEC releases); C only if the build shows it is needed.
Prediction: fixture same ≥14/15, wrong ≤5/10 (and INDEC Sept vs Aug, riesgo país 648 vs 720, blue 1555 vs oficial 1535 never merge); build per-theme multi_outlet +30–50% (Economía ~7 → ~10); blindspot m 1 → 3–6 (if m stays ≤2, the limit is feed overlap, not scoring).
Measurement: pytest fixture test; next newsdesk.yml per-theme and blindspot lines; investigator samples 10 multi-outlet stories for wrong merges if a debug log exists.
Review round 2: overlap term and name bonus only for titles with ≥4 tokens ("Boca ganó"/"Boca perdió" no longer merge); figures within 1% match (2% merged blue vs oficial). Known limit: outlets quoting different counts (120 vs 135 muertos) split into two stories. Fixture after: 14/15 same, 4/10 wrong.
Result: run 39008682199 — multi_outlet Economía 8→12, Mundo 5→11, Música 1→1, IA 2→2 (total 16→26, +62%); blindspot m 1→8 (2 flagged, both "left ignores", likely service/statistics items: VTV, morosidad); multi-outlet samples 8/8 one event (1 uncertain); job 15m53s (neutral titles at their budget; judge ~4 min). — yes
Verdict & lesson: kept → L13, L14. D9 stays parked until flagged titles are logged and ≥4/5 sampled flags are real political blindspots.

## Owner decisions (grilling, 2026-10-17)
- Order of work: Música → blind spots → IA.
- Unbiased = several leans cover it + neutral titles + official numbers first (see GLOSSARY.md).
- Confirmed story = 3+ outlets or an official source (Música and IA: 2+); sections fill the rest with 2-outlet stories.
- Leans stay approximate and owner-editable.
- Música: news about the owner's artists first (Spotify followed + most played; top 20 by plays), then shows in Argentina + big tours, then big releases. Owner will connect Spotify.
- Blind spots: Argentine politics/economy only; shown as a mark on story cards, only after ≥4/5 sampled flags are real.
- IA: launches and models first; big research results also fit (audit case "protein-structure model" stays IN).

## Open follow-ups (next /improve)
- D9: log flagged blindspot titles + ignoring side; sample 5; show tab only if ≥4/5 real.
- Música/IA: more outlets (Argentine music/espectáculos; owner's artists list is still empty).
- Build time ~16 min when caches are cold: keep an eye on it (neutral titles fill their budget).

### D11 — Música: your artists first, shows, and the confirmed-story rule (2026-10-17) — status: open
Goal: owner decisions (grilling): your artists first in Música, then shows in Argentina + big tours, then big releases; confirmed = 3+ outlets or official (2+ in Música and IA), filled with 2-outlet stories, then single-outlet stories marked "1 medio" only if a section has < 4; your-artist stories always shown; "most played" = Spotify top artists, medium_term (~6 months).
Evidence: Spotify list today = typed + top + followed, cut at 40 (index.html:923-926; judge.py:140) while search cuts at 20 (artists.py:26) — order only right by accident. No artist flag on stories; artist stories get no boost and single-outlet ones are cut by confirmed() (index.html:476). artists.py searches no shows/tours. multi_outlet log counts ≥2 only.
Options: A) strict 3+/2-fill, no single-source; B) A + marked single-source fill below 4; C) B + your-artist bypass.
Decision: C (owner chose marked fill + artist bypass). Shows via fixed Google News queries (unverified, L8 — checked by check-feeds). Threshold computed in Python per theme (testable), not in JS.
Prediction: Música accepted 5 → ≥8 and multi_outlet 1 → ≥3 once show queries run; log `music order: artist=a shows=b releases=c` (artist=0 until Spotify is connected); check-feeds shows the show queries OK; build ≤ 16 min.
Measurement: newsdesk.yml log (theme Música line with new confirmed= count, music order line, samples); audit check-feeds; pytest.
