"""
Carga en la base 7 días de datos falsos para probar el dashboard.

Deja la base igual que si el sistema hubiera funcionado una semana:
  - resumen_horario: un promedio por hora de los últimos 7 días
  - lecturas_crudas: solo la última hora, cada 500 ms

Cada día tiene su propio "clima" (soleado, nublado, intermedio) y de noche
el panel no genera.

ATENCIÓN: borra los datos que haya en la base antes de cargar los nuevos.

Uso (con el servidor apagado):
    python generar_datos_prueba.py
"""

import math
import random
import time
from datetime import datetime

import database as db

DIAS = 7
PERIODO_S = 0.5
AMANECER = 7.0     # hora decimal (aprox. Salta en primavera)
ATARDECER = 20.0
V_MAX, I_MAX = 18.5, 0.6


def sol(ts):
    """0 de noche, 1 al mediodía solar."""
    t = datetime.fromtimestamp(ts)
    h = t.hour + t.minute / 60 + t.second / 3600
    if not (AMANECER < h < ATARDECER):
        return 0.0
    return math.sin(math.pi * (h - AMANECER) / (ATARDECER - AMANECER))


clima_por_dia = {}
def clima(ts):
    """Factor del día: 1 = despejado, 0.3 = muy nublado."""
    dia = datetime.fromtimestamp(ts).date()
    if dia not in clima_por_dia:
        clima_por_dia[dia] = random.choice([1.0, 1.0, 0.95, 0.8, 0.6, 0.35])
    return clima_por_dia[dia]


def lectura(ts, ruido=0.04):
    s = sol(ts) * clima(ts) * random.uniform(1 - ruido, 1 + ruido)
    s = max(0.0, min(s, 1.0))
    if s == 0:
        return 0.0, 0.0, 0.0
    v = V_MAX * (0.8 + 0.2 * min(1.0, s * 3))   # el voltaje sube rápido y se mantiene
    i = I_MAX * s                                # la corriente sigue a la luz
    return v, i, v * i


db.inicializar()
with db.conectar() as conn:
    conn.execute("DELETE FROM lecturas_crudas")
    conn.execute("DELETE FROM resumen_horario")

ahora = time.time()
limite_crudo = ahora - db.RETENCION_CRUDA_S
hora_corte = db._inicio_de_hora(limite_crudo)   # desde acá en adelante, datos crudos

# --- 1) Resúmenes por hora de los últimos 7 días
filas_resumen = []
hora = db._inicio_de_hora(ahora - DIAS * 86400)
while hora < hora_corte:
    # 60 muestras dentro de la hora alcanzan para sacar promedio, mín, máx y energía
    muestras = [lectura(hora + k * 60 + 30) for k in range(60)]
    vs, is_, ps = zip(*muestras)
    prom = lambda xs: sum(xs) / len(xs)
    filas_resumen.append((
        hora, 7200,
        prom(vs), min(vs), max(vs),
        prom(is_), min(is_), max(is_),
        prom(ps), min(ps), max(ps),
        prom(ps) * 1.0,          # energía (Wh) = potencia promedio x 1 hora
    ))
    hora += 3600

with db.conectar() as conn:
    conn.executemany(
        "INSERT INTO resumen_horario VALUES (?,?, ?,?,?, ?,?,?, ?,?,?, ?)", filas_resumen
    )

# --- 2) Lecturas crudas desde el comienzo de esa hora hasta ahora (cada 500 ms)
crudas = []
ts = hora_corte
while ts <= ahora:
    crudas.append((ts, *lectura(ts, ruido=0.02)))
    ts += PERIODO_S
db.guardar_lecturas(crudas)

# --- 3) Mantenimiento normal: resume la hora pasada y borra lo crudo viejo
resumidas, borradas = db.mantenimiento()

print(f"Listo: {len(filas_resumen) + resumidas} horas resumidas ({DIAS} días) "
      f"y {len(crudas) - borradas} lecturas crudas de la última hora.\n")
print("Energía por día:")
energia_dia = {}
for f in db.resumen(DIAS * 24 + 1):
    d = datetime.fromtimestamp(f["hora_inicio"])
    dia = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"][d.weekday()] + d.strftime(" %d/%m")
    energia_dia[dia] = energia_dia.get(dia, 0) + f["energia_wh"]
for dia, e in energia_dia.items():
    print(f"  {dia}: {e:6.1f} Wh")