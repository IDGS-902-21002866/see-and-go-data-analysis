import cv2
import mediapipe as mp
import numpy as np


class HandDetector:

    def __init__(self):
        self.mp_hands = mp.solutions.hands

        # static_image_mode=False -> optimizado para video en tiempo real
        # (True seria para fotos sueltas; False reutiliza la deteccion del frame anterior)
        #
        # max_num_hands=1 -> solo necesitamos una mano para clasificar gestos
        self.hands = self.mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=1,
            min_detection_confidence=0.5,
        )

        self.mp_draw = mp.solutions.drawing_utils

    def detect(self, frame):
        # OpenCV usa BGR, MediaPipe necesita RGB
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self.hands.process(rgb_frame)

        features = None

        if results.multi_hand_landmarks:
            # Como max_num_hands=1, solo habra un elemento en la lista
            hand_landmarks = results.multi_hand_landmarks[0]

            # Dibujamos los puntos y conexiones sobre el frame
            self.mp_draw.draw_landmarks(
                frame,
                hand_landmarks,
                self.mp_hands.HAND_CONNECTIONS,
            )

            # Extraemos el vector de 63 features normalizado
            features = self.extract_features(hand_landmarks)

            # Mostramos los primeros 6 valores en pantalla para inspeccionar
            # (si el vector es estable al mover la mano, la normalizacion esta bien)
            preview = "  ".join(f"{v:.2f}" for v in features[:6])
            cv2.putText(
                frame, preview, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2
            )

        return frame, features

    """
    Author: mduran
    Descripcion: Convierte los 21 landmarks de MediaPipe en un vector de 63 floats normalizado, esto lo hace por medio de una normalizacion que consiste en dos pasos, traslacion y escala. 
        Traslacion: restamos la muñeca (punto 0) a todos los puntos, de esta manera la muñeca queda en el origen (0, 0, 0)
        Escala: dividimos por la distancia muñeca->nudillo dedo medio (punto 9), de esta manera se logra invarianza al tamaño / distancia de la camara.
        Esta funcion es la UNICA fuente de normalizacion del sistema.
        Capture_dataset.py y train_rf.py la importan para garantizar que
        el modelo reciba exactamente los mismos features en entrenamiento y runtime.
    Date: 2026-06-27
    """

    def extract_features(self, hand_landmarks) -> np.ndarray:

        # Extraemos los 21 puntos como array numpy de forma (21, 3)
        puntos = np.array(
            [[lm.x, lm.y, lm.z] for lm in hand_landmarks.landmark],
            dtype=np.float32,
        )

        # Paso 1: traslacion — la muñeca (punto 0) se convierte en el origen
        muñeca = puntos[0]

        # Esta resta funcion porque numpy hace broadcasting: resta el vector muñeca a cada fila de puntos
        puntos = puntos - muñeca

        # Paso 2: escala — calculamos la distancia entre muñeca y nudillo del dedo medio (punto 9)

        # np.linalg.norm calcula la distancia euclidiana: sqrt(x^2 + y^2 + z^2)
        distancia_ref = np.linalg.norm(puntos[9])

        # Evitamos division por cero en el caso (muy raro) de que los puntos coincidan
        if distancia_ref > 0:
            puntos = puntos / distancia_ref

        # Aplanamos de (21, 3) a (63,) — un vector de 63 numeros
        return puntos.flatten()
