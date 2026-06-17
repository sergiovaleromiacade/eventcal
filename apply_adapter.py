"""
Interprete del adaptador declarativo eventcal-adapter/v1.
Ejecuta el vocabulario cerrado de mapeadores (const, from[+map], template, cases,
objetos anidados) sobre registros de origen y produce un calendario eventcal/v1.
No hay evaluacion de codigo arbitrario: caja de arena por construccion.
"""
import json, os, re
from jsonschema.validators import Draft202012Validator as V

BASE = os.path.dirname(os.path.abspath(__file__))
def load(p): return json.load(open(os.path.join(BASE, p)))

# --- nucleo del interprete -------------------------------------------------

def lookup(ctx, path):
    cur = ctx
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur

TOKEN = re.compile(r"\{([^}]+)\}")
def render_template(tpl, ctx):
    missing = []
    def repl(m):
        v = lookup(ctx, m.group(1))
        if v is None:
            missing.append(m.group(1))
            return ""
        return str(v)
    out = TOKEN.sub(repl, tpl)
    return None if missing else out

MAPPER_KEYS = {"const", "from", "template", "cases"}
def is_mapper(node):
    return isinstance(node, dict) and any(k in node for k in MAPPER_KEYS)

def evaluate(node, ctx):
    if is_mapper(node):
        if "const" in node:
            return node["const"]
        if "template" in node:
            return render_template(node["template"], ctx)
        if "from" in node:
            val = lookup(ctx, node["from"])
            if "map" in node:
                return node["map"].get(val, node.get("default"))
            return val if val is not None else node.get("default")
        if "cases" in node:
            for case in node["cases"]:
                if lookup(ctx, case["from"]) == case.get("equals"):
                    return case["value"]
            return node.get("default")
    if isinstance(node, dict):  # objeto anidado: recurse, descartando None
        out = {k: r for k, v in node.items() if (r := evaluate(v, ctx)) is not None}
        return out or None
    return node

def run_adapter(adapter, params, sources):
    calendar = evaluate(adapter["calendar"], {"params": params}) or {}
    events = []
    for stream in adapter["streams"]:
        for rec in sources.get(stream["id"], []):
            ev = evaluate(stream["mapping"], {**rec, "params": params})
            if ev:
                events.append(ev)
    calendar["events"] = events
    return calendar

# --- validacion en dos fases (reutiliza el estandar) -----------------------

def validate(doc):
    core = V(load("eventcal.schema.json"), format_checker=V.FORMAT_CHECKER)
    registry = load("registry.json")["types"]
    errs = list(core.iter_errors(doc))
    if errs:
        return f"fase 1 (nucleo): {errs[0].message[:70]}"
    for i, ev in enumerate(doc.get("events", [])):
        t = ev.get("type")
        if not t or t not in registry:
            continue
        sv = V(load(registry[t]["file"]), format_checker=V.FORMAT_CHECKER)
        de = list(sv.iter_errors(ev.get("details", {})))
        if de:
            return f"fase 2 ({t}) en events/{i}: {de[0].message[:60]}"
    return None

# --- muestra representativa de OpenF1 --------------------------------------
# La sesion "Sprint Qualifying" (session_key 9140, meeting_key 1216) son
# valores REALES confirmados de la API. La carrera (9141) es ilustrativa.

SAMPLE = {
    "meetings": [
        {"meeting_key": 1216, "meeting_name": "Belgian Grand Prix",
         "location": "Spa-Francorchamps", "country_code": "BEL",
         "country_name": "Belgium", "date_start": "2023-07-28T11:30:00+00:00",
         "year": 2023, "is_cancelled": False}
    ],
    "sessions": [
        {"session_key": 9140, "meeting_key": 1216, "session_name": "Sprint Qualifying",
         "date_start": "2023-07-29T15:05:00+00:00", "date_end": "2023-07-29T15:35:00+00:00",
         "location": "Spa-Francorchamps", "country_code": "BEL", "year": 2023, "is_cancelled": False},
        {"session_key": 9141, "meeting_key": 1216, "session_name": "Race",
         "date_start": "2023-07-30T13:00:00+00:00", "date_end": "2023-07-30T15:00:00+00:00",
         "location": "Spa-Francorchamps", "country_code": "BEL", "year": 2023, "is_cancelled": False}
    ]
}

if __name__ == "__main__":
    adapter = load("openf1.adapter.json")
    calendar = run_adapter(adapter, {"year": 2023}, SAMPLE)
    print(json.dumps(calendar, ensure_ascii=False, indent=2))
    print("\n" + "-"*60)
    err = validate(calendar)
    print("VALIDACION:", "rechazado -> " + err if err else "eventcal/v1 valido")
