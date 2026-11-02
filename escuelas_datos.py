#!/usr/bin/env python3
"""radiAr: escuelas con direccion, un archivo por municipio o ciudad.
AR: toda la Provincia de Buenos Aires (datos abiertos oficiales, CKAN). PY y BR: OpenStreetMap (ODbL)."""
import csv
import io
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
CKAN = "https://catalogo.datos.gba.gob.ar/api/3/action/package_show?id=establecimientos-educativos"
OVERPASS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
PAUSA = 8
SOLO_PARTIDOS = None
OSM = {
    "PY": {
        "niveles": "4|8",
        "zonas": {z: "-25.6,-57.8,-25.1,-57.3" for z in [
            "Asunción", "Lambaré", "Fernando de la Mora", "San Lorenzo", "Luque",
            "Capiatá", "Ñemby", "Villa Elisa", "Mariano Roque Alonso", "Limpio"]},
    },
    "BR": {
        "niveles": "8",
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
PREFIJOS = {"av", "avenida", "calle", "pasaje", "pje", "diagonal", "diag", "bv",
            "boulevard", "rua", "alameda", "praca"}


def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


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


def columna(headers, patrones, evitar=None):
    for h in headers:
        n = norm(h)
        if evitar and re.search(evitar, n):
            continue
        for p in patrones:
            if re.search(p, n):
                return h
    return None


def numero(v):
    try:
        return float(str(v).replace(",", "."))
    except ValueError:
        return None


def escuela(nombre, direccion, localidad, muni, nivel, lat, lon):
    calle, num = calle_num(direccion)
    return {"n": nombre, "d": direccion or None, "c": calle, "h": num,
            "l": localidad or None, "m": muni or None, "v": nivel or None,
            "la": lat, "lo": lon}


def argentina():
    meta = json.loads(http(CKAN, timeout=60).decode("utf-8"))
    recursos = [r for r in meta["result"]["resources"]
                if str(r.get("format", "")).lower() == "csv"]
    if not recursos:
        raise RuntimeError("sin recurso csv")
    texto = http(recursos[0]["url"]).decode("utf-8-sig", errors="replace")
    primera = texto.split("\n", 1)[0]
    sep = ";" if primera.count(";") > primera.count(",") else ","
    filas = list(csv.DictReader(io.StringIO(texto), delimiter=sep))
    if not filas:
        raise RuntimeError("csv vacio")
    h = list(filas[0].keys())
    print("columnas:", h, flush=True)
    cols = {
        "muni": columna(h, [r"munipio nombre", r"municipio nombre", r"^municipio$", r"partido", r"distrito"]),
        "nombre": columna(h, [r"^nombre", r"nombre escuela", r"^escuela", r"establecimiento"], r"munic|munip"),
        "nro": columna(h, [r"nro escuela", r"numero escuela"]),
        "dir": columna(h, [r"domicilio", r"direccion", r"^calle"]),
        "loc": columna(h, [r"localidad"]),
        "nivel": columna(h, [r"^nivel"]),
        "lat": columna(h, [r"^lat"]),
        "lon": columna(h, [r"^lon"]),
    }
    print("detectadas:", cols, flush=True)
    quiero = {norm(p) for p in SOLO_PARTIDOS} if SOLO_PARTIDOS else None
    salida = []
    for f in filas:
        muni = f.get(cols["muni"]) if cols["muni"] else None
        if quiero and norm(muni) not in quiero:
            continue
        nombre = f.get(cols["nombre"]) if cols["nombre"] else None
        if not nombre and cols["nro"]:
            nombre = "Escuela " + str(f.get(cols["nro"]))
        salida.append(escuela(
            nombre, f.get(cols["dir"]) if cols["dir"] else None,
            f.get(cols["loc"]) if cols["loc"] else None, muni,
            f.get(cols["nivel"]) if cols["nivel"] else None,
            numero(f.get(cols["lat"])) if cols["lat"] else None,
            numero(f.get(cols["lon"])) if cols["lon"] else None))
    return salida, cols


def overpass(zona, niveles, bbox):
    q = ('[out:json][timeout:300];\n'
         f'rel["boundary"="administrative"]["admin_level"~"^({niveles})$"]'
         f'["name"~"^{zona}$"]({bbox});\nmap_to_area->.a;\n'
         'nwr(area.a)["amenity"="school"];\nout tags center;')
    datos = urllib.parse.urlencode({"data": q}).encode("utf-8")
    for intento in range(3):
        for url in OVERPASS:
            try:
                return json.loads(http(url, datos, 330).decode("utf-8"))
            except Exception as e:
                print("fallo", url, intento, str(e)[:120], flush=True)
                time.sleep(20)
    return None


def osm(pais, cfg):
    salida = []
    for zona, bbox in cfg["zonas"].items():
        print("zona", pais, zona, flush=True)
        js = overpass(zona, cfg["niveles"], bbox)
        time.sleep(PAUSA)
        if not js:
            continue
        for e in js.get("elements", []):
            t = e.get("tags", {})
            lat = e.get("lat") or e.get("center", {}).get("lat")
            lon = e.get("lon") or e.get("center", {}).get("lon")
            calle = t.get("addr:street")
            dir_ = (calle + " " + t.get("addr:housenumber", "")).strip() if calle else None
            salida.append(escuela(t.get("name"), dir_, t.get("addr:suburb") or t.get("addr:city"),
                                  zona, t.get("isced:level") or t.get("school:level"), lat, lon))
    return salida


def guardar(pais, escuelas, fuente, tipo):
    ahora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    carpeta = f"datos/escuelas/{pais}"
    os.makedirs(carpeta, exist_ok=True)
    grupos = {}
    for e in escuelas:
        grupos.setdefault(e["m"] or "sin zona", []).append(e)
    indice = []
    for zona in sorted(grupos):
        lista = grupos[zona]
        archivo = (norm(zona).replace(" ", "_") or "sin_zona") + ".json"
        con_dir = sum(1 for e in lista if e["d"])
        obj = {"schema_version": 1, "pais": pais, "zona": zona, "generado": ahora,
               "fuente": fuente, "fuente_tipo": tipo, "total": len(lista),
               "con_direccion": con_dir,
               "claves": {"n": "nombre", "d": "direccion", "c": "calle normalizada", "h": "altura",
                          "l": "localidad", "m": "municipio o zona", "v": "nivel",
                          "la": "latitud", "lo": "longitud"},
               "escuelas": lista}
        with open(f"{carpeta}/{archivo}", "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
        indice.append({"zona": zona, "archivo": archivo, "total": len(lista), "con_direccion": con_dir})
    with open(f"{carpeta}/_indice.json", "w", encoding="utf-8") as f:
        json.dump({"schema_version": 1, "pais": pais, "generado": ahora,
                   "fuente": fuente, "zonas": indice}, f, ensure_ascii=False, separators=(",", ":"))
    print(pais, "zonas:", len(indice), "escuelas:", len(escuelas), flush=True)


def main():
    ok = 0
    try:
        esc, cols = argentina()
        guardar("AR", esc, "Datos Abiertos de la Provincia de Buenos Aires, Establecimientos educativos (CC BY 4.0)",
                "oficial")
        ok += 1
    except Exception as e:
        print("AR fallo:", str(e)[:200], flush=True)
    for pais, cfg in OSM.items():
        esc = osm(pais, cfg)
        if esc:
            guardar(pais, esc, "OpenStreetMap contributors (ODbL)", "medio")
            ok += 1
    if ok == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
