#!/usr/bin/env python3
"""radiAr: estadios y recintos de eventos de AR, PY y BR (todo el territorio).
OpenStreetMap (ODbL): nombre, direccion y coordenadas. Wikidata (CC0): capacidad y direccion."""
import json
import os
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime, timezone

UA = {"User-Agent": "radiAr-datos/1.0 (github actions)"}
OVERPASS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
SPARQL = "https://query.wikidata.org/sparql"
PAISES = {"AR": "Q414", "PY": "Q733", "BR": "Q155"}
CAP_MIN = 3000
PREFIJOS = {"av", "avenida", "calle", "pasaje", "pje", "diagonal", "diag", "bv",
            "boulevard", "rua", "alameda", "praca"}


def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def entero(v):
    d = re.sub(r"[^\d]", "", str(v or "").split(";")[0])
    return int(d) if d else None


def calle_num(direccion):
    n = norm(direccion)
    if not n:
        return None, None
    m = re.match(r"^(?:calle|diagonal|diag)\s+(\d+(?: bis)?)(?:\s+(\d{1,5}))?", n)
    if m:
        return "calle " + m.group(1), int(m.group(2)) if m.group(2) else None
    m = re.search(r"\b(\d{1,5})\b", n)
    if m:
        calle, num = n[:m.start()].strip(), int(m.group(1))
    else:
        calle, num = n, None
    partes = calle.split()
    while len(partes) > 1 and partes[0] in PREFIJOS:
        partes.pop(0)
    return (" ".join(partes) or None), num


def http(url, datos=None, timeout=300):
    req = urllib.request.Request(url, data=datos, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def consulta_osm(iso):
    return (
        '[out:json][timeout:600];\n'
        f'area["ISO3166-1"="{iso}"][admin_level=2]->.a;\n'
        '(\n'
        '  nwr(area.a)["leisure"="stadium"]["name"];\n'
        '  nwr(area.a)["building"="stadium"]["name"];\n'
        '  nwr(area.a)["amenity"="events_venue"]["name"]["capacity"];\n'
        '  nwr(area.a)["leisure"="sports_hall"]["name"]["capacity"];\n'
        '  nwr(area.a)["amenity"="theatre"]["name"]["capacity"];\n'
        '  nwr(area.a)["amenity"="conference_centre"]["name"]["capacity"];\n'
        ');\nout tags center;')


def overpass(iso):
    datos = urllib.parse.urlencode({"data": consulta_osm(iso)}).encode("utf-8")
    for intento in range(3):
        for url in OVERPASS:
            try:
                return json.loads(http(url, datos, 660).decode("utf-8"))
            except Exception as e:
                print("fallo", url, intento, str(e)[:120], flush=True)
                time.sleep(30)
    return None


def wikidata(qid):
    q = ('SELECT ?item ?itemLabel ?cap ?coord ?dir ?lugarLabel WHERE { '
         f'?item wdt:P31/wdt:P279* wd:Q483110; wdt:P17 wd:{qid}. '
         'OPTIONAL { ?item wdt:P1083 ?cap. } OPTIONAL { ?item wdt:P625 ?coord. } '
         'OPTIONAL { ?item wdt:P6375 ?dir. } OPTIONAL { ?item wdt:P131 ?lugar. } '
         'SERVICE wikibase:label { bd:serviceParam wikibase:language "es,pt,en". } }')
    url = SPARQL + "?format=json&query=" + urllib.parse.quote(q)
    try:
        js = json.loads(http(url, timeout=180).decode("utf-8"))
    except Exception as e:
        print("wikidata fallo", str(e)[:120], flush=True)
        return {}
    salida = {}
    for b in js["results"]["bindings"]:
        nombre = b.get("itemLabel", {}).get("value", "")
        if not nombre or re.match(r"^Q\d+$", nombre):
            continue
        lat = lon = None
        m = re.match(r"Point\(([-\d.]+) ([-\d.]+)\)", b.get("coord", {}).get("value", ""))
        if m:
            lon, lat = float(m.group(1)), float(m.group(2))
        salida[norm(nombre)] = {
            "nombre": nombre, "cap": entero(b.get("cap", {}).get("value")),
            "dir": b.get("dir", {}).get("value"),
            "lugar": b.get("lugarLabel", {}).get("value"), "lat": lat, "lon": lon}
    return salida


def armar(nombre, alts, direccion, localidad, cap, tipo, lat, lon, fuente):
    claves = []
    for x in [nombre] + list(alts):
        k = norm(x)
        if k and k not in claves:
            claves.append(k)
    calle, num = calle_num(direccion)
    return {"n": nombre, "k": claves, "d": direccion or None, "c": calle, "h": num,
            "l": localidad or None, "cap": cap, "t": tipo, "la": lat, "lo": lon, "f": fuente}


def procesar(pais, qid):
    iso = pais
    js = overpass(iso)
    wd = wikidata(qid)
    vistos, items = set(), []
    for e in (js or {}).get("elements", []):
        t = e.get("tags", {})
        nombre = t.get("name")
        if not nombre:
            continue
        lat = e.get("lat") or e.get("center", {}).get("lat")
        lon = e.get("lon") or e.get("center", {}).get("lon")
        cap = entero(t.get("capacity"))
        w = wd.get(norm(nombre), {})
        cap = cap or w.get("cap")
        es_estadio = t.get("leisure") == "stadium" or t.get("building") == "stadium"
        if cap is not None and cap < CAP_MIN:
            continue
        if cap is None and not es_estadio:
            continue
        calle = t.get("addr:street")
        direccion = (calle + " " + t.get("addr:housenumber", "")).strip() if calle else w.get("dir")
        llave = (norm(nombre), round(lat or 0, 3), round(lon or 0, 3))
        if llave in vistos:
            continue
        vistos.add(llave)
        alts = [t.get(k) for k in ("alt_name", "short_name", "old_name", "official_name") if t.get(k)]
        items.append(armar(nombre, alts, direccion,
                           t.get("addr:suburb") or t.get("addr:city") or w.get("lugar"),
                           cap, "estadio" if es_estadio else "recinto", lat, lon,
                           "OpenStreetMap" + (" y Wikidata" if w else "")))
    en_osm = {norm(i["n"]) for i in items}
    for k, w in wd.items():
        if k in en_osm or not w.get("cap") or w["cap"] < CAP_MIN:
            continue
        items.append(armar(w["nombre"], [], w.get("dir"), w.get("lugar"), w["cap"],
                           "estadio", w.get("lat"), w.get("lon"), "Wikidata"))
    return items


def main():
    ok = 0
    os.makedirs("datos", exist_ok=True)
    for pais, qid in PAISES.items():
        print("pais", pais, flush=True)
        items = procesar(pais, qid)
        if not items:
            print(pais, "sin datos", flush=True)
            continue
        con_dir = sum(1 for i in items if i["d"])
        obj = {"schema_version": 1, "pais": pais, "fuente_tipo": "medio",
               "generado": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
               "fuentes": "OpenStreetMap contributors (ODbL) y Wikidata (CC0)",
               "capacidad_minima": CAP_MIN, "total": len(items), "con_direccion": con_dir,
               "claves": {"n": "nombre", "k": "nombres normalizados", "d": "direccion", "c": "calle normalizada",
                          "h": "altura", "l": "localidad", "cap": "capacidad (null = sin dato)",
                          "t": "tipo", "la": "latitud", "lo": "longitud", "f": "fuente"},
               "items": items}
        with open(f"datos/estadios_{pais}.json", "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
        print(pais, "recintos:", len(items), "con direccion:", con_dir, flush=True)
        ok += 1
    if ok == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
