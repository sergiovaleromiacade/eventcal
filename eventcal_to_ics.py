"""
Conversor generico eventcal/v1 -> iCalendar (.ics, RFC 5545).
No tiene logica especifica de ninguna fuente: opera sobre el esquema canonico,
asi que sirve igual para F1, conciertos o un viaje. Esta es una proyeccion mas
de la fuente de verdad (el JSON).
"""
import re, hashlib
from datetime import datetime, timezone, date
try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

DOMAIN = "eventcal.org"
STATUS = {"confirmed": "CONFIRMED", "tentative": "TENTATIVE",
          "cancelled": "CANCELLED", "postponed": "TENTATIVE"}

# --- helpers de formato iCalendar ------------------------------------------

def esc(text):
    """Escapa un valor TEXT de iCalendar."""
    s = str(text)
    s = s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    s = s.replace("\r\n", "\\n").replace("\n", "\\n")
    return s

def fold(line):
    """Plegado a 75 octetos con continuacion ' ' (sin partir multibyte)."""
    if len(line.encode("utf-8")) <= 75:
        return line
    out, cur, clen, first = [], "", 0, True
    for ch in line:
        w = len(ch.encode("utf-8"))
        limit = 75 if first else 74
        if clen + w > limit:
            out.append(cur); cur, clen, first = ch, w, False
        else:
            cur += ch; clen += w
    out.append(cur)
    return "\r\n ".join(out)

def parse_dt(s):
    s = s.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return "date", date.fromisoformat(s)
    dt = datetime.fromisoformat(s.replace(" ", "T").replace("Z", "+00:00"))
    return ("aware" if dt.tzinfo else "floating"), dt

def ics_dt(s, tzname):
    """Devuelve (params, valor). Instante->UTC 'Z'; flotante->UTC via tz del
    calendario; solo-fecha->VALUE=DATE."""
    kind, val = parse_dt(s)
    if kind == "date":
        return ";VALUE=DATE", val.strftime("%Y%m%d")
    if kind == "aware":
        return "", val.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if tzname and ZoneInfo:
        try:
            u = val.replace(tzinfo=ZoneInfo(tzname)).astimezone(timezone.utc)
            return "", u.strftime("%Y%m%dT%H%M%SZ")
        except Exception:
            pass
    return "", val.strftime("%Y%m%dT%H%M%S")  # flotante real (sin tz)

def humanize(k):
    return k.replace("_", " ").capitalize()

def render_value(v):
    if isinstance(v, list):
        return ", ".join(str(x).replace("_", " ") for x in v)
    return str(v).replace("_", " ")

# --- construccion de un VEVENT ---------------------------------------------

def uid_for(ev):
    if ev.get("id"):
        return f"{ev['id']}@{DOMAIN}"
    seed = f"{ev.get('title','')}|{ev.get('start','')}"
    return hashlib.sha1(seed.encode()).hexdigest()[:16] + f"@{DOMAIN}"

def build_description(ev):
    lines = []
    if ev.get("status") == "postponed":
        lines.append("(Aplazado)")
    for k, v in (ev.get("details") or {}).items():
        lines.append(f"{humanize(k)}: {render_value(v)}")
    if ev.get("url"):
        lines.append(f"Mas info: {ev['url']}")
    return "\\n".join(esc(x) if x != "(Aplazado)" else x for x in lines)

def vevent(ev, cal, dtstamp):
    tz = cal.get("timezone")
    L = ["BEGIN:VEVENT", f"UID:{uid_for(ev)}", f"DTSTAMP:{dtstamp}"]

    p, v = ics_dt(ev["start"], tz)
    L.append(f"DTSTART{p}:{v}")
    if ev.get("end"):
        p, v = ics_dt(ev["end"], tz)
        L.append(f"DTEND{p}:{v}")

    L.append(f"SUMMARY:{esc(ev['title'])}")
    L.append(f"STATUS:{STATUS.get(ev.get('status', 'confirmed'), 'CONFIRMED')}")

    loc = ev.get("location") or {}
    loc_parts = [loc.get("name"), loc.get("city"), loc.get("country")]
    loc_str = ", ".join(x for x in loc_parts if x)
    if loc_str:
        L.append(f"LOCATION:{esc(loc_str)}")
    if "lat" in loc and "lon" in loc:
        L.append(f"GEO:{loc['lat']};{loc['lon']}")

    if ev.get("url"):
        L.append(f"URL:{ev['url']}")
    img = ev.get("image") or {}
    if img.get("url"):
        L.append(f"ATTACH:{img['url']}")
    if ev.get("partOf"):
        L.append(f"RELATED-TO;RELTYPE=PARENT:{ev['partOf']}@{DOMAIN}")

    cats = [cal.get("category")] + (cal.get("tags") or [])
    cats = [c for c in cats if c]
    if cats:
        L.append(f"CATEGORIES:{esc(','.join(cats))}")
    if ev.get("type"):
        L.append(f"X-EVENTCAL-TYPE:{ev['type']}")

    desc = build_description(ev)
    if desc:
        L.append(f"DESCRIPTION:{desc}")

    L.append("END:VEVENT")
    return L

# --- API principal ---------------------------------------------------------

def to_ics(cal):
    dtstamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0",
        "PRODID:-//eventcal//converter//ES", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
        f"X-WR-CALNAME:{esc(cal.get('name', cal['id']))}",
        "REFRESH-INTERVAL;VALUE=DURATION:PT12H", "X-PUBLISHED-TTL:PT12H",
    ]
    if cal.get("timezone"):
        lines.append(f"X-WR-TIMEZONE:{cal['timezone']}")
    for ev in cal.get("events", []):
        lines += vevent(ev, cal, dtstamp)
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(x) for x in lines) + "\r\n"

if __name__ == "__main__":
    import json, sys
    cal = json.load(open(sys.argv[1]))
    sys.stdout.write(to_ics(cal))
