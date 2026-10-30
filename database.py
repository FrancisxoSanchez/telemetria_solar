"""
Base de datos del sistema de telemetría solar (SQLite).

Estrategia de almacenamiento en dos niveles:

  1. lecturas_crudas   -> cada lectura del ESP32 (cada ~500 ms).
                          Solo se conserva la ÚLTIMA HORA.
  2. resumen_horario   -> una fila por hora con promedio, mínimo, máximo
                          y energía generada (Wh). Se guarda para siempre.

Cada minuto un proceso en segundo plano:
  a) resume las horas que ya terminaron y todavía no tienen resumen,
  b) borra las lecturas crudas de más de 1 hora.

Cuánto ocupa: la tabla cruda nunca pasa de ~7.200 filas (3600 s / 0,5 s)
y el resumen suma 24 filas por día (~8.760 por año). Prácticamente nada.
"""

import sqlite3
import time
from datetime import datetime

DB_PATH = "telemetria.db"
RETENCION_CRUDA_S = 3600   # 1 hora de lecturas crudas
GAP_MAX_S = 5.0            # si entre dos lecturas pasan más de 5 s, se asume que
                           # el ESP32 estuvo desconectado y ese hueco no suma energía

ESQUEMA = """
CREATE TABLE IF NOT EXISTS lecturas_crudas (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         REAL    NOT NULL,   -- segundos Unix (UTC), lo pone el servidor
    voltaje    REAL    NOT NULL,   -- V
    corriente  REAL    NOT NULL,   -- A
    potencia   REAL    NOT NULL    -- W
);
CREATE INDEX IF NOT EXISTS idx_crudas_ts ON lecturas_crudas(ts);

CREATE TABLE IF NOT EXISTS resumen_horario (
    hora_inicio  REAL PRIMARY KEY,  -- segundos Unix del comienzo de la hora
    muestras     INTEGER NOT NULL,  -- cuántas lecturas entraron en el promedio
    v_prom REAL, v_min REAL, v_max REAL,
    i_prom REAL, i_min REAL, i_max REAL,
    p_prom REAL, p_min REAL, p_max REAL,
    energia_wh   REAL               -- energía generada en esa hora
);
"""


def conectar():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def inicializar():
    with conectar() as conn:
        conn.execute("PRAGMA journal_mode=WAL")  # permite leer y escribir a la vez
        conn.executescript(ESQUEMA)


# ---------------------------------------------------------------- escritura

def guardar_lecturas(lecturas):
    """lecturas: lista de tuplas (ts, voltaje, corriente, potencia)."""
    with conectar() as conn:
        conn.executemany(
            "INSERT INTO lecturas_crudas (ts, voltaje, corriente, potencia) VALUES (?,?,?,?)",
            lecturas,
        )


# ---------------------------------------------------------------- lectura

def ultima_lectura():
    with conectar() as conn:
        fila = conn.execute(
            "SELECT ts, voltaje, corriente, potencia FROM lecturas_crudas ORDER BY ts DESC LIMIT 1"
        ).fetchone()
    return dict(fila) if fila else None


def historico_crudo(minutos=60, max_puntos=600):
    """Lecturas de los últimos N minutos.

    Una hora a 500 ms son 7.200 puntos: demasiado para un gráfico. Si hay más
    de max_puntos, se agrupan en intervalos iguales y se promedian.
    """
    desde = time.time() - minutos * 60
    with conectar() as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM lecturas_crudas WHERE ts >= ?", (desde,)
        ).fetchone()[0]

        if n <= max_puntos:
            filas = conn.execute(
                "SELECT ts, voltaje, corriente, potencia FROM lecturas_crudas "
                "WHERE ts >= ? ORDER BY ts",
                (desde,),
            ).fetchall()
        else:
            ancho = (minutos * 60) / max_puntos  # segundos por grupo
            filas = conn.execute(
                "SELECT AVG(ts) AS ts, AVG(voltaje) AS voltaje, "
                "AVG(corriente) AS corriente, AVG(potencia) AS potencia "
                "FROM lecturas_crudas WHERE ts >= ? "
                "GROUP BY CAST((ts - ?) / ? AS INTEGER) ORDER BY ts",
                (desde, desde, ancho),
            ).fetchall()
    return [dict(f) for f in filas]


def resumen(horas=24):
    desde = time.time() - horas * 3600
    with conectar() as conn:
        filas = conn.execute(
            "SELECT * FROM resumen_horario WHERE hora_inicio >= ? ORDER BY hora_inicio",
            (desde,),
        ).fetchall()
    return [dict(f) for f in filas]


def energia_hoy_wh():
    """Energía del día: horas ya resumidas + lo que va de las lecturas crudas."""
    ahora = datetime.now()
    inicio_dia = ahora.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    hora_actual = _inicio_de_hora(time.time())
    with conectar() as conn:
        resumida = conn.execute(
            "SELECT COALESCE(SUM(energia_wh), 0) FROM resumen_horario "
            "WHERE hora_inicio >= ? AND hora_inicio < ?",
            (inicio_dia, hora_actual),
        ).fetchone()[0]
        crudas = conn.execute(
            "SELECT ts, potencia FROM lecturas_crudas WHERE ts >= ? ORDER BY ts",
            (max(hora_actual, inicio_dia),),
        ).fetchall()
    return resumida + _integrar_energia_wh(crudas)


# ---------------------------------------------------------------- mantenimiento

def _inicio_de_hora(ts):
    """Comienzo de la hora local que contiene ts (en segundos Unix)."""
    return datetime.fromtimestamp(ts).replace(minute=0, second=0, microsecond=0).timestamp()


def _integrar_energia_wh(filas):
    """Energía = suma de potencia x tiempo (método del trapecio), en Wh."""
    energia_ws = 0.0
    for a, b in zip(filas, filas[1:]):
        dt = b["ts"] - a["ts"]
        if 0 < dt <= GAP_MAX_S:
            energia_ws += (a["potencia"] + b["potencia"]) / 2 * dt
    return energia_ws / 3600.0


def mantenimiento():
    """Resume las horas terminadas y borra lo crudo de más de 1 hora.

    Devuelve (horas_resumidas, filas_borradas).
    """
    ahora = time.time()
    hora_actual = _inicio_de_hora(ahora)
    resumidas = 0

    with conectar() as conn:
        ts_min = conn.execute("SELECT MIN(ts) FROM lecturas_crudas").fetchone()[0]

        if ts_min is not None:
            hora = _inicio_de_hora(ts_min)
            while hora < hora_actual:          # solo horas que ya terminaron
                fin = hora + 3600
                ya_existe = conn.execute(
                    "SELECT 1 FROM resumen_horario WHERE hora_inicio = ?", (hora,)
                ).fetchone()
                if not ya_existe:
                    filas = conn.execute(
                        "SELECT ts, voltaje, corriente, potencia FROM lecturas_crudas "
                        "WHERE ts >= ? AND ts < ? ORDER BY ts",
                        (hora, fin),
                    ).fetchall()
                    if filas:
                        _insertar_resumen(conn, hora, filas)
                        resumidas += 1
                hora = fin

        # Lo crudo de más de una hora ya pertenece a horas terminadas y resumidas
        borradas = conn.execute(
            "DELETE FROM lecturas_crudas WHERE ts < ?", (ahora - RETENCION_CRUDA_S,)
        ).rowcount

    return resumidas, borradas


def _insertar_resumen(conn, hora, filas):
    def stats(col):
        valores = [f[col] for f in filas]
        return sum(valores) / len(valores), min(valores), max(valores)

    v, i, p = stats("voltaje"), stats("corriente"), stats("potencia")
    conn.execute(
        "INSERT INTO resumen_horario VALUES (?,?, ?,?,?, ?,?,?, ?,?,?, ?)",
        (hora, len(filas), *v, *i, *p, _integrar_energia_wh(filas)),
    )
