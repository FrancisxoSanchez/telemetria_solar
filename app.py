"""
Servidor de telemetría solar (corre en la notebook).

Uso:
    pip install flask
    python app.py

Endpoints:
    POST /api/telemetria   <- el ESP32 manda sus lecturas acá
    GET  /api/actual       -> última lectura + si el ESP32 está en línea
    GET  /api/historico    -> lecturas de los últimos N minutos (?minutos=60)
    GET  /api/resumen      -> promedios por hora (?horas=24)
    GET  /                 -> dashboard (Fase 2)
"""

import threading
import time
from datetime import datetime, timezone

from flask import Flask, jsonify, request, send_from_directory

import database as db

PUERTO = 5000
SEGUNDOS_PARA_OFFLINE = 5   # si no llega nada en 5 s, el ESP32 figura desconectado

app = Flask(__name__, static_folder="static")


def a_iso(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


# ------------------------------------------------------------------ recepción

def _validar(item):
    """Devuelve (voltaje, corriente, potencia) o lanza ValueError."""
    v = float(item["voltaje"])
    i = float(item["corriente"])
    # La potencia es opcional: si no viene, se calcula
    p = float(item["potencia"]) if "potencia" in item else v * i
    return v, i, p


@app.post("/api/telemetria")
def recibir_telemetria():
    """Acepta una lectura sola o un lote.

    Una lectura:  {"voltaje": 18.2, "corriente": 0.41, "potencia": 7.46}
    Un lote:      {"lecturas": [ {..., "hace_ms": 1500}, {..., "hace_ms": 1000}, ... ]}

    En los lotes, "hace_ms" indica cuántos milisegundos antes del envío se tomó
    cada lectura, así el servidor puede reconstruir la hora exacta.
    """
    datos = request.get_json(silent=True)
    if datos is None:
        return jsonify(ok=False, error="El cuerpo debe ser JSON"), 400

    ahora = time.time()
    items = datos["lecturas"] if isinstance(datos, dict) and "lecturas" in datos else [datos]

    lecturas = []
    try:
        for item in items:
            ts = ahora - float(item.get("hace_ms", 0)) / 1000.0
            lecturas.append((ts, *_validar(item)))
    except (KeyError, ValueError, TypeError) as e:
        return jsonify(ok=False, error=f"Dato inválido: {e}"), 400

    db.guardar_lecturas(lecturas)
    return jsonify(ok=True, guardadas=len(lecturas))


# ------------------------------------------------------------------ consultas

@app.get("/api/actual")
def actual():
    ultima = db.ultima_lectura()
    if not ultima:
        return jsonify(en_linea=False, lectura=None, energia_hoy_wh=db.energia_hoy_wh())
    hace = time.time() - ultima["ts"]
    ultima["timestamp"] = a_iso(ultima.pop("ts"))
    return jsonify(
        en_linea=hace < SEGUNDOS_PARA_OFFLINE,
        segundos_desde_ultima=round(hace, 1),
        lectura=ultima,
        energia_hoy_wh=round(db.energia_hoy_wh(), 3),
    )


@app.get("/api/historico")
def historico():
    minutos = min(request.args.get("minutos", 60, type=int), 60)
    max_puntos = request.args.get("max_puntos", 600, type=int)
    filas = db.historico_crudo(minutos, max_puntos)
    for f in filas:
        f["timestamp"] = a_iso(f.pop("ts"))
    return jsonify(filas)


@app.get("/api/resumen")
def resumen():
    horas = request.args.get("horas", 24, type=int)
    filas = db.resumen(horas)
    for f in filas:
        f["hora_inicio"] = a_iso(f["hora_inicio"])
    return jsonify(filas)


# ------------------------------------------------------------------ dashboard

@app.get("/")
def dashboard():
    return send_from_directory("static", "index.html")


# ------------------------------------------------------------------ tareas de fondo

def bucle_mantenimiento():
    while True:
        try:
            resumidas, borradas = db.mantenimiento()
            if resumidas or borradas:
                print(f"[mantenimiento] {resumidas} hora(s) resumida(s), "
                      f"{borradas} lectura(s) cruda(s) borrada(s)")
        except Exception as e:
            print(f"[mantenimiento] error: {e}")
        time.sleep(60)


if __name__ == "__main__":
    db.inicializar()
    threading.Thread(target=bucle_mantenimiento, daemon=True).start()
    print(f"Servidor en http://0.0.0.0:{PUERTO}  (desde otra PC: http://<IP-de-esta-notebook>:{PUERTO})")
    # host="0.0.0.0" es lo que permite que el ESP32 y otras PCs se conecten
    app.run(host="0.0.0.0", port=PUERTO, debug=False, threaded=True)
