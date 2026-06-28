import sys
import os

import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import (
    ConfusionMatrixDisplay,
    classification_report,
)
import matplotlib.pyplot as plt
import joblib

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

df = pd.read_csv("data/landmarks.csv")

x = df.drop("label", axis=1)
y = df["label"]

x_train, x_test, y_train, y_test = train_test_split(
    x, y, test_size=0.3, random_state=42
)

#  Se establece el modelo con 100 arboles, es el valor inicial, va a ir cambiando dependiendo de la performance del modelo, si es necesario se puede aumentar a 200 o 300 arboles, pero eso va a hacer que el entrenamiento sea mas lento.
modelo = RandomForestClassifier(n_estimators=100, random_state=42)
modelo.fit(x_train, y_train)
# Hacemos las predicciones de y con base a las pruebas de x
y_pred = modelo.predict(x_test)

# Mostamos el reporte de clasificacion, que nos da la precision, recall y f1-score de cada clase
print(classification_report(y_test, y_pred))

# Graficamos la matriz de confusion
ConfusionMatrixDisplay.from_predictions(y_test, y_pred)
plt.title("Matriz de Confusion")
plt.show()

joblib.dump(modelo, "models/rf_signs.joblib")
