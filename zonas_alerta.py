#!/usr/bin/env python3
"""radiAr: ZONA ALERTA de todas las ciudades de fuentes/zonas_alerta_*.json.
Poligonos de cada barrio: de OpenStreetMap (ODbL) o, si el barrio tiene "renabap": "<partido>", del Registro
Nacional de Barrios Populares (RENABAP, Desarrollo Social), que trae el poligono de cada villa o asentamiento.
Con el poligono saca 1) las calles que quedan casi enteras adentro, 2) el centro y 3) el contorno simplificado
("poly": anillos con latitud y longitud alternadas), que la app usa para ubicar Plus Codes y coordenadas.
"directo": true = entra tambien por su nombre. "noche": true = solo de noche. "todas" = la oferta debe nombrar todas las palabras de un grupo.
Salida: datos/zonas/zona_alerta_AR.json, _PY.json y _BR.json. Necesita: pip install shapely"""
import csv
import glob
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
OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]
CKAN_RENABAP = "https://datosabiertos.desarrollosocial.gob.ar/api/3/action/package_show?id=registro-nacional-de-barrios-populares"
PREFIJOS_CALLE = {"av", "avenida", "calle", "pasaje", "pje", "diagonal", "diag", "bv", "bvar", "boulevard", "bulevar",
                  "rua", "alameda", "praca", "estrada", "travessa"}
PREFIJOS_BARRIO = {"barrio", "villa", "bairro", "la", "las", "el", "los", "o", "a", "complexo", "comunidade"}
_RENABAP = None


def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def calle(s):
    p = norm(s).split()
    while len(p) > 1 and p[0] in PREFIJOS_CALLE:
        p.pop(0)
    return " ".join(p)


def barrio(s):
    p = norm(s).split()
    while len(p) > 1 and p[0] in PREFIJOS_BARRIO:
        p.pop(0)
    return " ".join(p)


def http(url, datos=None, timeout=400):
    req = urllib.request.Request(url, data=datos, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def overpass(q):
    datos = urllib.parse.urlencode({"data": q}).encode("utf-8")
    for intento in range(3):
        for url in OVERPASS:
            try:
                return json.loads(http(url, datos).decode("utf-8"))
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


def columna(headers, patrones):
    for h in headers:
        n = norm(h)
        if any(re.search(p, n) for p in patrones):
            return h
    return None


def renabap():
    """Lista de {nombre, partido, localidad, geom} de todos los barrios populares del pais."""
    global _RENABAP
    if _RENABAP is not None:
        return _RENABAP
    from shapely import wkt
    from shapely.geometry import shape
    _RENABAP = []
    try:
        meta = json.loads(http(CKAN_RENABAP, timeout=60).decode("utf-8"))
        orden = ["geojson", "json", "csv"]
        recs = [r for r in meta["result"]["resources"] if str(r.get("format", "")).lower() in orden]
        recs.sort(key=lambda r: orden.index(str(r["format"]).lower()))
        for r in recs:
            fmt, filas = str(r["format"]).lower(), []
            try:
                datos = http(r["url"], timeout=900)
                if fmt in ("geojson", "json"):
                    for f in json.loads(datos.decode("utf-8-sig")).get("features", []):
                        fila = dict(f.get("properties", {}))
                        fila["_geom"] = shape(f["geometry"]) if f.get("geometry") else None
                        filas.append(fila)
                else:
                    csv.field_size_limit(10 ** 8)
                    texto = datos.decode("utf-8-sig", errors="replace")
                    primera = texto.split("\n", 1)[0]
                    sep = ";" if primera.count(";") > primera.count(",") else ","
                    for fila in csv.DictReader(io.StringIO(texto), delimiter=sep):
                        g = next((fila[k] for k in fila if norm(k) in ("geometry", "geom", "the geom", "wkt")), None)
                        try:
                            fila["_geom"] = wkt.loads(g) if g else None
                        except Exception:
                            fila["_geom"] = None
                        filas.append(fila)
                if not filas:
                    continue
                h = [k for k in filas[0] if k != "_geom"]
                cn = columna(h, [r"nombre.*barrio", r"^nombre", r"barrio"])
                cp = columna(h, [r"^partido", r"departamento"])
                cl = columna(h, [r"localidad"])
                print("renabap columnas:", h, "| nombre:", cn, "| partido:", cp, flush=True)
                for fila in filas:
                    if fila.get("_geom") is not None and cn:
                        _RENABAP.append({"nombre": fila.get(cn), "partido": fila.get(cp) if cp else "",
                                         "localidad": fila.get(cl) if cl else "", "geom": fila["_geom"]})
                break
            except Exception as e:
                print("renabap recurso fallo", str(e)[:150], flush=True)
    except Exception as e:
        print("renabap fallo", str(e)[:150], flush=True)
    print("renabap barrios con poligono:", len(_RENABAP), flush=True)
    return _RENABAP


def poligonos_renabap(b):
    partido = norm(b["renabap"]) if isinstance(b.get("renabap"), str) else ""
    buscados = {barrio(n) for n in [b["nombre"]] + b.get("alias", [])}
    sal = []
    for r in renabap():
        if partido and partido not in norm(r["partido"]) + " " + norm(r["localidad"]):
            continue
        if barrio(r["nombre"]) in buscados:
            sal.append(r["geom"])
    return sal


def contorno(geoms):
    """Anillos simplificados (unos 9 metros) con latitud y longitud alternadas, para la app."""
    from shapely.ops import unary_union
    g = unary_union(geoms).simplify(0.00008, preserve_topology=True)
    partes = list(g.geoms) if hasattr(g, "geoms") else [g]
    anillos = []
    for p in partes:
        if p.geom_type == "Polygon" and len(p.exterior.coords) >= 4:
            anillos.append([round(v, 5) for xy in p.exterior.coords for v in (xy[1], xy[0])])
    anillos.sort(key=len, reverse=True)
    return anillos[:15], g.centroid


def ciudad(c):
    from shapely.geometry import Point
    bbox = c["bbox"]
    pedidos = {}
    for b in c["barrios"]:
        for nombre in [b["nombre"]] + b.get("alias", []):
            pedidos[barrio(nombre)] = b["nombre"]
    polys = {}
    for b in c["barrios"]:
        if b.get("renabap"):
            lista = poligonos_renabap(b)
            if lista:
                polys[b["nombre"]] = lista
    js = overpass("[out:json][timeout:300];\n(\n"
                  f'  rel["boundary"~"administrative|suburb"]["name"]({bbox});\n'
                  f'  way["place"~"suburb|neighbourhood|quarter"]["name"]({bbox});\n'
                  f'  rel["place"~"suburb|neighbourhood|quarter"]["name"]({bbox});\n'
                  ");\nout geom;")
    if js:
        for e in js.get("elements", []):
            k = barrio(e.get("tags", {}).get("name", ""))
            if k in pedidos and pedidos[k] not in polys:
                polys.setdefault(pedidos[k], []).extend(poligonos(e))
    halladas = {b: len(v) for b, v in polys.items() if v}
    faltan = [b["nombre"] for b in c["barrios"] if b["nombre"] not in halladas]
    print(c["id"], "con poligono:", sorted(halladas), "| sin poligono:", faltan, flush=True)
    por_barrio = {}
    if halladas:
        cs = overpass(f'[out:json][timeout:300];\nway["highway"]["name"]({bbox});\nout center tags;')
        total, dentro = {}, {}
        for e in (cs or {}).get("elements", []):
            nombre, cen = calle(e.get("tags", {}).get("name", "")), e.get("center")
            if not nombre or not cen:
                continue
            total[nombre] = total.get(nombre, 0) + 1
            pt = Point(cen["lon"], cen["lat"])
            for b, lista in polys.items():
                if any(p.contains(pt) for p in lista):
                    dentro.setdefault(nombre, {})[b] = dentro.setdefault(nombre, {}).get(b, 0) + 1
                    break
        for nombre, por in dentro.items():
            if sum(por.values()) / total[nombre] >= 0.8:
                por_barrio.setdefault(max(por, key=por.get), set()).add(nombre)
    items = []
    gate = norm(c["ciudad"])
    for b in c["barrios"]:
        claves = set(por_barrio.get(b["nombre"], set()))
        if b.get("directo"):
            claves.add(norm(b["nombre"]))
            claves.update(norm(a) for a in b.get("alias", []))
        todas = [[norm(x) for x in g] for g in b.get("todas", [])]
        anillos, centro = [], None
        if b["nombre"] in polys:
            try:
                anillos, centro = contorno(polys[b["nombre"]])
            except Exception as e:
                print("contorno fallo", b["nombre"], str(e)[:100], flush=True)
        if not claves and not todas and not anillos:
            continue
        item = {"zona": f"{c['id']}: {b['nombre']}", "ciudad": gate, "claves": sorted(claves),
                "fuente": b["fuente"], "fuente_tipo": b["tipo"], "estimado": True}
        if todas:
            item["todas"] = todas
        # Solo de noche (reporte de choferes): la app la muestra de 20 a 7 (horario estimado).
        if b.get("noche"):
            item["noche"] = True
        if anillos:
            item["poly"] = anillos
            item["centro"] = [round(centro.y, 6), round(centro.x, 6)]
        items.append(item)
    return items, faltan


def main():
    cfgs, nota = [], ""
    for ruta in sorted(glob.glob("fuentes/zonas_alerta_*.json")):
        with open(ruta, encoding="utf-8") as f:
            cfg = json.load(f)
        nota = nota or cfg.get("nota", "")
        cfgs.extend(cfg["ciudades"])
    por_pais, sin = {}, {}
    for c in cfgs:
        try:
            items, faltan = ciudad(c)
            por_pais.setdefault(c["pais"], []).extend(items)
            sin[c["id"]] = faltan
            time.sleep(10)
        except Exception as e:
            print(c["id"], "fallo:", str(e)[:200], flush=True)
    if not por_pais:
        sys.exit(1)
    os.makedirs("datos/zonas", exist_ok=True)
    for pais, items in por_pais.items():
        obj = {"schema_version": 1, "pais": pais, "etiqueta": "ZONA ALERTA", "nota": nota,
               "generado": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
               "barrios_sin_poligono": sin, "items": items}
        with open(f"datos/zonas/zona_alerta_{pais}.json", "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
        print(pais, "items:", len(items), "claves:", sum(len(i["claves"]) for i in items),
              "con contorno:", sum(1 for i in items if i.get("poly")), flush=True)


if __name__ == "__main__":
    main()
