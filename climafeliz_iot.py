import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta

# Datos basicos (5 strings)
empresa = "ClimaFeliz SpA"
archivo = "mediciones_climafeliz.txt"
sep = "|"
cabecera = "FECHA|CLIENTE|REGION|CULTIVO|HUM|EST|RIEGO|LLENADO|ALERTA"
plataforma = "AWS API Gateway"

# Tuplas con regiones y limites del estanque (mismos valores que en Packet Tracer)
regiones = ("IV Región", "V Región", "VI Región", "VII Región")
limites_est = (20, 30, 90)  # critico, prende llenado, apaga llenado

# Listas
cultivos = ["Viña", "Palta", "Tomate Limachino"]
alertas = []
clientes = [
    {"id": "CLI-01", "region": "IV Región", "cultivo": "Viña"},
    {"id": "CLI-02", "region": "V Región", "cultivo": "Palta"},
    {"id": "CLI-03", "region": "V Región", "cultivo": "Tomate Limachino"},
    {"id": "CLI-04", "region": "VI Región", "cultivo": "Viña"},
    {"id": "CLI-05", "region": "VII Región", "cultivo": "Palta"},
]

# Diccionarios
umbrales = {
    "Viña": {"min": 35, "max": 45},
    "Palta": {"min": 40, "max": 50},
    "Tomate Limachino": {"min": 45, "max": 55},
}
estados = {c["id"]: {"riego": "OFF", "llenado": "OFF"} for c in clientes}
config_aws = {
    "env_url": "AWS_API_URL",
    "env_key": "AWS_API_KEY",
    "timeout": 10,
}

# Conjunto para no repetir clientes con falta de agua
clientes_criticos = set()


def evaluar_riego(cid, cultivo, hum, est):
    agua_min, llenar_on, llenar_off = limites_est
    u = umbrales[cultivo]
    riego = estados[cid]["riego"]
    llenado = estados[cid]["llenado"]

    if est < llenar_on:
        llenado = "ON"
    elif est >= llenar_off:
        llenado = "OFF"

    # si el estanque baja a 20% o menos se corta el riego
    if est <= agua_min:
        riego = "OFF"
        llenado = "ON"
        alerta = "AGUA_CRITICA"
        clientes_criticos.add(cid)
        alertas.append(f"{cid}: estanque bajo ({est}%), riego bloqueado")
    elif hum < u["min"]:
        riego = "ON"
        alerta = "RIEGO_ON"
    elif hum >= u["max"]:
        riego = "OFF"
        alerta = "HUMEDAD_OK"
    else:
        alerta = "HISTERESIS"

    estados[cid]["riego"] = riego
    estados[cid]["llenado"] = llenado
    return riego, llenado, alerta


def leer_y_limpiar(ruta):
    validos, malos = [], []
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            next(f)  # salto el encabezado
            for num, linea in enumerate(f, 2):
                datos = [x.strip() for x in linea.strip().split(sep)]
                if len(datos) != 9:
                    malos.append(f"Linea {num}: columnas incorrectas")
                    continue

                fecha, cid, reg, cult, h_txt, e_txt, riego, llenado, alerta = datos
                if reg not in regiones or cult not in cultivos:
                    malos.append(f"Linea {num}: region o cultivo invalido")
                    continue
                try:
                    hum, est = float(h_txt), float(e_txt)
                except ValueError:
                    malos.append(f"Linea {num}: no es numero")
                    continue

                if not (0 <= hum <= 100 and 0 <= est <= 100):
                    malos.append(f"Linea {num}: fuera de rango")
                    continue

                deficit = round(max(0, umbrales[cult]["max"] - hum), 1)
                validos.append({
                    "fecha": fecha,
                    "cliente": cid,
                    "region": reg,
                    "cultivo": cult,
                    "humedad": hum,
                    "estanque": est,
                    "riego": 1 if riego == "ON" else 0,
                    "llenado": 1 if llenado == "ON" else 0,
                    "deficit": deficit,
                    "alerta": alerta,
                })
    except OSError as e:
        print("Error leyendo archivo:", e)
    return validos, malos


def enviar_aws(registros):
    url = os.getenv(config_aws["env_url"], "").strip()
    api_key = os.getenv(config_aws["env_key"], "").strip()

    print(f"\n--- Envio a {plataforma} ---")
    if not url:
        print("(Sin AWS_API_URL en entorno, corriendo en modo simulacion)")

    for i, r in enumerate(registros, 1):
        payload = {
            "empresa": empresa,
            "fecha": r["fecha"],
            "cliente": r["cliente"],
            "region": r["region"],
            "cultivo": r["cultivo"],
            "humedad": r["humedad"],
            "estanque": r["estanque"],
            "riego": r["riego"],
            "llenado": r["llenado"],
            "deficit": r["deficit"],
            "alerta": r["alerta"],
        }

        if url:
            body = json.dumps(payload).encode("utf-8")
            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["x-api-key"] = api_key

            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=config_aws["timeout"]) as resp:
                    respuesta = resp.read().decode("utf-8", errors="ignore").strip()
                    print(f"[{i}] {r['cliente']} ({r['cultivo']}) -> HTTP {resp.status} {respuesta}")
                time.sleep(0.5)
            except urllib.error.HTTPError as e:
                detalle = e.read().decode("utf-8", errors="ignore").strip()
                print(f"[{i}] Error HTTP {e.code} en {r['cliente']}: {detalle}")
            except Exception as e:
                print(f"[{i}] Fallo envio {r['cliente']}: {e}")
        else:
            print(f"[{i}] Simulado HTTP 200 -> {r['cliente']}: {json.dumps(payload, ensure_ascii=False)}")


# --- Ejecucion de pruebas ---
print(f"Sistema {empresa}")
mapa = {c["id"]: c for c in clientes}

# Casos de prueba: (cliente, humedad, estanque)
pruebas = [
    ("CLI-01", 28, 65),  # Viña activa riego (<35)
    ("CLI-01", 48, 60),  # Viña apaga riego (>=45)
    ("CLI-02", 34, 25),  # Palta activa riego y llenado
    ("CLI-02", 52, 92),  # Palta apaga ambos
    ("CLI-03", 38, 75),  # Tomate activa riego (<45)
    ("CLI-03", 58, 70),  # Tomate apaga riego (>=55)
    ("CLI-04", 30, 18),  # Agua critica (<=20) bloquea riego
    ("CLI-04", 32, 45),  # Vuelve el agua y riega
    ("CLI-05", 36, 55),  # Palta prende riego
    ("CLI-05", 44, 50),  # Zona histeresis (se mantiene ON)
]

hora = datetime(2026, 11, 25, 8, 0)
lineas = []

for i, (cid, hum, est) in enumerate(pruebas):
    c = mapa[cid]
    fecha = (hora + timedelta(minutes=15 * i)).strftime("%Y-%m-%d %H:%M")
    riego, llenado, alerta = evaluar_riego(cid, c["cultivo"], hum, est)
    lineas.append(f"{fecha}|{cid}|{c['region']}|{c['cultivo']}|{hum}|{est}|{riego}|{llenado}|{alerta}")
    print(f"{cid} ({c['cultivo']}) H:{hum}% E:{est}% -> Riego:{riego} Llenado:{llenado} [{alerta}]")

# Meto 2 lineas malas para probar la limpieza del txt
lineas.append("2026-11-25 10:45|CLI-01|IV Región|Viña|ERROR|50|OFF|OFF|FALLO")
lineas.append("2026-11-25 11:00|CLI-02|V Región|Palta|145|80|OFF|OFF|MALO")

try:
    with open(archivo, "w", encoding="utf-8") as f:
        f.write(cabecera + "\n")
        for l in lineas:
            f.write(l + "\n")
except OSError as e:
    print("Error al guardar:", e)

limpios, malos = leer_y_limpiar(archivo)
print(f"\nLectura txt -> {len(limpios)} validos, {len(malos)} descartados")
for m in malos:
    print(" -", m)

enviar_aws(limpios)

if alertas:
    print("\nAlertas criticas:", list(clientes_criticos))
    for a in alertas:
        print(" !", a)
