#!/usr/bin/env python3
"""radiAr: datos de Rosario y el Gran Rosario (fuentes abiertas).
1) Barrios populares (RENABAP, Desarrollo Social).
2) Escuelas (Padron Oficial de Establecimientos Educativos, datos.gob.ar).
3) Zona alerta: calles dentro de los barrios marcados (OpenStreetMap, ODbL).
Necesita: pip install shapely openpyxl"""
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
CKAN_RENABAP = "https://datosabiertos.desarrollosocial.gob.ar/api/3/action/package_show?id=registro-nacional-de-barrios-populares"
CKAN_PADRON = "https://datos.gob.ar/api/3/action/package_show?id=educacion-padron-oficial-establecimientos-educativos"
OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]
BBOX = "-33.12,-60.90,-32.80,-60.50"
GRAN_ROSARIO = {
    "rosario", "villa gobernador galvez", "granadero baigorria", "perez", "funes", "roldan",
    "san lorenzo", "capitan bermudez", "fray luis beltran", "soldini", "pueblo esther",
    "general lagos", "arroyo seco", "ibarlucea", "zavalla"}
# Barrios con concentracion de violencia. Fuentes: La Capital (mapa de homicidios de 2025) y el ministro de
# Seguridad de Santa Fe (2023). Ver 01-datos/rosario.md. Dato de ubicacion, no un juicio sobre los vecinos.
BARRIOS = {
    "Empalme Graneros": ("La Capital 2025; Ministerio de Seguridad 2023", "medio"),
    "Ludueña": ("La Capital 2025", "medio"),
    "Nuevo Alberdi": ("La Capital 2025", "medio"),
    "Larrea": ("La Capital 2025; Ministerio de Seguridad 2023", "medio"),
    "Vía Honda": ("Ministerio de Seguridad 2023", "medio"),
    "Industrial": ("La Capital 2025; Ministerio de Seguridad 2023", "medio"),
    "Triángulo": ("La Capital 2025; Ministerio de Seguridad 2023", "medio"),
    "Moderno": ("La Capital 2025; Ministerio de Seguridad 2023", "medio"),
    "Godoy": ("La Capital 2025", "medio"),
    "Villa Banana": ("La Capital 2025", "medio"),
    "Tablada": ("La Capital 2025; Ministerio de Seguridad 2023", "medio"),
    "Las Flores": ("La Capital 2025; Ministerio de Seguridad 2023", "medio"),
    "Las Flores Este": ("La Capital 2025", "medio"),
    "República de la Sexta": ("La Capital 2025", "medio"),
    "Hospitales": ("La Capital 2025", "medio"),
    "Saladillo": ("La Capital 2025", "medio"),
    "Plata": ("La Capital 2025", "medio"),
    "La Guardia": ("La Capital 2025", "medio"),
    "Puente Gallego": ("La Capital 2025", "medio"),
    "San Martín Sur": ("La Capital 2025", "medio"),
    "17 de Agosto": ("Ministerio de Seguridad 2023", "medio"),
    "Bella Vista": ("Ministerio de Seguridad 2023", "medio"),
    "Santa Lucía": ("Ministerio de Seguridad 2023", "medio"),
}
PREFIJOS = {"av", "avenida", "calle", "pasaje", "pje", "diagonal", "diag", "bv", "bvar", "boulevard", "bulevar"}


def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def sin_prefijo(s):
    p = norm(s).split()
    while len(p) > 1 and p[0] in PREFIJOS:
        p.pop(0)
    return " ".join(p)


def calle_num(direccion):
    n = norm(direccion)
    if not n:
        return None, None
    m = re.search(r"\b(\d{1,5})\b", n)
    calle, num = (n[:m.start()].strip(), int(m.group(1))) if m else (n, None)
    p = calle.split()
    while len(p) > 1 and p[0] in PREFIJOS:
        p.pop(0)
    return (" ".join(p) or None), num


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


def coords(c):
    if isinstance(c, (list, tuple)) and len(c) >= 2 and all(isinstance(x, (int, float)) for x in c[:2]):
        yield c[0], c[1]
    elif isinstance(c, (list, tuple)):
        for x in c:
            yield from coords(x)


def centro_geojson(g):
    pts = list(coords((g or {}).get("coordinates", [])))
    if not pts:
        return None, None
    return sum(p[1] for p in pts) / len(pts), sum(p[0] for p in pts) / len(pts)


def centro_wkt(s):
    pts = re.findall(r"(-?\d+\.\d+)\s+(-?\d+\.\d+)", str(s or ""))
    if not pts:
        return None, None
    return sum(float(p[1]) for p in pts) / len(pts), sum(float(p[0]) for p in pts) / len(pts)


def leer_recurso(url_ckan):
    meta = json.loads(http(url_ckan, timeout=60).decode("utf-8"))
    recs = meta["result"]["resources"]
    orden = ["csv", "geojson", "json", "xlsx", "xls"]
    recs.sort(key=lambda r: orden.index(str(r.get("format", "")).lower()) if str(r.get("format", "")).lower() in orden else 99)
    for r in recs:
        fmt = str(r.get("format", "")).lower()
        if fmt not in orden:
            continue
        try:
            datos = http(r["url"], timeout=900)
            return fmt, datos
        except Exception as e:
            print("recurso fallo", r.get("url"), str(e)[:100], flush=True)
    raise RuntimeError("sin recurso utilizable")


def a_filas(fmt, datos):
    if fmt in ("geojson", "json"):
        js = json.loads(datos.decode("utf-8-sig"))
        filas = []
        for f in js.get("features", []):
            fila = dict(f.get("properties", {}))
            fila["_lat"], fila["_lon"] = centro_geojson(f.get("geometry"))
            filas.append(fila)
        return filas
    if fmt == "csv":
        texto = datos.decode("utf-8-sig", errors="replace")
        primera = texto.split("\n", 1)[0]
        sep = ";" if primera.count(";") > primera.count(",") else ","
        csv.field_size_limit(10 ** 8)
        filas = list(csv.DictReader(io.StringIO(texto), delimiter=sep))
        for f in filas:
            g = next((f[k] for k in f if norm(k) in ("geometry", "geom", "the geom", "wkt", "geojson")), None)
            if g and g.strip().startswith("{"):
                try:
                    f["_lat"], f["_lon"] = centro_geojson(json.loads(g))
                except Exception:
                    pass
            elif g:
                f["_lat"], f["_lon"] = centro_wkt(g)
        return filas
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(datos), read_only=True, data_only=True)
    filas, cab = [], None
    for fila in wb.worksheets[0].iter_rows(values_only=True):
        vals = [str(v).strip() if v is not None else "" for v in fila]
        if cab is None:
            if sum(1 for v in vals if v) >= 3:
                cab = vals
            continue
        filas.append(dict(zip(cab, vals)))
    return filas


def barrios_populares():
    fmt, datos = leer_recurso(CKAN_RENABAP)
    filas = a_filas(fmt, datos)
    h = list(filas[0].keys())
    print("renabap columnas:", h, flush=True)
    c = {"n": columna(h, [r"nombre.*barrio", r"^nombre", r"barrio"], r"id"), "p": columna(h, [r"provincia"]),
         "d": columna(h, [r"departamento", r"partido"]), "l": columna(h, [r"localidad"]),
         "f": columna(h, [r"familias"]), "y": columna(h, [r"anio", r"ano de"]), "id": columna(h, [r"^renabap", r"^id"]),
         "la": columna(h, [r"^lat"]), "lo": columna(h, [r"^lon"])}
    print("renabap detectadas:", c, flush=True)
    sal = []
    for f in filas:
        if "santa fe" not in norm(f.get(c["p"])):
            continue
        zona = {norm(f.get(c["l"])), norm(f.get(c["d"]))}
        if not (zona & GRAN_ROSARIO):
            continue
        la = f.get("_lat") or (float(str(f.get(c["la"])).replace(",", ".")) if c["la"] and f.get(c["la"]) else None)
        lo = f.get("_lon") or (float(str(f.get(c["lo"])).replace(",", ".")) if c["lo"] and f.get(c["lo"]) else None)
        sal.append({"id": f.get(c["id"]) if c["id"] else None, "n": f.get(c["n"]) if c["n"] else None,
                    "l": f.get(c["l"]) if c["l"] else None, "f": f.get(c["f"]) if c["f"] else None,
                    "y": f.get(c["y"]) if c["y"] else None, "la": la, "lo": lo})
    return sal


def escuelas():
    fmt, datos = leer_recurso(CKAN_PADRON)
    filas = a_filas(fmt, datos)
    h = list(filas[0].keys())
    print("padron columnas:", h, flush=True)
    c = {"p": columna(h, [r"provincia", r"jurisdiccion"]), "d": columna(h, [r"departamento"]),
         "l": columna(h, [r"localidad"]), "n": columna(h, [r"^nombre", r"establecimiento"], r"codigo|cue|numero"),
         "dir": columna(h, [r"domicilio", r"direccion", r"^calle"]), "v": columna(h, [r"nivel", r"oferta", r"modalidad"]),
         "la": columna(h, [r"^lat"]), "lo": columna(h, [r"^lon"])}
    print("padron detectadas:", c, flush=True)
    vistos, sal = set(), []
    for f in filas:
        if c["p"] and "santa fe" not in norm(f.get(c["p"])):
            continue
        loc = norm(f.get(c["l"]))
        if loc not in GRAN_ROSARIO:
            continue
        nombre = f.get(c["n"]) if c["n"] else None
        dire = f.get(c["dir"]) if c["dir"] else None
        k = (norm(nombre), norm(dire))
        if k in vistos:
            continue
        vistos.add(k)
        calle, num = calle_num(dire)
        sal.append({"n": nombre, "d": dire or None, "c": calle, "h": num, "l": f.get(c["l"]),
                    "m": f.get(c["l"]), "v": f.get(c["v"]) if c["v"] else None,
                    "la": f.get("_lat"), "lo": f.get("_lon")})
    return sal


def guardar_escuelas(lista):
    carpeta = "datos/escuelas/AR"
    os.makedirs(carpeta, exist_ok=True)
    ahora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    grupos = {}
    for e in lista:
        grupos.setdefault(e["m"] or "sin zona", []).append(e)
    nuevos = []
    for zona in sorted(grupos):
        arch = (norm(zona).replace(" ", "_") or "sin_zona") + ".json"
        con_dir = sum(1 for e in grupos[zona] if e["d"])
        obj = {"schema_version": 1, "pais": "AR", "zona": zona, "generado": ahora,
               "fuente": "Padron Oficial de Establecimientos Educativos (datos.gob.ar)", "fuente_tipo": "oficial",
               "total": len(grupos[zona]), "con_direccion": con_dir, "escuelas": grupos[zona]}
        with open(f"{carpeta}/{arch}", "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
        nuevos.append({"zona": zona, "archivo": arch, "total": len(grupos[zona]), "con_direccion": con_dir})
    ruta = f"{carpeta}/_indice.json"
    try:
        with open(ruta, encoding="utf-8") as f:
            ind = json.load(f)
    except Exception:
        ind = {"schema_version": 1, "pais": "AR", "zonas": []}
    pisados = {n["zona"] for n in nuevos}
    ind["zonas"] = [z for z in ind.get("zonas", []) if z.get("zona") not in pisados] + nuevos
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(ind, f, ensure_ascii=False, separators=(",", ":"))


def overpass(q):
    datos = urllib.parse.urlencode({"data": q}).encode("utf-8")
    for intento in range(3):
        for url in OVERPASS:
            try:
                return json.loads(http(url, datos, 400).decode("utf-8"))
            except Exception as e:
                print("overpass fallo", url, intento, str(e)[:100], flush=True)
                time.sleep(20)
    return None


def poligonos(e):
    from shapely.geometry import LineString, Polygon
    from shapely.ops import polygonize, unary_union
    try:
        if e["type"] == "way" and e.get("geometry"):
            pts = [(p["lon"], p["lat"]) for p in e["geometry"]]
            return [Polygon(pts)] if len(pts) >= 4 and pts[0] == pts[-1] else []
        if e["type"] == "relation":
            lineas = [LineString([(p["lon"], p["lat"]) for p in m["geometry"]])
                      for m in e.get("members", []) if m.get("role") in ("outer", "") and m.get("geometry")]
            return list(polygonize(unary_union(lineas))) if lineas else []
    except Exception:
        pass
    return []


def zona_alerta():
    from shapely.geometry import Point
    pedidos = {sin_prefijo(b).replace("la ", "", 1) if sin_prefijo(b).startswith("la ") else sin_prefijo(b): b
               for b in BARRIOS}
    q = ("[out:json][timeout:300];\n(\n"
         f'  rel["boundary"~"administrative|suburb"]["name"]({BBOX});\n'
         f'  way["place"~"suburb|neighbourhood|quarter"]["name"]({BBOX});\n'
         f'  rel["place"~"suburb|neighbourhood|quarter"]["name"]({BBOX});\n'
         ');\nout geom;')
    js = overpass(q)
    if not js:
        raise RuntimeError("sin barrios")
    polys = {}
    for e in js.get("elements", []):
        k = sin_prefijo(e.get("tags", {}).get("name", ""))
        k = k[3:] if k.startswith("la ") else k
        if k in pedidos:
            polys.setdefault(pedidos[k], []).extend(poligonos(e))
    encontrados = {b: len(v) for b, v in polys.items() if v}
    print("barrios encontrados:", encontrados, flush=True)
    print("barrios sin poligono:", [b for b in BARRIOS if b not in encontrados], flush=True)
    calles = overpass(f'[out:json][timeout:300];\nway["highway"]["name"]({BBOX});\nout center tags;')
    if not calles:
        raise RuntimeError("sin calles")
    total, dentro = {}, {}
    for e in calles.get("elements", []):
        nombre = sin_prefijo(e.get("tags", {}).get("name", ""))
        cen = e.get("center")
        if not nombre or not cen:
            continue
        total[nombre] = total.get(nombre, 0) + 1
        pt = Point(cen["lon"], cen["lat"])
        for b, lista in polys.items():
            if any(p.contains(pt) for p in lista):
                dentro.setdefault(nombre, {})
                dentro[nombre][b] = dentro[nombre].get(b, 0) + 1
                break
    items = {}
    parciales = []
    for nombre, por in dentro.items():
        n_in = sum(por.values())
        frac = n_in / total[nombre]
        barrio = max(por, key=por.get)
        if frac >= 0.8:
            items.setdefault(barrio, []).append(nombre)
        elif frac >= 0.2:
            parciales.append({"calle": nombre, "barrio": barrio, "fraccion": round(frac, 2)})
    lista = [{"zona": "Rosario: " + b, "ciudad": "rosario", "claves": sorted(v), "fuente": BARRIOS[b][0],
              "fuente_tipo": BARRIOS[b][1], "estimado": True} for b, v in sorted(items.items())]
    obj = {"schema_version": 1, "pais": "AR", "etiqueta": "ZONA ALERTA",
           "nota": "Calles que quedan casi enteras dentro de un barrio marcado. La etiqueta sale solo si la oferta nombra Rosario. Es un dato de ubicacion basado en estadisticas de homicidios, no un juicio sobre las personas.",
           "generado": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
           "barrios_sin_poligono": [b for b in BARRIOS if b not in encontrados],
           "calles_parciales_para_revisar": parciales[:400], "items": lista}
    os.makedirs("datos/rosario", exist_ok=True)
    with open("datos/rosario/zona_alerta_AR.json", "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    print("zona alerta: barrios", len(lista), "calles", sum(len(i["claves"]) for i in lista), flush=True)


def main():
    ok = 0
    os.makedirs("datos/rosario", exist_ok=True)
    for nombre, fn in (("barrios_populares", barrios_populares), ("escuelas", escuelas)):
        try:
            res = fn()
            if nombre == "escuelas":
                guardar_escuelas(res)
            else:
                with open("datos/rosario/barrios_populares.json", "w", encoding="utf-8") as f:
                    json.dump({"schema_version": 1, "fuente": "RENABAP, Ministerio de Desarrollo Social de la Nacion",
                               "total": len(res), "barrios": res}, f, ensure_ascii=False, separators=(",", ":"))
            print(nombre, "total:", len(res), flush=True)
            ok += 1
        except Exception as e:
            print(nombre, "fallo:", str(e)[:200], flush=True)
    try:
        zona_alerta()
        ok += 1
    except Exception as e:
        print("zona_alerta fallo:", str(e)[:200], flush=True)
    if ok == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
