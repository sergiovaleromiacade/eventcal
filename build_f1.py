"""
Runner de la fase 0: fetch real -> adaptador -> validar -> .ics en public/.
  EVENTCAL_YEAR     temporada (por defecto 2025)
  EVENTCAL_OFFLINE  =1 usa muestra local (pruebas)
"""
import os, re, json, urllib.parse, urllib.request
from collections import Counter
from apply_adapter import load, run_adapter, validate, SAMPLE
from eventcal_to_ics import to_ics

YEAR = int(os.environ.get("EVENTCAL_YEAR", "2025"))
OFFLINE = os.environ.get("EVENTCAL_OFFLINE") == "1"
OUT_DIR = "public"


def _interp(s, params):
    return re.sub(r"\{params\.(\w+)\}", lambda m: str(params[m.group(1)]), s)


def fetch_sources(adapter, params, timeout=30):
    sources = {}
    for st in adapter["streams"]:
        f = st["fetch"]
        query = {k: _interp(v, params) for k, v in (f.get("query") or {}).items()}
        url = f["url"] + ("?" + urllib.parse.urlencode(query) if query else "")
        req = urllib.request.Request(url, headers={"User-Agent": "eventcal/0.1"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            sources[st["id"]] = json.load(r)
        print(f"  fetch {st['id']}: {len(sources[st['id']])} registros")
    return sources


def session_mapping(adapter):
    for st in adapter["streams"]:
        m = (st.get("mapping", {}).get("details", {}) or {}).get("session")
        if isinstance(m, dict) and "map" in m:
            return st["id"], m["from"], m["map"]
    return None, None, None


def main():
    print(">>> build_f1: diagnostico v2 <<<")
    adapter = load("openf1.adapter.json")
    params = {"year": YEAR}

    if OFFLINE:
        print("MODO OFFLINE: usando muestra local")
        sources = SAMPLE
    else:
        print(f"Trayendo datos reales (temporada {YEAR})...")
        sources = fetch_sources(adapter, params)

    # Distribucion COMPLETA del campo que alimenta details.session (incluye vacios)
    sid, field, table = session_mapping(adapter)
    if sid:
        counts = Counter(r.get(field) for r in sources.get(sid, []))
        print(f"\nValores de '{field}' en el stream '{sid}':")
        for val, n in counts.most_common():
            if val is None:
                shown, mark = "<vacio/null>", "VACIO"
            elif val in table:
                shown, mark = repr(val), "ok"
            else:
                shown, mark = repr(val), "SIN MAPEAR"
            print(f"   {shown:26} x{n:<3} [{mark}]")
        bad = [v for v in counts if v not in table]   # None tambien cae aqui
        if bad:
            print("\n*** El adaptador no sabe traducir estos valores: ***")
            for v in bad:
                print("   -", repr(v) if v is not None else "<vacio/null>")
            print("\nSolucion: anade cada nombre al 'map' de details.session en")
            print("openf1.adapter.json. Para <vacio/null> habria que filtrar esos")
            print("registros (sesiones sin nombre); dime si aparece y lo vemos.")
            raise SystemExit(1)

    calendar = run_adapter(adapter, params, sources)
    err = validate(calendar)
    if err:
        raise SystemExit(f"ABORTADO, no valida: {err}")

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, f"f1-{YEAR}.json"), "w", encoding="utf-8") as fp:
        json.dump(calendar, fp, ensure_ascii=False, indent=2)
    with open(os.path.join(OUT_DIR, f"f1-{YEAR}.ics"), "w", newline="", encoding="utf-8") as fp:
        fp.write(to_ics(calendar))
    print(f"\nOK -> public/f1-{YEAR}.ics ({len(calendar['events'])} eventos)")


if __name__ == "__main__":
    main()
