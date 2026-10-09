"""Check how the AI theme filter decides, with the real model: `python -m newsdesk audit`.

1. Test: example stories whose right answer is known, for each of your themes
   (matched by subject: AI, Argentine economy, world, music). Shows the score and every mistake.
2. Today: the real candidate stories for each theme, with the model's verdict, so a person
   can read through and spot wrong calls.

Nothing is cached or published; it only prints a report (and a GitHub job summary).
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone

from .cluster import cluster
from .config import load_sources
from .fetch import fetch_all
from .judge import BATCH, PER_THEME, _ask, _material, candidates, configured_themes, theme_key
from .neutral import _provider
from .rank import score_stories

# (subject words found in the theme, [(headline, excerpt, fits?)])
CASES = {
    "ai": (["inteligencia artificial", " ia ", " ai ", "artificial intelligence"], [
        ("OpenAI launches GPT-6 with stronger reasoning", "The company released its new flagship model to developers.", True),
        ("Google DeepMind presenta Gemini 3, su nuevo modelo multimodal", "El laboratorio anunció el modelo en su blog oficial.", True),
        ("Anthropic announces new Claude model for scientific research", "The model is available today through its API.", True),
        ("Nvidia unveils new chip to train large AI models", "The processor will ship to data centres next year.", True),
        ("Investigadores publican un modelo de IA que predice estructuras de proteínas", "El trabajo salió en la revista Nature.", True),
        ("Startup lanza una app con un agente de IA para contar calorías", "La aplicación sugiere menús según el peso del usuario.", False),
        ("Opinion: is AI making students lazy?", "A columnist argues schools should ban chatbots.", False),
        ("Acciones de Nvidia suben 4% en Wall Street", "Los inversores apuestan por la demanda de chips.", False),
        ("Demanda contra OpenAI por derechos de autor avanza en un tribunal", "Un juez rechazó desestimar el caso.", False),
        ("Teachers worry about pupils using ChatGPT for homework", "Parents and schools debate new rules.", False),
        ("El Banco Central sube la tasa de interés", "La medida busca contener la inflación.", False),
    ]),
    "economy": (["economia argentina", "economia del pais", "economia local"], [
        ("El INDEC informó que la inflación de septiembre fue de 2,1%", "El índice acumula 25% en el año.", True),
        ("El BCRA compró USD 150 millones y las reservas suben", "Las reservas brutas llegaron a USD 32.000 millones.", True),
        ("La actividad económica creció 0,8% en agosto, según el EMAE", "El dato del INDEC superó lo esperado.", True),
        ("El desempleo en Argentina bajó a 6,9% en el segundo trimestre", "Lo informó el INDEC.", True),
        ("El Gobierno anunció una baja de retenciones al trigo", "La medida rige desde el lunes.", True),
        ("Brazil's central bank holds rates at 10.5%", "Policymakers cited sticky inflation.", False),
        ("Opinión: el plan económico está condenado al fracaso", "Una columna sobre el rumbo del Gobierno.", False),
        ("Messi marcó un doblete en la victoria de Inter Miami", "El argentino fue la figura del partido.", False),
        ("La inflación en España se modera al 2,3%", "El dato del INE para septiembre.", False),
        ("Taylor Swift anuncia gira con fechas en Buenos Aires", "Las entradas salen a la venta el lunes.", False),
    ]),
    "world": (["mundo", "world", "internacional"], [
        ("Israel y Hamas acuerdan un alto el fuego en Gaza", "El acuerdo fue mediado por Egipto y Qatar.", True),
        ("UN warns of famine in parts of Sudan", "Aid agencies say access is blocked.", True),
        ("Terremoto de magnitud 7 sacude el norte de Japón", "Se emitió una alerta de tsunami.", True),
        ("Alemania celebra elecciones anticipadas", "Los conservadores lideran las encuestas.", True),
        ("Ukraine and Russia exchange hundreds of prisoners", "The swap was brokered by the UAE.", True),
        ("Boca le ganó a River 2-1 en el Superclásico", "Fue en La Bombonera.", False),
        ("Receta: cómo hacer pan casero en 30 minutos", "Solo hacen falta cuatro ingredientes.", False),
        ("El INDEC informó que la inflación de septiembre fue de 2,1%", "El índice acumula 25% en el año.", False),
        ("Bad Bunny lanza un álbum sorpresa", "El disco tiene 17 canciones.", False),
    ]),
    "music": (["musica", "music"], [
        ("Taylor Swift anuncia gira mundial con fechas en Buenos Aires", "Las entradas salen a la venta el lunes.", True),
        ("Bad Bunny lanza un álbum sorpresa", "El disco tiene 17 canciones.", True),
        ("Lollapalooza Argentina confirma su line-up 2027", "Encabezan tres bandas internacionales.", True),
        ("Radiohead releases its first single in eight years", "The song arrives ahead of a new album.", True),
        ("Coldplay suma una nueva fecha en River Plate", "La primera se agotó en horas.", True),
        ("Cantante condenada por evasión fiscal", "Deberá pagar una multa millonaria.", False),
        ("Spotify sube el precio de su suscripción en Argentina", "El aumento rige desde noviembre.", False),
        ("El INDEC informó que la inflación de septiembre fue de 2,1%", "El índice acumula 25% en el año.", False),
        ("Netflix estrena una serie sobre la vida de un futbolista", "Llega a la plataforma el viernes.", False),
        ("OpenAI launches GPT-6 with stronger reasoning", "The company released its new flagship model.", False),
    ]),
}


def _case_set(theme: str):
    t = f" {theme_key(theme)} "
    for name, (subjects, cases) in CASES.items():
        if any(w in t for w in subjects):
            return name, cases
    return None, []


def run(cfg, out=print) -> int:
    themes = configured_themes(cfg)
    provider = _provider(cfg.get("neutral_titles") or {}, None)
    if not themes:
        out("No themes: set NEWSDESK_THEMES (the app sends them) or `themes:` in config.yaml.")
        return 1
    if provider != "local" and provider != "anthropic":
        out("No AI model available (start Ollama and set NEWSDESK_LOCAL_MODEL, or ANTHROPIC_API_KEY).")
        return 1
    client = None
    if provider == "anthropic":
        import anthropic

        client = anthropic.Anthropic()
    model = os.environ.get("NEWSDESK_LOCAL_MODEL", "") if provider == "local" else cfg["neutral_titles"]["model"]
    now = datetime.now(timezone.utc)
    lines: list[str] = [f"# AI theme filter check ({provider}: {model})", ""]

    def ask(theme, items):
        got, t0 = {}, time.time()
        for i in range(0, len(items), BATCH):
            part = items[i:i + BATCH]
            try:
                got.update(_ask(provider, client, model, theme, part))
            except Exception as exc:
                lines.append(f"- (error: {type(exc).__name__}: {exc})")
        return got, time.time() - t0

    # 1. Test with known answers.
    lines += ["## 1. Test with known answers", ""]
    total = right = 0
    for theme in themes:
        name, cases = _case_set(theme)
        if not cases:
            lines += [f"### {theme}", "_(no example stories for this subject)_", ""]
            continue
        items = [(f"c{i}", {"headlines": [h], "excerpt": e}) for i, (h, e, _) in enumerate(cases)]
        got, secs = ask(theme, items)
        ok = [got.get(f"c{i}") == want for i, (_, _, want) in enumerate(cases)]
        total += len(cases)
        right += sum(ok)
        lines += [f"### {theme}", f"**{sum(ok)}/{len(cases)} right** ({secs:.0f}s)", ""]
        for (h, _, want), good, i in zip(cases, ok, range(len(cases))):
            if not good:
                said = got.get(f"c{i}")
                lines.append(f"- ✗ {h} — should be {'IN' if want else 'OUT'}, model said "
                             f"{'IN' if said else 'OUT' if said is False else 'nothing'}")
        lines.append("")
    if total:
        lines += [f"**Overall: {right}/{total} right ({100 * right // total}%)**", ""]

    # 2. Today's real news.
    lines += ["## 2. Today's news, as the filter sees it", ""]
    articles = fetch_all(load_sources(cfg), country=cfg["profile"]["country"])
    stories = score_stories(cluster(articles), cfg, now)
    for theme in themes:
        cands = candidates(theme, stories)[:PER_THEME]
        items = [(str(i), _material(s)) for i, s in enumerate(cands)]
        got, secs = ask(theme, items)
        ins = [s for i, s in enumerate(cands) if got.get(str(i))]
        outs = [s for i, s in enumerate(cands) if got.get(str(i)) is False]
        lines += [f"### {theme}", f"{len(cands)} candidates → **{len(ins)} in**, {len(outs)} out ({secs:.0f}s)", ""]
        lines += [f"- ✔ {s.headline.title} — _{', '.join(s.outlets[:3])}_" for s in ins]
        lines += [f"- ✘ {s.headline.title} — _{', '.join(s.outlets[:3])}_" for s in outs]
        lines.append("")

    report = "\n".join(lines)
    out(report)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(report + "\n")
    return 0
