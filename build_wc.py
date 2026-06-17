"""
Runner del Mundial: fetch openfootball -> normalizar -> adaptador -> validar -> .ics
en public/.

Por que existe la normalizacion aqui (y no en el adaptador): openfootball expone
'time' como 'HH:MM UTC-N' (p.ej. '13:00 UTC-6'), formato no-ISO que el vocabulario
declarativo de adaptadores no parsea. Documentado en HANDOFF.md seccion 5.5. La
disciplina: este script hace 'fetch + normalizacion minima de formato'; el
adaptador hace el mapeo a eventcal/v1 con datos ya limpios.

Vars de entorno:
  EVENTCAL_YEAR     temporada (por defecto 2026)
  EVENTCAL_OFFLINE  =1 usa muestra local (no implementado todavia)
"""
import os, re, json, urllib.parse, urllib.request
from apply_adapter import load, run_adapter, validate

YEAR = int(os.environ.get("EVENTCAL_YEAR", "2026"))
OUT_DIR = "public"

# --- normalizacion de la fuente openfootball -------------------------------

VENUE_COUNTRY = {
    "Atlanta": "US",
    "Boston (Foxborough)": "US",
    "Dallas (Arlington)": "US",
    "Houston": "US",
    "Kansas City": "US",
    "Los Angeles (Inglewood)": "US",
    "Miami (Miami Gardens)": "US",
    "New York/New Jersey (East Rutherford)": "US",
    "Philadelphia": "US",
    "San Francisco Bay Area (Santa Clara)": "US",
    "Seattle": "US",
    "Toronto": "CA",
    "Vancouver": "CA",
    "Guadalajara (Zapopan)": "MX",
    "Mexico City": "MX",
    "Monterrey (Guadalupe)": "MX",
}

STAGE_FROM_ROUND = {
    "Round of 32": "round_of_32",
    "Round of 16": "round_of_16",
    "Quarter-final": "quarter_final",
    "Semi-final": "semi_final",
    "Match for third place": "third_place",
    "Final": "final",
}

# Formato openfootball: "13:00 UTC-6", "12:00 UTC-4", etc.
TIME_RE = re.compile(r"^(\d{2}):(\d{2})\s+UTC([+-])(\d+)$")

# Para ids de fase de grupos. Selecciones nacionales son estables; el id
# tampoco es legible para el usuario, asi que slug agresivo esta bien.
def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def to_iso(date_str, time_str):
    """'2026-06-11', '13:00 UTC-6' -> '2026-06-11T13:00:00-06:00'."""
    if not date_str or not time_str:
        return None
    m = TIME_RE.match(time_str.strip())
    if not m:
        return None
    h, mn, sign, off = m.groups()
    return f"{date_str}T{h}:{mn}:00{sign}{int(off):02d}:00"


def make_id(rec, year):
    # Eliminatorias: 'num' estable (1..104). Grupos: clave natural date+teams.
    # Selecciones nacionales son notablemente estables; openfootball cambia los
    # placeholders 'W89' por el ganador real cuando llega: ese cambio en team1/2
    # SI mueve el id. Aceptable: los partidos de grupos no usan placeholders, y
    # en knockout usamos 'num' que no se ve afectado.
    if "num" in rec:
        return f"wc{year}-m{rec['num']}"
    return f"wc{year}-{rec['date']}-{slug(rec['team1'])}-vs-{slug(rec['team2'])}"


def stage_of(rec):
    r = rec.get("round", "")
    if r.startswith("Matchday"):
        return "group"
    return STAGE_FROM_ROUND.get(r)


def normalize(rec, year):
    start = to_iso(rec.get("date"), rec.get("time"))
    stage = stage_of(rec)
    score = rec.get("score") or {}
    ft = score.get("ft") or []
    out = {
        "id": make_id(rec, year),
        "start": start,
        "team1": rec.get("team1"),
        "team2": rec.get("team2"),
        "ground": rec.get("ground"),
        "country_code": VENUE_COUNTRY.get(rec.get("ground")),
        "stage": stage,
    }
    # opcionales: solo si vienen, para que el adaptador (via 'from' + None drop)
    # no meta claves vacias en details
    if rec.get("group"):
        out["group"] = rec["group"]
    if "num" in rec:
        out["num"] = rec["num"]
    if len(ft) == 2:
        out["homeScore"] = ft[0]
        out["awayScore"] = ft[1]
    return out


# --- fetch ----------------------------------------------------------------

def _interp(s, params):
    return re.sub(r"\{params\.(\w+)\}", lambda m: str(params[m.group(1)]), s)


def fetch_matches(adapter, params, timeout=30):
    fetch = adapter["streams"][0]["fetch"]
    url = _interp(fetch["url"], params)
    req = urllib.request.Request(url, headers={"User-Agent": "eventcal/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = json.load(r)
    matches = raw.get("matches") or []
    print(f"  fetch openfootball: {len(matches)} partidos crudos ({url})")
    return matches


# --- main -----------------------------------------------------------------

def main():
    print(">>> build_wc: Copa Mundial de la FIFA <<<")
    adapter = load("openfootball-wc.adapter.json")
    params = {"year": YEAR}

    raw_matches = fetch_matches(adapter, params)
    records = [normalize(m, YEAR) for m in raw_matches]

    # diagnostico: rondas no mapeadas (las que devolverian stage=None)
    sin_stage = [r for r in records if r["stage"] is None]
    if sin_stage:
        from collections import Counter
        bad = Counter(rm.get("round") for rm in raw_matches if stage_of(rm) is None)
        print("\n*** Rondas que el runner no sabe traducir a 'stage': ***")
        for v, n in bad.most_common():
            print(f"   {v!r} x{n}")
        print("\nSolucion: anade la entrada al STAGE_FROM_ROUND de build_wc.py o,")
        print("si es de fase de grupos, ajusta el prefijo en stage_of().")
        raise SystemExit(1)

    # diagnostico: venues sin pais
    sin_pais = sorted({r["ground"] for r in records if r["country_code"] is None and r["ground"]})
    if sin_pais:
        print("\nAviso: venues sin pais en VENUE_COUNTRY (location.country saldra vacio):")
        for v in sin_pais:
            print(f"   {v!r}")

    sources = {"matches": records}
    calendar = run_adapter(adapter, params, sources)

    err = validate(calendar)
    if err:
        raise SystemExit(f"ABORTADO, no valida: {err}")

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, f"wc-{YEAR}.json"), "w", encoding="utf-8") as fp:
        json.dump(calendar, fp, ensure_ascii=False, indent=2)
    # reutilizamos el conversor generico
    from eventcal_to_ics import to_ics
    with open(os.path.join(OUT_DIR, f"wc-{YEAR}.ics"), "w", newline="", encoding="utf-8") as fp:
        fp.write(to_ics(calendar))
    print(f"\nOK -> public/wc-{YEAR}.ics ({len(calendar['events'])} partidos)")


if __name__ == "__main__":
    main()
