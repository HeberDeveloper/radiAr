#!/usr/bin/env python3
"""radiAr: arma datos/calendario_eventos.json.
Une 1) eventos manuales con fuente, 2) ferias semanales convertidas en fechas y 3) partidos de las proximas
fechas desde TheSportsDB (gratis; ligas de Argentina y Brasil; endpoint sin verificar: si falla, sigue sin eso).
Argentina, Paraguay y Brasil (hora de Brasilia) usan UTC-3."""
import json
import os
import re
import sys
import unicodedata
import urllib.request
from datetime import datetime, timedelta, timezone

ZONA = timezone(timedelta(hours=-3))
HOY = datetime.now(ZONA).date()
DIAS = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
ADELANTE = 60
API = "https://www.thesportsdb.com/api/v1/json/123/eventsnextleague.php?id="
LIGAS = {"4406": "Liga Profesional (Argentina)", "4351": "Brasileirao Serie A"}
LOCALES = {
    "racing club": ["cilindro", "estadio presidente peron"],
    "independiente": ["bochini 751", "ricardo bochini", "libertadores de america"],
    "lanus": ["ramon cabrero 2007", "estadio ciudad de lanus"],
    "banfield": ["arenales 900", "florencio sola"],
    "rosario central": ["gigante de arroyito", "cordiviola 1100", "genova 640"],
    "newell": ["morcillo 2501", "marcelo bielsa", "coloso del parque"],
    "velez": ["amalfitani", "juan b justo 9200"],
    "huracan": ["tomas adolfo duco", "amancio alcorta 2570"],
    "flamengo": ["maracana"],
    "fluminense": ["maracana"],
    "botafogo": ["nilton santos", "engenhao", "jose dos reis 425"],
    "palmeiras": ["nubank parque", "allianz parque", "francisco matarazzo 1705"],
    "corinthians": ["neo quimica arena", "miguel ignacio curi"],
    "sao paulo": ["morumbi", "roberto gomes pedrosa"],
}


def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def leer(ruta):
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print("no se pudo leer", ruta, str(e)[:100], flush=True)
        return {}


def manuales():
    sal = []
    for e in leer("fuentes/eventos_manuales.json").get("eventos", []):
        if e.get("fecha", "") >= HOY.isoformat():
            sal.append(e)
    return sal


def ferias():
    sal = []
    for f in leer("fuentes/ferias_semanales.json").get("ferias", []):
        for i in range(ADELANTE):
            d = HOY + timedelta(days=i)
            if DIAS[d.weekday()] in f["dias"] and d.month in f.get("meses", range(1, 13)):
                sal.append({"titulo": f["nombre"], "fecha": d.isoformat(), "desde": f["desde"], "hasta": f["hasta"],
                            "claves": f["claves"], "fuente": f["fuente"]})
    return sal


def partidos():
    sal = []
    for liga, nombre in LIGAS.items():
        try:
            req = urllib.request.Request(API + liga, headers={"User-Agent": "radiAr-datos/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                js = json.loads(r.read().decode("utf-8"))
        except Exception as e:
            print("sportsdb fallo", liga, str(e)[:100], flush=True)
            continue
        for ev in js.get("events") or []:
            local = norm(ev.get("strHomeTeam"))
            claves = next((v for k, v in LOCALES.items() if k in local), None)
            if not claves or not ev.get("dateEvent") or not ev.get("strTime"):
                continue
            try:
                utc = datetime.fromisoformat(ev["dateEvent"] + "T" + ev["strTime"][:8]).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            ini = utc.astimezone(ZONA)
            desde = ini - timedelta(hours=2)
            hasta = ini + timedelta(hours=3, minutes=30)
            if desde.date() != ini.date():
                desde = ini.replace(hour=0, minute=0)
            if hasta.date() != ini.date():
                hasta = ini.replace(hour=23, minute=59)
            sal.append({"titulo": f"{ev.get('strHomeTeam')} - {ev.get('strAwayTeam')} ({nombre})",
                        "fecha": ini.date().isoformat(), "desde": desde.strftime("%H:%M"),
                        "hasta": hasta.strftime("%H:%M"), "claves": claves, "fuente": "TheSportsDB"})
    return sal


def main():
    todos = manuales() + ferias() + partidos()
    vistos, final = set(), []
    for e in sorted(todos, key=lambda x: (x["fecha"], x["desde"])):
        k = (e["fecha"], e["desde"], tuple(e["claves"]))
        if k in vistos:
            continue
        vistos.add(k)
        final.append(e)
    if not final:
        print("sin eventos", flush=True)
        sys.exit(1)
    os.makedirs("datos", exist_ok=True)
    with open("datos/calendario_eventos.json", "w", encoding="utf-8") as f:
        json.dump(final, f, ensure_ascii=False, separators=(",", ":"))
    print("eventos:", len(final), "manuales:", len(manuales()), flush=True)


if __name__ == "__main__":
    main()
