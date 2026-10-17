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

### D6 — Balanced sources + coverage/lean view + per-theme metrics (2026-10-17) — status: open
Goal: interesting, unbiased news that fits the owner's themes, modelled on existing apps.
Evidence: (investigators) Página/12 feed 404 and Rolling Stone ES 403, so only 5 working AR outlets, mostly centre/centre-right; 1 economy feed (Ámbito home); no lean field anywhere; Economía accepted 6/25 in the audit, mostly single-outlet opinion; music 4/16; the build logs no per-theme counts. Ground News/AllSides/Google Full Coverage show the spread of coverage by lean and each outlet's headline; Semafor separates news from views.
Options: A) sources + lean labels + coverage bar + side-by-side headlines + per-theme log; B) economy data card (INDEC/BCRA); C) Semafor-style summaries with the 7B model; D) Blindspot tab.
Decision: A first (cheap, no model calls, makes everything else measurable). B, D next; C later (risk of invented facts, CI time).
Prediction: working AR outlets 5 → ≥8; AR economy feeds 1 → ≥3; build log prints per theme candidates/accepted/multi-outlet; every multi-outlet story shows a lean bar and per-outlet headlines; build time +<1 min.
Measurement: newsdesk.yml run log (fetch line, warnings, new per-theme line, duration); pytest.
