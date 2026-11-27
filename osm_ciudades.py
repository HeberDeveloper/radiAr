#!/usr/bin/env python3
"""radiAr: mapa detallado por ciudad desde OpenStreetMap (ODbL), hecho en GitHub y no en el celu.

27 nov 2026: antes cada celu bajaba esto de Overpass (consultas pesadas) y el celu se trababa al
empezar la ronda. Ahora lo arma GitHub una vez por mes y el celu solo baja archivos chicos ya listos.

Salida (mismo formato que guardaba el celu en OsmDatos.bajarCiudad):
  datos/osm/<PAIS>/<slug>.json      ciudad, t, fuente, tierra, vias, inundables, lugares, villas, villa_calles
  datos/osm/<PAIS>/esc_<slug>.json  {"escuelas": [{"c": calle, "h": altura}]}
  datos/osm/<PAIS>/_indice.json     lista de ciudades publicadas
Solo listas publicas por nombre de partido o recuadro: no usa ningun dato de choferes.
"""
import json
import os
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request

SERVIDORES = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
UA = "radiAr-datos/1.0 github.com/radiarapp/radiAr"
PAUSA = 10

SUPERFICIES = ("^(unpaved|dirt|ground|earth|gravel|fine_gravel|compacted|sand|mud|grass|pebblestone|rock|"
               "grass_paver|woodchips)$")
SUP_SET = set(SUPERFICIES.strip("^$()").split("|"))

BA = "^(Provincia de )?Buenos Aires$"
# Ciudad de la app (Zona.kt) -> partido en OpenStreetMap (provincia, nombre). Sin entrada: recuadro.
AREAS = {
    "Buenos Aires": (None, "Ciudad Aut[oó]noma de Buenos Aires"),
    "Quilmes": (BA, "Quilmes$"), "Berazategui": (BA, "Berazategui$"),
    "Florencio Varela": (BA, "Florencio Varela$"), "Avellaneda": (BA, "Avellaneda$"),
    "Lanus": (BA, "Lan[uú]s$"), "Lomas de Zamora": (BA, "Lomas de Zamora$"),
    "Almirante Brown": (BA, "Almirante Brown$"), "Esteban Echeverria": (BA, "Esteban Echeverr[ií]a$"),
    "Ezeiza": (BA, "Ezeiza$"), "La Matanza": (BA, "La Matanza$"), "Moron": (BA, "Mor[oó]n$"),
    "Merlo": (BA, "Merlo$"), "Moreno": (BA, "Moreno$"), "Hurlingham": (BA, "Hurlingham$"),
    "Ituzaingo": (BA, "Ituzaing[oó]$"), "Tres de Febrero": (BA, "Tres de Febrero$"),
    "San Martin": (BA, "General San Mart[ií]n$"), "Vicente Lopez": (BA, "Vicente L[oó]pez$"),
    "San Isidro": (BA, "San Isidro$"), "San Fernando": (BA, "San Fernando$"), "Tigre": (BA, "Tigre$"),
    "San Miguel": (BA, "San Miguel$"), "Jose C Paz": (BA, "Jos[eé] C\\\\. ?Paz$"),
    "Malvinas Argentinas": (BA, "Malvinas Argentinas$"), "Pilar": (BA, "Pilar$"),
    "Escobar": (BA, "Escobar$"), "La Plata": (BA, "(La Plata|Ensenada|Berisso)$"),
    "Mar del Plata": (BA, "General Pueyrred[oó]n$"),
    "Rosario": ("^(Provincia de )?Santa Fe$", "Rosario$"),
    "Santa Fe": ("^(Provincia de )?Santa Fe$", "La Capital$"),
    "Cordoba": ("^(Provincia de )?C[oó]rdoba$", "Capital$"),
    "Tucuman": ("^(Provincia de )?Tucum[aá]n$", "Capital$"),
    "Mendoza": ("^(Provincia de )?Mendoza$", "(Capital|Godoy Cruz|Guaymall[eé]n|Las Heras)$"),
}
RADIO_GRADOS = {
    "Sao Paulo": 0.22, "Rio de Janeiro": 0.22, "Brasilia": 0.2, "Belo Horizonte": 0.12,
    "Porto Alegre": 0.11, "Curitiba": 0.11, "Salvador": 0.12, "Fortaleza": 0.11, "Recife": 0.1,
    "Asuncion": 0.07, "Ciudad del Este": 0.08, "Guarulhos": 0.1, "Campinas": 0.1, "Goiania": 0.1,
    "Manaus": 0.12, "Belem": 0.1,
}
# Las mismas ciudades que Zona.kt de la app (Bernal ya esta dentro de Quilmes).
CIUDADES = [
    ("Buenos Aires", "AR", -34.61, -58.44), ("Quilmes", "AR", -34.73, -58.27),
    ("Berazategui", "AR", -34.77, -58.21), ("Florencio Varela", "AR", -34.81, -58.28),
    ("Avellaneda", "AR", -34.66, -58.37), ("Lanus", "AR", -34.71, -58.39),
    ("Lomas de Zamora", "AR", -34.76, -58.41), ("Almirante Brown", "AR", -34.83, -58.39),
    ("Esteban Echeverria", "AR", -34.82, -58.47), ("Ezeiza", "AR", -34.85, -58.52),
    ("La Matanza", "AR", -34.77, -58.62), ("Moron", "AR", -34.65, -58.62), ("Merlo", "AR", -34.67, -58.73),
    ("Moreno", "AR", -34.65, -58.79), ("Hurlingham", "AR", -34.59, -58.64), ("Ituzaingo", "AR", -34.66, -58.67),
    ("Tres de Febrero", "AR", -34.60, -58.56), ("San Martin", "AR", -34.57, -58.54),
    ("Vicente Lopez", "AR", -34.53, -58.48), ("San Isidro", "AR", -34.47, -58.53),
    ("San Fernando", "AR", -34.44, -58.56), ("Tigre", "AR", -34.43, -58.58), ("San Miguel", "AR", -34.54, -58.71),
    ("Jose C Paz", "AR", -34.52, -58.77), ("Malvinas Argentinas", "AR", -34.49, -58.70),
    ("Pilar", "AR", -34.46, -58.91), ("Escobar", "AR", -34.35, -58.80), ("La Plata", "AR", -34.92, -57.95),
    ("Rosario", "AR", -32.95, -60.66), ("Cordoba", "AR", -31.42, -64.18), ("Mendoza", "AR", -32.89, -68.84),
    ("Mar del Plata", "AR", -38.00, -57.56), ("Tucuman", "AR", -26.82, -65.22), ("Santa Fe", "AR", -31.63, -60.70),
    ("Asuncion", "PY", -25.28, -57.63), ("Lambare", "PY", -25.34, -57.62),
    ("Fernando de la Mora", "PY", -25.32, -57.55), ("San Lorenzo", "PY", -25.34, -57.51),
    ("Luque", "PY", -25.27, -57.49), ("Capiata", "PY", -25.36, -57.45), ("Nemby", "PY", -25.39, -57.54),
    ("Ciudad del Este", "PY", -25.51, -54.61), ("Encarnacion", "PY", -27.33, -55.87),
    ("Mariano Roque Alonso", "PY", -25.20, -57.53), ("Limpio", "PY", -25.17, -57.49),
    ("Villa Elisa", "PY", -25.37, -57.59), ("Itaugua", "PY", -25.39, -57.35), ("Aregua", "PY", -25.31, -57.39),
    ("Hernandarias", "PY", -25.40, -54.64), ("Presidente Franco", "PY", -25.56, -54.61),
    ("Sao Paulo", "BR", -23.55, -46.63), ("Rio de Janeiro", "BR", -22.91, -43.20),
    ("Belo Horizonte", "BR", -19.92, -43.94), ("Porto Alegre", "BR", -30.03, -51.23),
    ("Curitiba", "BR", -25.43, -49.27), ("Salvador", "BR", -12.97, -38.50), ("Fortaleza", "BR", -3.73, -38.53),
    ("Recife", "BR", -8.05, -34.90), ("Brasilia", "BR", -15.79, -47.88), ("Guarulhos", "BR", -23.46, -46.53),
    ("Osasco", "BR", -23.53, -46.79), ("Santo Andre", "BR", -23.66, -46.53),
    ("Sao Bernardo do Campo", "BR", -23.69, -46.56), ("Campinas", "BR", -22.91, -47.06),
    ("Niteroi", "BR", -22.88, -43.10), ("Sao Goncalo", "BR", -22.83, -43.05),
    ("Duque de Caxias", "BR", -22.79, -43.31), ("Nova Iguacu", "BR", -22.76, -43.45),
    ("Goiania", "BR", -16.69, -49.26), ("Manaus", "BR", -3.12, -60.02), ("Belem", "BR", -1.46, -48.49),
    ("Florianopolis", "BR", -27.60, -48.55), ("Foz do Iguacu", "BR", -25.52, -54.58),
]

PREF = ["avenida ", "avda ", "av ", "calle ", "pasaje ", "boulevard ", "bulevar ", "diagonal ", "camino ",
        "rua ", "travessa ", "estrada ", "alameda ", "rodovia ", "ruta "]
ABREV = [("general", "gral"), ("teniente", "tte"), ("mariscal", "mcal"), ("coronel", "cnel"), ("doctor", "dr"),
         ("presidente", "pte"), ("capitan", "cap"), ("sargento", "sgto"), ("ingeniero", "ing"),
         ("comandante", "cte"), ("almirante", "alte"), ("profesor", "prof"), ("santa", "sta"), ("doutor", "dr")]


def norm(s):
    """Igual que Alertas.norm de la app."""
    d = unicodedata.normalize("NFD", s or "")
    d = "".join(ch for ch in d if not unicodedata.category(ch).startswith("M"))
    return re.sub(r"[^a-z0-9]+", " ", d.lower()).strip()


def slug(s):
    return norm(s).replace(" ", "_")


def variantes(nombre):
    """Igual que OsmDatos.variantes de la app."""
    n = norm(nombre)
    if len(n) < 5:
        return []
    out = [n]
    for p in PREF:
        if n.startswith(p):
            resto = n[len(p):]
            if len(resto) >= 6 and not all(c.isdigit() or c == " " for c in resto):
                out.append(resto)
            if p == "avenida ":
                out += ["av " + resto, "avda " + resto]
    for v in list(out):
        a = v
        for largo, corto in ABREV:
            a = (" " + a + " ").replace(" " + largo + " ", " " + corto + " ").strip()
        if a != v:
            out.append(a)
    vistos, r = set(), []
    for v in out:
        if len(v) >= 5 and v not in vistos:
            vistos.add(v)
            r.append(v)
    return r


def seleccion(nombre, la, lo, recuadro):
    a = AREAS.get(nombre)
    if recuadro or a is None:
        d = RADIO_GRADOS.get(nombre, 0.09)
        return "", f"({la - d},{lo - d},{la + d},{lo + d})"
    prov, nom = a
    if prov is None:
        sel = f'area["admin_level"="4"]["name"~"{nom}"]->.a;'
    else:
        sel = (f'area["admin_level"="4"]["name"~"{prov}"]->.p;'
               f'rel(area.p)["boundary"="administrative"]["admin_level"~"^[5-8]$"]["name"~"{nom}"];'
               'map_to_area->.a;')
    return sel, "(area.a)"


def consulta_general(sel, f):
    return (f'[out:json][timeout:300];{sel}('
            f'way{f}["highway"]["name"]["surface"~"{SUPERFICIES}"];'
            f'way{f}["highway"="track"]["name"];'
            f'way{f}["highway"]["name"]["flood_prone"="yes"];'
            f'way{f}["highway"~"^(motorway|trunk)$"]["name"];'
            f'nwr{f}["amenity"~"^(school|kindergarten|college)$"]["addr:street"]["addr:housenumber"];'
            f'node{f}["place"~"^(city|town|village|suburb|quarter|neighbourhood|hamlet|locality)$"]["name"];'
            ');out tags;')


def consulta_villas(sel, f):
    return (f'[out:json][timeout:300];{sel}('
            f'way{f}["landuse"="residential"]["residential"="informal"];'
            f'rel{f}["landuse"="residential"]["residential"="informal"];'
            f'way{f}["informal"="yes"]["landuse"];'
            f'rel{f}["informal"="yes"]["landuse"];'
            f'way{f}["place"]["informal"="yes"];'
            ')->.v;.v out tags;.v map_to_area->.va;'
            'way(area.va)["highway"~"^(residential|living_street|service|footway|path|track|unclassified|'
            'pedestrian|steps)$"]["name"];'
            'out tags;')


def pedir(q):
    datos = urllib.parse.urlencode({"data": q}).encode()
    for intento in range(3):
        for srv in SERVIDORES:
            try:
                req = urllib.request.Request(srv, data=datos, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=330) as r:
                    return json.loads(r.read().decode("utf-8")).get("elements", [])
            except Exception as e:
                print("  falla", srv, e, flush=True)
                time.sleep(PAUSA)
        time.sleep(60)
    return None


def ciudad(nombre, pais, la, lo):
    sel, f = seleccion(nombre, la, lo, False)
    gen = pedir(consulta_general(sel, f))
    if gen is None:
        return None
    if not gen and sel:
        sel, f = seleccion(nombre, la, lo, True)
        gen = pedir(consulta_general(sel, f))
        if gen is None:
            return None
    time.sleep(PAUSA)
    vil = pedir(consulta_villas(sel, f)) or []
    tierra, inund, vias, lugares, villas, vcalles = [], [], [], [], [], []
    escuelas, vistas = [], set()

    def sumar(lista, vals):
        for v in vals:
            if v not in lista:
                lista.append(v)

    for el in gen:
        t = el.get("tags") or {}
        name = t.get("name", "")
        if t.get("amenity"):
            h = re.match(r"\d+", t.get("addr:housenumber", ""))
            if h and int(h.group()) > 0:
                for calle in variantes(t.get("addr:street", "")):
                    k = f"{calle}|{int(h.group())}"
                    if k not in vistas:
                        vistas.add(k)
                        escuelas.append({"c": calle, "h": int(h.group())})
        elif "place" in t:
            sumar(lugares, [norm(name)])
        elif t.get("flood_prone") == "yes":
            sumar(inund, variantes(name))
            if t.get("surface") in SUP_SET:
                sumar(tierra, variantes(name))
        elif t.get("highway") in ("motorway", "trunk"):
            sumar(vias, variantes(name))
        elif "highway" in t:
            sumar(tierra, variantes(name))
    for el in vil:
        t = el.get("tags") or {}
        name = t.get("name", "")
        if not name:
            continue
        if "highway" in t:
            sumar(vcalles, variantes(name))
        else:
            sumar(villas, [norm(name)])
    o = {"ciudad": nombre, "t": int(time.time() * 1000), "fuente": "OpenStreetMap (ODbL)",
         "tierra": tierra, "vias": vias, "inundables": inund,
         "lugares": [x for x in lugares if len(x) >= 4], "villas": villas, "villa_calles": vcalles}
    return o, {"escuelas": escuelas}


def main():
    solo = set(sys.argv[1:])
    hechas = {}
    for nombre, pais, la, lo in CIUDADES:
        if solo and pais not in solo:
            continue
        print("ciudad", pais, nombre, flush=True)
        r = ciudad(nombre, pais, la, lo)
        time.sleep(PAUSA)
        if r is None:
            print("  sin datos (se deja el archivo anterior)", flush=True)
            continue
        o, esc = r
        d = f"datos/osm/{pais}"
        os.makedirs(d, exist_ok=True)
        s = slug(nombre)
        with open(f"{d}/{s}.json", "w", encoding="utf-8") as fh:
            json.dump(o, fh, ensure_ascii=False, separators=(",", ":"))
        with open(f"{d}/esc_{s}.json", "w", encoding="utf-8") as fh:
            json.dump(esc, fh, ensure_ascii=False, separators=(",", ":"))
        hechas.setdefault(pais, []).append(s)
        print(f"  ok: tierra {len(o['tierra'])}, villas {len(o['villas'])}, escuelas {len(esc['escuelas'])}",
              flush=True)
    for pais in {p for _, p, _, _ in CIUDADES}:
        d = f"datos/osm/{pais}"
        if not os.path.isdir(d):
            continue
        todas = sorted(f[:-5] for f in os.listdir(d) if f.endswith(".json") and not f.startswith(("esc_", "_")))
        with open(f"{d}/_indice.json", "w", encoding="utf-8") as fh:
            json.dump({"pais": pais, "ciudades": todas, "fuente": "OpenStreetMap (ODbL)"}, fh,
                      ensure_ascii=False, separators=(",", ":"))
    total = sum(len(v) for v in hechas.values())
    print("ciudades hechas:", total, flush=True)
    if total == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
