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
