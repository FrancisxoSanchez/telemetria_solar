# Telemetría Solar – Servidor (Fase 1)

## Archivos

| Archivo | Qué hace |
|---|---|
| `app.py` | Servidor web (Flask). Recibe los datos del ESP32 y los sirve al dashboard. |
| `database.py` | Base de datos SQLite: tablas, guardado, resumen por hora y limpieza. |
| `simulador_esp32.py` | Se hace pasar por el ESP32 mandando datos falsos cada 500 ms. |
| `generar_datos_prueba.py` | Carga 6 horas de datos falsos para probar el resumen horario. |
| `static/index.html` | Página de prueba mínima (el dashboard real es la Fase 2). |

La base (`telemetria.db`) se crea sola la primera vez.

## Cómo funciona la base de datos

- **`lecturas_crudas`**: cada lectura (cada 500 ms). Se guarda solo la última hora (~7.200 filas como máximo).
- **`resumen_horario`**: una fila por hora con promedio, mínimo y máximo de V, I y P, más la **energía generada (Wh)**. Se guarda para siempre (24 filas por día).
- Cada minuto, el servidor resume las horas terminadas y borra lo crudo de más de 1 hora.
- Los horarios los pone el servidor, no el ESP32 (la placa no tiene reloj).

## Puesta en marcha

1. Instalar Python 3.10 o superior y luego:
   ```
   pip install -r requirements.txt
   ```
2. Arrancar el servidor:
   ```
   python app.py
   ```
3. En otra terminal, arrancar el simulador:
   ```
   python simulador_esp32.py
   ```
4. Abrir `http://localhost:5000` en el navegador: tienen que verse los valores cambiando.
5. (Opcional) Para probar los resúmenes por hora sin esperar: cortar todo, ejecutar
   `python generar_datos_prueba.py` y volver a arrancar el servidor.
   Ver `http://localhost:5000/api/resumen`.

## Prueba de red (antes de tocar el ESP32)

1. Averiguar la IP de la notebook: `ipconfig` (Windows) o `ip a` (Linux).
2. Desde el celular conectado al mismo Wi‑Fi, abrir `http://<IP>:5000`.
3. Si no carga, casi seguro es el **firewall de Windows**: permitir Python en redes privadas,
   o abrir el puerto 5000 de entrada.
4. Desde la otra PC, correr el simulador apuntando a la notebook:
   ```
   python simulador_esp32.py http://<IP>:5000
   ```
   Si eso funciona, el ESP32 también va a funcionar.

## API

| Método | Ruta | Descripción |
|---|---|---|
| POST | `/api/telemetria` | Recibe `{"voltaje":18.2,"corriente":0.41,"potencia":7.46}`. La potencia es opcional. También acepta lotes: `{"lecturas":[{..., "hace_ms":500}, {...}]}` |
| GET | `/api/actual` | Última lectura, si el ESP32 está en línea y la energía de hoy. |
| GET | `/api/historico?minutos=60` | Lecturas de la última hora (máx. 600 puntos, promediados). |
| GET | `/api/resumen?horas=24` | Resumen por hora. |

Los horarios se devuelven en UTC (ISO 8601); el navegador los pasa a hora local.
