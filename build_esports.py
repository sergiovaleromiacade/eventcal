"""
Runner de esports (Dota 2 via PandaScore).

Razones para vivir aqui y no en apply_adapter:
- PandaScore requiere Authorization header con API token. El motor de
  apply_adapter no entiende headers ni secretos (a proposito: el evaluator
  trabaja sobre datos ya descargados).
- El runner hace fetch con headers, normaliza el JSON anidado de PandaScore
  (match->opponents[].opponent.name, match->tournament.name, etc.) a un
  registro plano con prefijo _ y se lo pasa al adaptador. El adaptador hace
  el mapeo declarativo final a eventcal/v1.
- La interpolacion {secret.X} en fetch.headers/url/query es la PRIMERA
  extension del shape del adaptador desde v1. Sigue siendo declarativa
  (textual replacement, sin codigo). Documentado en HANDOFF.md seccion 5.2.

Vars de entorno:
  PANDASCORE_TOKEN  API key (requerido). Obtener gratis en pandascore.co
"""
import os, re, json, urllib.parse, urllib.request
from apply_adapter import load, run_adapter, validate
from eventcal_to_ics import to_ics

OUT_DIR = "public"

INTERP_PARAMS = re.compile(r"\{params\.(\w+)\}")
INTERP_SECRET = re.compile(r"\{secret\.(\w+)\}")


def interp(s, params):
    """Interpola {params.X} desde el dict params y {secret.X} desde os.environ.
    Si falta un secreto, error claro. Los params los validamos antes de aqui."""
    s = INTERP_PARAMS.sub(lambda m: str(params[m.group(1)]), s)
    def _secret(m):
        name = m.group(1)
        v = os.environ.get(name)
        if v is None:
            raise SystemExit(f"FALTA secreto requerido: variable de entorno {name!r} no esta definida")
        return v
    return INTERP_SECRET.sub(_secret, s)


def fetch_matches(adapter, params, timeout=30):
    stream = adapter["streams"][0]
    f = stream["fetch"]
    url = interp(f["url"], params)
    query = {k: interp(v, params) for k, v in (f.get("query") or {}).items()}
    if query:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(query)
    headers = {"User-Agent": "eventcal/0.1"}
    for k, v in (f.get("headers") or {}).items():
        headers[k] = interp(v, params)
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.load(r)
    print(f"  fetch PandaScore: {len(data)} partidos")
    return data


# --- normalizacion del shape de PandaScore --------------------------------
#
# PandaScore devuelve algo como:
#   { id, name, begin_at, end_at, status, number_of_games, match_type,
#     official_stream_url,
#     opponents: [ {opponent: {name, id}}, {opponent: {name, id}} ],
#     tournament: { name, ... }, serie: { name }, league: { name } }
#
# Aplanamos los campos anidados a llaves planas con prefijo "_" para que el
# adaptador los acceda con "from": "_team1_name" sin necesitar lookup
# por path anidado (el evaluator hace dotted lookup, pero queremos mantener
# el adaptador legible sin "opponents.0.opponent.name").

FORMAT_BY_NGAMES = {1: "bo1", 3: "bo3", 5: "bo5", 7: "bo7"}


def opponent_at(rec, i):
    opps = rec.get("opponents") or []
    if len(opps) > i and opps[i] and opps[i].get("opponent"):
        return opps[i]["opponent"].get("name")
    return "TBD"


def score_at(rec, i):
    results = rec.get("results") or []
    if len(results) > i and isinstance(results[i], dict):
        return results[i].get("score")
    return None


def normalize(rec):
    rec = dict(rec)
    rec["_team1_name"] = opponent_at(rec, 0)
    rec["_team2_name"] = opponent_at(rec, 1)
    rec["_team1_score"] = score_at(rec, 0)
    rec["_team2_score"] = score_at(rec, 1)
    # Mapeo de la jerarquia de PandaScore -> semantica humana (verificado con
    # datos reales el 2026-06-17):
    #   league.name        circuito ("The International", "ESL Pro Tour")
    #   serie.full_name    edicion ("South America Closed Qualifier 2026")
    #                       = lo que el humano llama "torneo"
    #   tournament.name    fase dentro de la serie ("Group Stage", "Playoffs")
    #                       = lo que el humano llama "stage"
    serie = rec.get("serie") or {}
    rec["_league_name"] = (rec.get("league") or {}).get("name")
    rec["_tournament_name"] = serie.get("full_name") or serie.get("name")
    rec["_stage"] = (rec.get("tournament") or {}).get("name")
    # match_type es 'best_of' habitualmente; number_of_games es el N
    rec["_match_format"] = FORMAT_BY_NGAMES.get(rec.get("number_of_games"))
    return rec


def main():
    print(">>> build_esports: Dota 2 via PandaScore <<<")
    adapter = load("pandascore-dota2.adapter.json")
    params = {"game": "dota2"}

    raw = fetch_matches(adapter, params)
    records = [normalize(r) for r in raw]

    sources = {"matches": records}
    calendar = run_adapter(adapter, params, sources)

    err = validate(calendar)
    if err:
        raise SystemExit(f"ABORTADO, no valida: {err}")

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "esports-dota2.json"), "w", encoding="utf-8") as fp:
        json.dump(calendar, fp, ensure_ascii=False, indent=2)
    with open(os.path.join(OUT_DIR, "esports-dota2.ics"), "w", newline="", encoding="utf-8") as fp:
        fp.write(to_ics(calendar))
    print(f"\nOK -> public/esports-dota2.ics ({len(calendar['events'])} partidos)")


if __name__ == "__main__":
    main()
