import os

import joblib
import numpy as np


class Classifier:

    def __init__(self, umbral: float):
        # Cargamos el modelo entrenado desde el archivo .joblib
        self.model = joblib.load("models/rf_signs.joblib")
        self.umbral = umbral

    def predict(self, features):

        probas = self.model.predict_proba([features])

        # Obtenemo la confianza
        confidence = np.max(probas[0])

        # Obtenemos el indice de la clase con mayor probabilidad
        class_index = np.argmax(probas[0])

        # Guardamos las clases del modelo para poder acceder a ellas desde fuera de la clase
        self.model.classes_

        # Obtenemos la clase con mayor probabilidad
        predicted_class = self.model.classes_[class_index]

        # Verificamos si la confianza supera el umbral
        if confidence < self.umbral:
            return None, confidence

        return predicted_class, confidence
