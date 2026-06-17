import json, os, sys
from jsonschema.validators import Draft202012Validator as V

BASE = os.path.dirname(os.path.abspath(__file__))

def load(p): return json.load(open(os.path.join(BASE, p)))

core = load("eventcal.schema.json")
registry = load("registry.json")["types"]
instances = load("instances.json")

V.check_schema(core)
core_validator = V(core, format_checker=V.FORMAT_CHECKER)

# Cache de validadores de extension por type
ext_cache = {}
def ext_validator(t):
    if t not in ext_cache:
        spec = registry[t]
        sch = load(spec["file"])
        V.check_schema(sch)
        ext_cache[t] = V(sch, format_checker=V.FORMAT_CHECKER)
    return ext_cache[t]

def validate_doc(doc):
    # Fase 1: esqueleto contra el nucleo
    errs = sorted(core_validator.iter_errors(doc), key=lambda e: e.path)
    if errs:
        e = errs[0]
        loc = "/".join(str(p) for p in e.absolute_path) or "(raiz)"
        return ("fase 1 (nucleo)", f"{loc}: {e.message[:70]}")
    # Fase 2: details de cada evento contra su extension
    for i, ev in enumerate(doc.get("events", [])):
        t = ev.get("type")
        if not t:
            continue
        if t not in registry:
            # Tipo desconocido: pasa el esqueleto, sin validacion profunda
            continue
        details = ev.get("details", {})
        derrs = sorted(ext_validator(t).iter_errors(details), key=lambda e: e.path)
        if derrs:
            e = derrs[0]
            loc = f"events/{i}/details/" + "/".join(str(p) for p in e.absolute_path)
            return (f"fase 2 ({t})", f"{loc.rstrip('/')}: {e.message[:60]}")
    return (None, None)

print("Validacion en dos fases (nucleo + registro)\n")
print(f"{'instancia':<28} {'esperado':<9} {'resultado':<11} {'donde fallo'}")
print("-"*82)
for name, doc in instances.items():
    phase, msg = validate_doc(doc)
    ok = phase is None
    expected_ok = name.startswith("valid")
    verdict = "OK" if ok == expected_ok else "!! INESPERADO"
    res = "valido" if ok else "rechazado"
    where = "" if ok else phase
    note = " [tipo desconocido: solo esqueleto]" if name == "valid_unknown_type" else ""
    print(f"{name:<28} {'valido' if expected_ok else 'rechazo':<9} {res:<11} {where}{('  '+verdict) if verdict!='OK' else ''}{note}")
    if not ok and not expected_ok:
        print(f"      -> {msg}")
