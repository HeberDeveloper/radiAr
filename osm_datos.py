#!/usr/bin/env python3
"""radiAr: calles de tierra y vias rapidas desde OpenStreetMap (ODbL). AR, PY y BR."""
import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

SERVIDORES = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
PAUSA = 8
UMBRAL_TIERRA = 0.30
MIN_CON_DATO = 10
MAX_NOMBRES = 40

PAISES = {
    "AR": {
        "bbox": "-35.3,-59.3,-34.2,-57.6",
        "niveles": "6",
        "zonas": ["Quilmes", "Berazategui", "Florencio Varela", "Avellaneda",
                  "Lanús", "Almirante Brown", "Lomas de Zamora",
                  "Esteban Echeverría", "Pilar"],
    },
    "PY": {
        "bbox": "-25.6,-57.8,-25.1,-57.3",
        "niveles": "4|8",
        "zonas": ["Asunción", "Lambaré", "Fernando de la Mora", "San Lorenzo",
                  "Luque", "Capiatá", "Ñemby", "Villa Elisa",
                  "Mariano Roque Alonso", "Limpio"],
    },
    "BR": {
        "niveles": "8",
        "ligero": True,
        "zonas": {
            "São Paulo": "-24.1,-46.9,-23.3,-46.3",
            "Rio de Janeiro": "-23.1,-43.8,-22.7,-43.0",
            "Belo Horizonte": "-20.1,-44.1,-19.75,-43.85",
            "Porto Alegre": "-30.3,-51.3,-29.9,-51.0",
            "Curitiba": "-25.65,-49.45,-25.3,-49.15",
            "Salvador": "-13.1,-38.6,-12.75,-38.3",
            "Fortaleza": "-3.9,-38.7,-3.65,-38.4",
            "Recife": "-8.2,-35.0,-7.95,-34.85",
        },
    },
}

TIERRA = {"unpaved", "dirt", "ground", "gravel", "earth", "compacted",
          "fine_gravel", "mud", "sand", "grass", "pebblestone"}
EMPEDRADO = {"cobblestone", "sett", "cobblestone:flattened",
             "unhewn_cobblestone", "paving_stones"}
PAVIMENTADO = {"paved", "asphalt", "concrete", "concrete:plates",
               "concrete:lanes", "bricks", "metal", "wood"}
RAPIDAS = {"motorway", "motorway_link", "trunk", "trunk_link"}
CALLES_RE = "residential|unclassified|tertiary|secondary|primary|living_street"
LUGARES_RE = "suburb|neighbourhood|town|village|quarter|hamlet|city"


def bbox_de(cfg, zona):
    zonas = cfg["zonas"]
    if isinstance(zonas, dict):
        return zonas[zona]
    return cfg["bbox"]


def consulta(zona, cfg):
    niveles = cfg["niveles"]
    bbox = bbox_de(cfg, zona)
    rapidas = "|".join(sorted(RAPIDAS))
    cabecera = (
        '[out:json][timeout:300];\n'
        f'rel["boundary"="administrative"]["admin_level"~"^({niveles})$"]'
        f'["name"~"^(Partido de |Municipio de )?{zona}$"]({bbox});\n'
        'map_to_area->.a;\n'
    )
    filtro = f'way(area.a)["highway"~"^({CALLES_RE})$"]["name"]'
    if cfg.get("ligero"):
        calles = filtro + '["surface"];\nout tags center;\n' + filtro + ';\nout count;\n'
    else:
        calles = filtro + ';\nout tags center;\n'
    lugares = f'node(area.a)["place"~"^({LUGARES_RE})$"]["name"];\nout;\n'
    vias = f'way(area.a)["highway"~"^({rapidas})$"];\nout tags;'
    return cabecera + calles + lugares + vias


def llamar(q):
    datos = urllib.parse.urlencode({"data": q}).encode("utf-8")
    for intento in range(3):
        for url in SERVIDORES:
            try:
                req = urllib.request.Request(
                    url, data=datos,
                    headers={"User-Agent": "radiAr-datos/1.0 (github actions)"})
                with urllib.request.urlopen(req, timeout=330) as r:
                    return json.loads(r.read().decode("utf-8"))
            except Exception as e:
                print("fallo", url, intento, str(e)[:120])
                time.sleep(20)
    return None


def dist2(lat1, lon1, lat2, lon2):
    dx = (lon1 - lon2) * math.cos(math.radians(lat1))
    dy = lat1 - lat2
    return dx * dx + dy * dy


def procesar(zona, js, ligero):
    calles, lugares, rapidas = [], [], set()
    total = None
    for e in js.get("elements", []):
        t = e.get("tags", {})
        if e.get("type") == "count":
            try:
                total = int(t.get("ways", 0))
            except ValueError:
                total = None
        elif e.get("type") == "node" and "place" in t and "name" in t:
            lugares.append((t["name"], e["lat"], e["lon"]))
        elif e.get("type") == "way" and t.get("highway") in RAPIDAS:
            for n in (t.get("name"), t.get("ref")):
                if n:
                    rapidas.add(n)
        elif e.get("type") == "way" and "center" in e and "name" in t:
            calles.append((t["name"], t.get("surface"),
                           e["center"]["lat"], e["center"]["lon"]))
    agg = {}
    for nombre, sup, lat, lon in calles:
        loc = zona
        if lugares:
            loc = min(lugares, key=lambda p: dist2(lat, lon, p[1], p[2]))[0]
        a = agg.setdefault(loc, {"tramos": 0, "con_dato": 0, "tierra": 0,
                                 "empedrado": 0, "nombres": set()})
        a["tramos"] += 1
        if sup in TIERRA:
            a["con_dato"] += 1
            a["tierra"] += 1
            a["nombres"].add(nombre)
        elif sup in EMPEDRADO:
            a["con_dato"] += 1
            a["empedrado"] += 1
        elif sup in PAVIMENTADO:
            a["con_dato"] += 1
    localidades = {}
    for loc in sorted(agg):
        a = agg[loc]
        k = a["con_dato"]
        pt = round(a["tierra"] / k, 2) if k >= MIN_CON_DATO else None
        pe = round(a["empedrado"] / k, 2) if k >= MIN_CON_DATO else None
        localidades[loc] = {
            "tramos": a["tramos"],
            "con_dato": k,
            "cobertura": None if ligero else round(k / a["tramos"], 2),
            "pct_tierra": pt,
            "pct_empedrado": pe,
            "marcar_tierra": bool(pt is not None and pt >= UMBRAL_TIERRA),
            "calles_tierra": sorted(a["nombres"])[:MAX_NOMBRES],
        }
    cobertura_ciudad = None
    if ligero and total:
        cobertura_ciudad = round(len(calles) / total, 2)
    return localidades, sorted(rapidas), cobertura_ciudad


def main():
    ahora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    os.makedirs("datos", exist_ok=True)
    total_ok = 0
    for pais, cfg in PAISES.items():
        ligero = bool(cfg.get("ligero"))
        tierra = {"schema_version": 1, "pais": pais, "generado": ahora,
                  "fuente": "OpenStreetMap contributors (ODbL)",
                  "fuente_tipo": "medio", "estimado": True,
                  "umbral_tierra": UMBRAL_TIERRA,
                  "min_con_dato": MIN_CON_DATO,
                  "modo": "solo tramos con superficie cargada" if ligero else "completo",
                  "zonas": {}}
        vias = {"schema_version": 1, "pais": pais, "generado": ahora,
                "fuente": "OpenStreetMap contributors (ODbL)",
                "fuente_tipo": "medio", "zonas": {}, "todas": []}
        todas = set()
        for zona in cfg["zonas"]:
            print("zona", pais, zona, flush=True)
            js = llamar(consulta(zona, cfg))
            time.sleep(PAUSA)
            if not js or not js.get("elements"):
                tierra["zonas"][zona] = {"estado": "sin dato"}
                vias["zonas"][zona] = None
                continue
            loc, rap, cc = procesar(zona, js, ligero)
            tierra["zonas"][zona] = {"estado": "ok", "cobertura_ciudad": cc,
                                     "localidades": loc}
            vias["zonas"][zona] = rap
            todas.update(rap)
            total_ok += 1
        vias["todas"] = sorted(todas)
        for nombre, obj in (("zonas_tierra_", tierra), ("vias_rapidas_", vias)):
            with open(f"datos/{nombre}{pais}.json", "w", encoding="utf-8") as f:
                json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    print("zonas con datos:", total_ok)
    if total_ok == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
