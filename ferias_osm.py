#!/usr/bin/env python3
"""radiAr: ferias y mercados que se repiten cada semana, desde OpenStreetMap (ODbL).
Toma los lugares marcados como feria o mercado (amenity=marketplace) que tienen dias y horarios cargados
(opening_hours) y, para cada uno, las calles con nombre que pasan a menos de 80 metros. Con eso la app avisa
FERIA si la oferta nombra esas calles (por ejemplo "Chile" y "Centenario") el dia y en el horario de la feria.
Argentina y Paraguay: todo el pais. Brasil: las ciudades grandes.
Salida: datos/ferias/ferias_AR.json, _PY.json y _BR.json."""
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
OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]
RADIO = 80
PAISES = {
    "AR": {"area": 'area["ISO3166-1"="AR"][admin_level=2]->.a;', "bboxes": [None]},
    "PY": {"area": 'area["ISO3166-1"="PY"][admin_level=2]->.a;', "bboxes": [None]},
    "BR": {"area": None, "bboxes": [
        "-24.1,-46.9,-23.3,-46.3", "-23.1,-43.8,-22.7,-43.0", "-20.1,-44.1,-19.75,-43.85",
        "-30.3,-51.3,-29.9,-51.0", "-25.65,-49.45,-25.3,-49.15", "-13.1,-38.6,-12.75,-38.3",
        "-3.9,-38.7,-3.65,-38.4", "-8.2,-35.0,-7.95,-34.85", "-15.95,-48.2,-15.6,-47.75"]},
}
DIAS_OSM = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
DIAS = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
PREFIJOS = {"av", "avenida", "calle", "pasaje", "pje", "diagonal", "diag", "bv", "bvar", "boulevard", "bulevar",
            "rua", "alameda", "praca", "estrada", "travessa", "ruta"}


def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def calle(s):
    p = norm(s).split()
    while len(p) > 1 and p[0] in PREFIJOS:
        p.pop(0)
    return " ".join(p)


def overpass(q):
    datos = urllib.parse.urlencode({"data": q}).encode("utf-8")
    for intento in range(3):
        for url in OVERPASS:
            try:
                req = urllib.request.Request(url, data=datos, headers=UA)
                with urllib.request.urlopen(req, timeout=900) as r:
                    return json.loads(r.read().decode("utf-8"))
            except Exception as e:
                print("overpass fallo", url, intento, str(e)[:120], flush=True)
                time.sleep(30)
    return None


def dias_de(txt):
    """'Mo-Fr' -> [0..4], 'Sa,Su' -> [5, 6], 'Fr' -> [4]. None si no se entiende."""
    sal = []
    for parte in txt.split(","):
        parte = parte.strip()
        m = re.fullmatch(r"(Mo|Tu|We|Th|Fr|Sa|Su)(?:-(Mo|Tu|We|Th|Fr|Sa|Su))?", parte)
        if not m:
            return None
        a = DIAS_OSM.index(m.group(1))
        b = DIAS_OSM.index(m.group(2)) if m.group(2) else a
        i = a
        while True:
            sal.append(i)
            if i == b:
                break
            i = (i + 1) % 7
    return sal


def horarios(oh):
    """Entiende los formatos simples de opening_hours: 'Fr 08:00-15:00; Su 09:00-13:00'.
    Lo que no se entiende (feriados, meses, 'off', '24/7') se deja afuera: mejor sin dato que inventado."""
    sal = []
    for regla in str(oh or "").split(";"):
        regla = regla.strip()
        if not regla:
            continue
        m = re.fullmatch(r"([A-Za-z,\- ]+?)\s+((?:\d{1,2}:\d{2}-\d{1,2}:\d{2},?\s*)+)", regla)
        if not m:
            continue
        ds = dias_de(m.group(1).replace(" ", ""))
        if not ds:
            continue
        for tramo in re.findall(r"(\d{1,2}:\d{2})-(\d{1,2}:\d{2})", m.group(2)):
            desde, hasta = tramo[0].zfill(5), tramo[1].zfill(5)
            if hasta == "24:00":
                hasta = "23:59"
            if hasta <= desde:
                continue
            sal.append({"dias": [DIAS[d] for d in sorted(set(ds))], "desde": desde, "hasta": hasta})
    return sal


def consulta(cfg, bbox):
    filtro = '["amenity"="marketplace"]["opening_hours"]'
    if cfg["area"]:
        cab = "[out:json][timeout:900];\n" + cfg["area"] + "\n"
        donde = "(area.a)"
    else:
        cab = "[out:json][timeout:900];\n"
        donde = "(" + bbox + ")"
    # Por cada feria: primero ella misma y despues las calles con nombre cercanas.
    return (cab + "nwr" + donde + filtro + "->.f;\n"
            "foreach.f->.x(\n"
            "  .x out tags center;\n"
            f"  way(around.x:{RADIO})[\"highway\"][\"name\"];\n"
            "  out tags;\n"
            ");")


def procesar(js):
    items = []
    actual = None
    for e in (js or {}).get("elements", []):
        t = e.get("tags", {})
        if t.get("amenity") == "marketplace":
            if actual:
                items.append(actual)
            actual = {"t": t, "c": e.get("center") or {"lat": e.get("lat"), "lon": e.get("lon")}, "calles": set()}
        elif actual is not None and t.get("highway") and t.get("name"):
            actual["calles"].add(calle(t["name"]))
    if actual:
        items.append(actual)
    sal = []
    for it in items:
        t = it["t"]
        # Solo ferias de pocos dias por semana: los mercados que abren casi todos los dias no son "feria".
        hs = [h for h in horarios(t.get("opening_hours")) if len(h["dias"]) <= 3]
        if not hs:
            continue
        calles = sorted(c for c in it["calles"] if c)
        nombre = t.get("name") or t.get("official_name") or "Feria"
        claves = []
        if t.get("name"):
            claves.append(norm(t["name"]))
        todas = []
        # Esquinas: cada par de calles cercanas (la oferta tiene que nombrar las dos).
        for i in range(len(calles)):
            for j in range(i + 1, len(calles)):
                todas.append([calles[i], calles[j]])
        if t.get("addr:street") and t.get("addr:housenumber"):
            claves.append(calle(t["addr:street"]) + " " + norm(t["addr:housenumber"]))
        if not claves and not todas:
            continue
        sal.append({
            "nombre": nombre, "horarios": hs, "claves": claves, "todas": todas[:15],
            "la": round(it["c"].get("lat") or 0, 5), "lo": round(it["c"].get("lon") or 0, 5),
            "fuente": "OpenStreetMap contributors (ODbL)", "fuente_tipo": "medio", "estimado": True,
        })
    return sal


def manuales(pais):
    """Ferias cargadas a mano en fuentes/ferias_semanales.json (Argentina)."""
    if pais != "AR":
        return []
    try:
        with open("fuentes/ferias_semanales.json", encoding="utf-8") as f:
            fs = json.load(f).get("ferias", [])
    except Exception:
        return []
    sal = []
    for f in fs:
        sal.append({"nombre": f["nombre"], "horarios": [{"dias": f["dias"], "desde": f["desde"], "hasta": f["hasta"]}],
                    "meses": f.get("meses"), "claves": [norm(c) for c in f.get("claves", [])], "todas": f.get("todas", []),
                    "fuente": f.get("fuente", ""), "fuente_tipo": "medio", "estimado": True})
    return sal


def main():
    ok = 0
    os.makedirs("datos/ferias", exist_ok=True)
    for pais, cfg in PAISES.items():
        todas = manuales(pais)
        for bbox in cfg["bboxes"]:
            print("pais", pais, bbox or "todo", flush=True)
            js = overpass(consulta(cfg, bbox))
            todas.extend(procesar(js))
            time.sleep(15)
        if not todas:
            print(pais, "sin ferias", flush=True)
            continue
        obj = {"schema_version": 1, "pais": pais, "etiqueta": "FERIA",
               "generado": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
               "nota": "Ferias y mercados semanales. La app avisa FERIA si la oferta nombra el lugar o sus calles cercanas, "
                       "el dia y en el horario de la feria. Horarios de OpenStreetMap o de fuentes publicas: estimados.",
               "total": len(todas), "items": todas}
        with open(f"datos/ferias/ferias_{pais}.json", "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
        print(pais, "ferias:", len(todas), flush=True)
        ok += 1
    if ok == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
