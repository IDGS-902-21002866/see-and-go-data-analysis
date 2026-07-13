import csv
import os
import sys

import cv2
import mediapipe as mp

# Agregamos la raiz del proyecto al path para poder importar src/
# Esto es necesario porque este script vive en tools/, no en la raiz
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from src.landmarks import HandDetector

hand_detector = HandDetector()

# ---------------------------------------------------------------------------
# Configuracion del dataset
# ---------------------------------------------------------------------------

# Mapa tecla -> nombre del gesto
# Agrega o quita gestos aqui segun lo que quieras capturar
GESTOS = {
    "1": "palma_abierta",
    "2": "puno",
    "3": "paz",
    "4": "like",
    "5": "rock",
    "6": "ok",
    "7": "loser",
    "8": "dedo_indice",
    "9": "dedo_medio",
    "0": "dedo_anular",
    "m": "dedo_meñique",
}

# Ruta del archivo CSV donde se guardaran las muestras
CSV_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "landmarks.csv")

# Numero de features por muestra: 21 puntos x 3 coordenadas
NUM_FEATURES = 63

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def inicializar_csv(path: str) -> None:
    """Crea el archivo CSV con el header si no existe o esta vacio."""
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            # Primera columna = label (nombre del gesto)
            # Siguientes 63 columnas = f0, f1, ..., f62
            header = ["label"] + [f"f{i}" for i in range(NUM_FEATURES)]
            writer.writerow(header)
        print(f"CSV creado en: {path}")


def guardar_muestra(path: str, label: str, features) -> None:
    """Agrega una fila al CSV con el label y los 63 features."""
    with open(path, "a", newline="") as f:
        writer = csv.writer(f)
        # features es un numpy array; .tolist() lo convierte a lista normal
        writer.writerow([label] + features.tolist())


def contar_muestras(path: str) -> dict:
    """Lee el CSV y devuelve cuantas muestras hay por gesto."""
    conteo = {gesto: 0 for gesto in GESTOS.values()}

    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return conteo

    with open(path, "r") as f:
        reader = csv.DictReader(f)
        for fila in reader:
            label = fila["label"]
            if label in conteo:
                conteo[label] += 1

    return conteo


# ---------------------------------------------------------------------------
# Dibujo en pantalla
# ---------------------------------------------------------------------------


def dibujar_ui(frame, conteo: dict, ultimo_guardado: str) -> None:
    """
    Dibuja en el frame:
    - Las teclas disponibles y su gesto (esquina superior izquierda)
    - El conteo de muestras por gesto
    - Confirmacion cuando se guarda una muestra
    - Instruccion para salir
    """
    y = 30

    # Teclas disponibles
    for tecla, gesto in GESTOS.items():
        cv2.putText(
            frame,
            f"[{tecla}] {gesto}",
            (10, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (255, 255, 255),
            2,
        )
        y += 28

    # Separador
    y += 5
    cv2.line(frame, (10, y), (300, y), (100, 100, 100), 1)
    y += 15

    # Conteo por gesto (verde si llego a 100, amarillo si no)
    cv2.putText(
        frame, "Muestras:", (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (180, 180, 180), 1
    )
    y += 22

    for gesto, cantidad in conteo.items():
        color = (0, 255, 0) if cantidad >= 100 else (0, 200, 255)
        cv2.putText(
            frame,
            f"  {gesto}: {cantidad}",
            (10, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            color,
            1,
        )
        y += 22

    # Confirmacion de guardado (aparece abajo por unos frames)
    if ultimo_guardado:
        cv2.putText(
            frame,
            f"Guardado: {ultimo_guardado}",
            (10, frame.shape[0] - 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (0, 255, 0),
            2,
        )

    # Instruccion para salir
    cv2.putText(
        frame,
        "[q] Salir",
        (10, frame.shape[0] - 15),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (100, 100, 255),
        1,
    )


# ---------------------------------------------------------------------------
# Loop principal
# ---------------------------------------------------------------------------


def main():
    os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)

    inicializar_csv(CSV_PATH)

    # Cargamos el conteo previo por si el CSV ya tenia muestras de otra sesion
    conteo = contar_muestras(CSV_PATH)

    # Configuracion de MediaPipe — identica a landmarks.py para ser consistentes
    mp_hands = mp.solutions.hands
    hands = mp_hands.Hands(
        static_image_mode=False,
        max_num_hands=1,
        min_detection_confidence=0.5,
    )
    mp_draw = mp.solutions.drawing_utils

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("Error: no se pudo abrir la camara")
        return

    print("Camara abierta. Presiona una tecla para capturar. [q] para salir.")
    print("Muestras actuales:", conteo)

    ultimo_guardado = ""
    frames_desde_guardado = 0

    while True:
        success, frame = cap.read()
        if not success:
            print("Error leyendo frame")
            break

        # MediaPipe necesita RGB; OpenCV captura en BGR
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = hands.process(rgb)

        features = None

        if results.multi_hand_landmarks:
            hand_landmarks = results.multi_hand_landmarks[0]
            mp_draw.draw_landmarks(frame, hand_landmarks, mp_hands.HAND_CONNECTIONS)

            # La misma funcion que usara el runtime -> garantiza features identicos
            features = hand_detector.extract_features(hand_landmarks)

        dibujar_ui(frame, conteo, ultimo_guardado)

        # El mensaje de guardado se muestra ~20 frames (~0.7 segundos)
        frames_desde_guardado += 1
        if frames_desde_guardado > 20:
            ultimo_guardado = ""

        cv2.imshow("Captura de Dataset", frame)

        key = cv2.waitKey(1) & 0xFF

        if key == ord("q"):
            break

        if key != 255:
            caracter = chr(key)

            if caracter in GESTOS:
                if features is not None:
                    label = GESTOS[caracter]
                    guardar_muestra(CSV_PATH, label, features)

                    # Actualizamos en memoria para no releer el CSV cada frame
                    conteo[label] += 1
                    ultimo_guardado = label
                    frames_desde_guardado = 0

                    print(f"  [{label}] muestra #{conteo[label]} guardada")
                else:
                    print("  Sin mano detectada, muestra no guardada")

    cap.release()
    cv2.destroyAllWindows()
    hands.close()

    print("\nSesion terminada. Muestras totales:")
    for gesto, cantidad in conteo.items():
        print(f"  {gesto}: {cantidad}")


if __name__ == "__main__":
    main()
