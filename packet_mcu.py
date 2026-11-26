from gpio import *
from time import *
from environment import Environment

# ============================================
# CLIMAFELIZ - SISTEMA DE RIEGO AUTOMATICO (v6)
# ============================================

# Umbrales de humedad (escala 0-100): bajo este valor se enciende el riego
UMBRAL_VINAS = 35
UMBRAL_PALTAS = 40
UMBRAL_TOMATES = 45

# Histeresis: el riego se apaga al llegar a umbral + MARGEN
MARGEN = 10

# Los Lawn Sprinkler SUBEN la variable "Water Level" al regar. Si empieza en 0
# y USAR_NIVEL_AGUA esta en True, el riego nunca arranca. Dejalo en False.
NOMBRE_NIVEL_AGUA = "Water Level"
AGUA_MINIMA = 20
USAR_NIVEL_AGUA = False

# ---------------------------------------------------------
# MODO DE LECTURA DE HUMEDAD
#   "SIMULADO": la humedad de cada cultivo sube mientras su aspersor
#               riega y baja sola cuando esta apagado (ciclo rapido).
#   "ENTORNO" : lee la variable "Humidity" del entorno (0-100).
#               Los aspersores la suben, pero muy lento (5% por hora),
#               y es una sola variable para los tres cultivos.
#   "SENSOR"  : lee los sensores fisicos en D0, D1, D2.
# ---------------------------------------------------------
MODO_HUMEDAD = "SIMULADO"

# Parametros del modo SIMULADO (puntos de humedad por segundo)
HUMEDAD_INICIAL = 20
SUBE_REGANDO = 5
BAJA_SECANDO = 1

# Pines de los aspersores (viñas, paltas, tomates).
# La orden se envia con customWrite por las dos numeraciones posibles
# de pines (0, 1, 2 y A0, A1, A2), para que llegue al aspersor.
PINES_ASPERSOR = [0, 1, 2]
try:
    PINES_ASPERSOR_ALT = [A0, A1, A2]
except:
    PINES_ASPERSOR_ALT = []

# Estado de cada aspersor (0 = apagado, 1 = encendido)
riego_vinas = 0
riego_paltas = 0
riego_tomates = 0

# Humedad simulada de cada cultivo
sim_vinas = HUMEDAD_INICIAL
sim_paltas = HUMEDAD_INICIAL
sim_tomates = HUMEDAD_INICIAL


def leer_agua():
    """Devuelve (nivel, origen). Intenta el entorno y, si falla, el pin A3."""
    try:
        valor = Environment.get(NOMBRE_NIVEL_AGUA)
        return valor, "entorno"
    except:
        return analogRead(3), "pin A3"


def leer_humedad_sensor(pin):
    """Lee un sensor fisico y devuelve la humedad en escala 0-100."""
    valor = digitalRead(pin)
    if valor <= 1:
        # Lectura digital: 0 = seco, 1 = humedo
        return valor * 100
    if valor > 100:
        # Escala 0-255 del sensor (0-1023 por si acaso)
        if valor <= 255:
            return valor * 100 / 255
        return valor * 100 / 1023
    return valor


def leer_humedad_entorno():
    """Lee la variable 'Humidity' del entorno (0-100)."""
    try:
        return Environment.get("Humidity")
    except:
        return 0


def mover_aspersor(indice, estado):
    """Enciende (1) o apaga (0) un Lawn Sprinkler.
    El aspersor lee el mensaje con customRead y lo convierte con int(),
    asi que debe llegar como texto "0" o "1". No se usa analogWrite porque
    enviaria 1023, que el aspersor no entiende como 1."""
    mensaje = str(estado)
    try:
        customWrite(PINES_ASPERSOR[indice], mensaje)
    except:
        print("ERROR customWrite en pin", PINES_ASPERSOR[indice])
    if indice < len(PINES_ASPERSOR_ALT):
        try:
            customWrite(PINES_ASPERSOR_ALT[indice], mensaje)
        except:
            pass


def actualizar_simulacion(humedad, regando):
    """Sube la humedad si esta regando y la baja si no, entre 0 y 100."""
    if regando:
        humedad = humedad + SUBE_REGANDO
    else:
        humedad = humedad - BAJA_SECANDO
    if humedad > 100:
        humedad = 100
    if humedad < 0:
        humedad = 0
    return humedad


def controlar_riego(humedad, umbral, estado, agua):
    # Sin agua suficiente: apagar por seguridad
    if USAR_NIVEL_AGUA and agua <= AGUA_MINIMA:
        return 0

    # Suelo seco: encender
    if humedad < umbral:
        return 1

    # Suelo suficientemente humedo: apagar
    if humedad >= umbral + MARGEN:
        return 0

    # Zona intermedia: mantener el estado anterior (evita parpadeo)
    return estado


def main():
    global riego_vinas, riego_paltas, riego_tomates
    global sim_vinas, sim_paltas, sim_tomates

    print("CLIMAFELIZ - SISTEMA DE RIEGO")
    print("Iniciando MCU... modo humedad:", MODO_HUMEDAD)

    # Arrancar con los tres aspersores apagados
    mover_aspersor(0, 0)
    mover_aspersor(1, 0)
    mover_aspersor(2, 0)

    while True:
        # 1. Leer humedad de cada cultivo (viñas, paltas, tomates)
        if MODO_HUMEDAD == "SIMULADO":
            humedad_vinas = sim_vinas
            humedad_paltas = sim_paltas
            humedad_tomates = sim_tomates
        elif MODO_HUMEDAD == "ENTORNO":
            humedad_vinas = leer_humedad_entorno()
            humedad_paltas = humedad_vinas
            humedad_tomates = humedad_vinas
        else:
            humedad_vinas = leer_humedad_sensor(0)     # D0
            humedad_paltas = leer_humedad_sensor(1)    # D1
            humedad_tomates = leer_humedad_sensor(2)   # D2

        # 2. Leer nivel de agua (cm)
        agua, origen = leer_agua()

        # 3. Decidir el riego de cada cultivo
        riego_vinas = controlar_riego(
            humedad_vinas, UMBRAL_VINAS, riego_vinas, agua
        )
        riego_paltas = controlar_riego(
            humedad_paltas, UMBRAL_PALTAS, riego_paltas, agua
        )
        riego_tomates = controlar_riego(
            humedad_tomates, UMBRAL_TOMATES, riego_tomates, agua
        )

        # 4. Activar aspersores (0 = viñas, 1 = paltas, 2 = tomates)
        mover_aspersor(0, riego_vinas)
        mover_aspersor(1, riego_paltas)
        mover_aspersor(2, riego_tomates)

        # 5. En modo simulado, la humedad responde al riego
        if MODO_HUMEDAD == "SIMULADO":
            sim_vinas = actualizar_simulacion(sim_vinas, riego_vinas)
            sim_paltas = actualizar_simulacion(sim_paltas, riego_paltas)
            sim_tomates = actualizar_simulacion(sim_tomates, riego_tomates)

        # 6. Mostrar resultados
        print("VIÑAS:", humedad_vinas, "RIEGO:", riego_vinas)
        print("PALTAS:", humedad_paltas, "RIEGO:", riego_paltas)
        print("TOMATES:", humedad_tomates, "RIEGO:", riego_tomates)
        print("AGUA:", agua, "(origen:", origen + ")")
        if USAR_NIVEL_AGUA and agua <= AGUA_MINIMA:
            print("AVISO: nivel de agua bajo, riego bloqueado")
        print("-----")

        delay(1000)


if __name__ == "__main__":
    main()