"""
Simulador del ESP32: manda datos falsos al servidor, igual que lo hará la placa.
Sirve para probar el servidor y el dashboard sin tener el hardware.

Uso:
    python simulador_esp32.py                          # al servidor local
    python simulador_esp32.py http://192.168.1.50:5000 # a otra PC de la red

Solo usa la librería estándar de Python (no hay que instalar nada).
"""

import json
import math
import random
import sys
import time
import urllib.request

SERVIDOR = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5000"
URL = SERVIDOR.rstrip("/") + "/api/telemetria"
PERIODO_S = 0.5


def lectura_falsa(t):
    # Un panel de ~18 V que varía suave, con "nubes" y algo de ruido
    nube = 0.75 + 0.25 * math.sin(t / 40)
    voltaje = 17.5 + 0.8 * nube + random.uniform(-0.05, 0.05)
    corriente = max(0.0, 0.55 * nube + random.uniform(-0.01, 0.01))
    return {
        "voltaje": round(voltaje, 3),
        "corriente": round(corriente, 4),
        "potencia": round(voltaje * corriente, 4),
    }


def enviar(dato):
    req = urllib.request.Request(
        URL, data=json.dumps(dato).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=2) as resp:
        return resp.status


print(f"Enviando a {URL} cada {PERIODO_S} s (Ctrl+C para cortar)")
inicio = time.time()
while True:
    dato = lectura_falsa(time.time() - inicio)
    try:
        estado = enviar(dato)
        print(f"{estado}  V={dato['voltaje']:.2f}  I={dato['corriente']:.3f}  P={dato['potencia']:.2f}")
    except Exception as e:
        print(f"Error al enviar: {e}")
    time.sleep(PERIODO_S)
