#!/usr/bin/env python3
"""radiAr: lluvia en vivo por ciudad, cada hora.
Fuente: MET Norway, Locationforecast 2.0 (api.met.no), licencia CC BY 4.0: "Datos del tiempo: MET Norway".
Para cada ciudad se mira la lluvia prevista para la proxima hora en su centro (coordenadas aproximadas).
Si es 0,3 mm o mas, la app prende la alerta INUNDABLE en las calles marcadas como inundables de esa ciudad.
Salida: datos/lluvia.json (unos pocos kilobytes: la app lo baja cada media hora)."""
import json
import os
import sys
import time
import unicodedata
import re
import urllib.request
from datetime import datetime, timezone

# MET Norway pide identificarse con el nombre de la app y un contacto (el repositorio).
UA = {"User-Agent": "radiAr-datos/1.0 github.com/HeberDeveloper/radiAr"}
URL = "https://api.met.no/weatherapi/locationforecast/2.0/compact?lat={lat}&lon={lon}"
UMBRAL_MM = 0.3

# nombre, pais, latitud, longitud (centro aproximado)
CIUDADES = [
    ("Buenos Aires", "AR", -34.61, -58.44),
    ("Quilmes", "AR", -34.73, -58.27), ("Bernal", "AR", -34.71, -58.28),
    ("Berazategui", "AR", -34.77, -58.21), ("Florencio Varela", "AR", -34.81, -58.28),
    ("Avellaneda", "AR", -34.66, -58.37), ("Lanus", "AR", -34.71, -58.39),
    ("Lomas de Zamora", "AR", -34.76, -58.41), ("Almirante Brown", "AR", -34.83, -58.39),
    ("Esteban Echeverria", "AR", -34.82, -58.47), ("Ezeiza", "AR", -34.85, -58.52),
    ("La Matanza", "AR", -34.77, -58.62), ("Moron", "AR", -34.65, -58.62),
    ("Merlo", "AR", -34.67, -58.73), ("Moreno", "AR", -34.65, -58.79),
    ("Hurlingham", "AR", -34.59, -58.64), ("Ituzaingo", "AR", -34.66, -58.67),
    ("Tres de Febrero", "AR", -34.60, -58.56), ("San Martin", "AR", -34.57, -58.54),
    ("Vicente Lopez", "AR", -34.53, -58.48), ("San Isidro", "AR", -34.47, -58.53),
    ("San Fernando", "AR", -34.44, -58.56), ("Tigre", "AR", -34.43, -58.58),
    ("San Miguel", "AR", -34.54, -58.71), ("Jose C Paz", "AR", -34.52, -58.77),
    ("Malvinas Argentinas", "AR", -34.49, -58.70), ("Pilar", "AR", -34.46, -58.91),
    ("Escobar", "AR", -34.35, -58.80), ("La Plata", "AR", -34.92, -57.95),
    ("Rosario", "AR", -32.95, -60.66), ("Cordoba", "AR", -31.42, -64.18),
    ("Mendoza", "AR", -32.89, -68.84), ("Mar del Plata", "AR", -38.00, -57.56),
    ("Tucuman", "AR", -26.82, -65.22), ("Santa Fe", "AR", -31.63, -60.70),
    ("Asuncion", "PY", -25.28, -57.63), ("Lambare", "PY", -25.34, -57.62),
    ("Fernando de la Mora", "PY", -25.32, -57.55), ("San Lorenzo", "PY", -25.34, -57.51),
    ("Luque", "PY", -25.27, -57.49), ("Capiata", "PY", -25.36, -57.45),
    ("Nemby", "PY", -25.39, -57.54), ("Villa Elisa", "PY", -25.37, -57.59),
    ("Mariano Roque Alonso", "PY", -25.20, -57.53), ("Limpio", "PY", -25.17, -57.49),
    ("Ciudad del Este", "PY", -25.51, -54.61), ("Encarnacion", "PY", -27.33, -55.87),
    ("Sao Paulo", "BR", -23.55, -46.63), ("Rio de Janeiro", "BR", -22.91, -43.20),
    ("Belo Horizonte", "BR", -19.92, -43.94), ("Porto Alegre", "BR", -30.03, -51.23),
    ("Curitiba", "BR", -25.43, -49.27), ("Salvador", "BR", -12.97, -38.50),
    ("Fortaleza", "BR", -3.73, -38.53), ("Recife", "BR", -8.05, -34.90),
    ("Brasilia", "BR", -15.79, -47.88),
]


def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def lluvia_mm(lat, lon):
    req = urllib.request.Request(URL.format(lat=lat, lon=lon), headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        js = json.loads(r.read().decode("utf-8"))
    serie = js["properties"]["timeseries"]
    if not serie:
        return None
    d = serie[0].get("data", {})
    for clave in ("next_1_hours", "next_6_hours"):
        b = d.get(clave)
        if b and "details" in b and "precipitation_amount" in b["details"]:
            mm = float(b["details"]["precipitation_amount"])
            return mm if clave == "next_1_hours" else mm / 6.0
    return None


def main():
    sal, errores = [], 0
    for nombre, pais, lat, lon in CIUDADES:
        try:
            mm = lluvia_mm(lat, lon)
        except Exception as e:
            print("fallo", nombre, str(e)[:100], flush=True)
            errores += 1
            mm = None
        if mm is not None:
            sal.append({"ciudad": nombre, "pais": pais, "claves": [norm(nombre)], "mm": round(mm, 1),
                        "lluvia": mm >= UMBRAL_MM})
        time.sleep(0.3)
    if not sal:
        sys.exit(1)
    os.makedirs("datos", exist_ok=True)
    obj = {"schema_version": 1, "generado": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
           "fuente": "MET Norway (api.met.no), CC BY 4.0", "umbral_mm": UMBRAL_MM, "estimado": True,
           "ciudades": sal}
    with open("datos/lluvia.json", "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    print("ciudades:", len(sal), "con lluvia:", sum(1 for c in sal if c["lluvia"]), "errores:", errores, flush=True)


if __name__ == "__main__":
    main()
