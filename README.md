# SeeNGo — Pipeline de Reconocimiento de Gestos

Pipeline de visión por computadora que corre en una **Raspberry Pi 3**. Captura señas de la mano
con una cámara, las clasifica con un modelo de Machine Learning y publica comandos para automatizar
dispositivos del hogar (IoT) por MQTT.

```
Cámara → MediaPipe (landmarks) → Random Forest (clasifica seña)
       → resuelve acción desde caché → publica comando MQTT → registra evento en MongoDB
```

> Este módulo **solo detecta y emite comandos**. No re-entrena modelos, no expone API HTTP y no
> actúa directamente sobre los dispositivos: solo publica el comando al broker MQTT, y otro
> componente lo consume.

---

## Tabla de contenidos
1. [Conceptos clave (léelos primero)](#1-conceptos-clave)
2. [Requisitos previos](#2-requisitos-previos)
3. [Estructura del proyecto](#3-estructura-del-proyecto)
4. [Instalación y setup](#4-instalación-y-setup)
5. [Plan de desarrollo paso a paso (M0–M10)](#5-plan-de-desarrollo-paso-a-paso)
6. [Verificación end-to-end](#6-verificación-end-to-end)
7. [Despliegue en la Raspberry Pi](#7-despliegue-en-la-raspberry-pi)
8. [Glosario](#8-glosario)

---

## 1. Conceptos clave

Lee esto antes de codear; cada hito asume que entiendes estos términos.

### ¿Qué son los *landmarks* de la mano?
MediaPipe Hands detecta **21 puntos** en tu mano (puntas de dedos, nudillos, muñeca). Cada punto
tiene 3 coordenadas: `x`, `y` (posición en la imagen, 0–1) y `z` (profundidad relativa).
21 puntos × 3 = **63 números** que describen la pose de la mano en un instante.

### ¿Por qué *normalizar* esos 63 números?
Si usamos las coordenadas crudas, el modelo aprendería *dónde* está tu mano en la pantalla, no *qué
forma* tiene. Para que reconozca la seña sin importar si tu mano está arriba, abajo, cerca o lejos,
**trasladamos** todos los puntos para que la muñeca sea el origen (0,0,0) y **escalamos** por una
distancia de referencia (p. ej. muñeca → nudillo del dedo medio). Resultado: la misma seña produce
un vector parecido sin importar posición ni tamaño. Esto es lo que hace que el modelo generalice.

> ⚠️ Regla de oro: la normalización en **runtime** debe ser **idéntica** a la del **entrenamiento**.
> Por eso habrá UNA sola función `extract_features()` importada por captura, entrenamiento y runtime.

### ¿Qué es un *Random Forest* (RF)?
Un algoritmo de **clasificación supervisada**. Entrena muchos **árboles de decisión**, cada uno
sobre un subconjunto aleatorio de los datos, y predice por **votación mayoritaria** de los árboles.
- Entrada (features): los 63 valores normalizados.
- Salida (clases): un **gesto neutro** del catálogo (`palma_abierta`, `puño`, `paz`, …).
- En esta Pi solo corre `.predict()` (barato en CPU). El **entrenamiento** lo hacemos aparte (en `tools/`).

### ⭐ Gesto vs. acción (la distinción más importante del diseño)
El modelo clasifica un **vocabulario fijo y compartido de *gestos*** (formas de mano), con nombres
**neutros** que describen la forma, **no** lo que controlan. Lo que cada gesto *hace* es un **mapeo
gesto→acción** que vive en **MongoDB** (`user_signs`) y es personalizable por usuario.

| Cambio que quieres hacer | Qué tocas | ¿Re-entrenar el modelo? |
| ------------------------ | --------- | ----------------------- |
| Un gesto existente ahora controla otro aparato/acción | Mongo (`user_signs`) | **No** |
| Otro usuario usa el mismo gesto para otra cosa | Mongo (un doc por usuario) | **No** — un solo modelo para todos |
| Agregar una **forma de mano nueva** al catálogo | Capturar datos (M2) + re-entrenar (M3) → nuevo `.joblib` | **Sí**, offline y versionado |

**Por qué importa:** un Random Forest solo predice las clases con las que fue entrenado; no se le
puede añadir un gesto nuevo "en caliente". Por eso una forma de mano genuinamente nueva obliga a
re-entrenar (un evento deliberado y poco frecuente, fuera de la Pi), mientras que **cambiar el
significado** de un gesto es solo editar Mongo. Mantén el catálogo **modesto: ~5–15 gestos
visualmente distintos** (más clases = más confusión y más datos por recolectar). El **umbral de
confianza** (M4) ayuda a ignorar gestos fuera del catálogo, aunque no es infalible (el RF siempre
vota *alguna* clase conocida).

### ¿Qué es MQTT?
Un protocolo de mensajería ligero tipo "publicador/suscriptor". Nuestro pipeline **publica** un
mensaje (comando) en un *topic* (`seengo/comandos/{deviceId}`) y un **broker** (Mosquitto) lo
reparte a quien esté suscrito. Desacopla "detectar la seña" de "encender la luz".

### ¿Qué es el *caché en memoria* y por qué importa?
Al iniciar sesión leemos **una sola vez** de MongoDB el mapeo `gesto → acción` del usuario y lo
guardamos en un diccionario en RAM. Durante la operación, cada gesto se resuelve contra ese
diccionario (instantáneo, sin red). Así sacamos el I/O de red del loop y respetamos el KPI de 500 ms.
MongoDB solo se vuelve a tocar para **escribir** el evento de cada reconocimiento.

### ¿Qué es el *anti-rebote* (debounce)?
Si sostienes una seña 2 segundos, el loop la vería ~60 veces y dispararía 60 comandos. El debounce
aplica un **cooldown por seña** (p. ej. ignorar la misma seña dentro de ~1 s) para disparar **una vez**.

---

## 2. Requisitos previos

- **Python 3.10** (MediaPipe 0.10.14 lo requiere).
- Una **webcam USB** para desarrollar en Windows.
- **Docker** (para levantar Mosquitto y MongoDB localmente) — o instalaciones nativas.
- Conocimientos básicos de Python (clases, funciones, `import`).
- (Solo para el despliegue final) una **Raspberry Pi 3** con cámara **CSI**.

---

## 3. Estructura del proyecto

Estructura objetivo (la vamos creando hito por hito; hoy solo existe `app/vision/`):

```
seengo-gesture-pipeline/
├── README.md
├── CLAUDE.md                     # guía de arquitectura para Claude Code
├── config.yaml                   # broker MQTT, ref a Mongo, ruta del modelo, deviceId, umbral, cooldown
├── .env                          # SECRETOS: MONGO_URI, credenciales MQTT (git-ignored)
├── requirements.txt              # deps de runtime + dev (Windows)
├── requirements-pi.txt           # deps SOLO de la Pi: picamera2, gpiozero
├── models/
│   └── rf_signs.joblib           # modelo entrenado (lo genera tools/train_rf.py)
├── data/
│   └── landmarks.csv             # dataset: label + 63 features (lo genera tools/capture_dataset.py)
├── src/
│   ├── main.py                   # orquestador: arranca sesión y corre el loop
│   ├── config.py                 # carga config.yaml + .env
│   ├── session.py                # define el userId fijo de la sesión
│   ├── camera.py                 # abstracción de cámara: Webcam (OpenCV) | CSI (Picamera2)
│   ├── landmarks.py              # MediaPipe Hands → vector de 63 features normalizado
│   ├── classifier.py             # carga .joblib, predice seña + confianza
│   ├── debounce.py               # cooldown por seña (anti-rebote)
│   ├── action_resolver.py        # caché en memoria seña → acción
│   ├── mqtt_publisher.py         # publica comandos (+ versión Stub para dev)
│   └── event_logger.py           # escribe eventos en MongoDB (+ versión Stub)
└── tools/
    ├── capture_dataset.py        # captura landmarks etiquetados → data/landmarks.csv
    └── train_rf.py               # entrena el Random Forest → models/rf_signs.joblib
```

**Reutilización del código actual:** la lógica de `app/vision/hand_detector.py` (convertir BGR→RGB,
`hands.process()`) se mueve a `src/landmarks.py`; en vez de **dibujar** los puntos, **devuelve** los
63 features. El bucle de `app/vision/camera.py` se conserva como base de la cámara webcam.

### Contratos de datos (defínelos antes de codear)

**Lectura inicial — colección `user_signs` (Mongo)** — mapea **gestos del catálogo** → acción:
```json
{
  "userId": "migueldr12",
  "signs": [
    { "gesture": "palma_abierta", "deviceId": "shelly-sala", "action": "on"  },
    { "gesture": "puño",          "deviceId": "shelly-sala", "action": "off" }
  ]
}
```
> El `gesture` debe coincidir con una clase del modelo. Cambiar el `deviceId`/`action` de un gesto
> (o que otro usuario lo use distinto) **no requiere re-entrenar** — solo edita Mongo.

**Comando publicado — topic `seengo/comandos/{deviceId}`:**
```json
{ "deviceId": "shelly-sala", "action": "on", "userId": "migueldr12", "ts": "2026-06-26T10:00:00Z" }
```

**Evento escrito — colección `sign_events` (Mongo):**
```json
{ "userId": "migueldr12", "gesture": "palma_abierta", "confidence": 0.94, "deviceId": "shelly-sala", "action": "on", "ts": "2026-06-26T10:00:00Z" }
```

---

## 4. Instalación y setup

### Dev (Windows + webcam USB)

```powershell
# 1. Clonar y entrar
git clone <repo>
cd seengo-gesture-pipeline

# 2. Crear y activar entorno virtual (Python 3.10)
python -m venv env
env\Scripts\Activate.ps1

# 3. Instalar dependencias
pip install -r requirements.txt
```

Levantar infraestructura local con Docker (a partir del hito M7):
```powershell
# Broker MQTT
docker run -d --name mosquitto -p 1883:1883 eclipse-mosquitto

# MongoDB
docker run -d --name mongo -p 27017:27017 mongo
```

> En dev usa `skip_frames: 1` en `config.yaml` para procesar todos los frames
> (la PC tiene CPU de sobra). En la Pi cambia a `2` o `3`.

### Producción (Raspberry Pi 3)

Todo corre en la misma Pi 3:

```
Raspberry Pi 3
├── SeeNGo pipeline      ← este repo
├── Mosquitto            ← broker MQTT (add-on de Home Assistant)
└── Home Assistant       ← controla los dispositivos WiFi
```

**MongoDB** corre en la nube usando el free tier de **MongoDB Atlas** (512 MB gratuitos)
para no saturar la RAM de la Pi 3.

**Acceso remoto desde app móvil:**
- **Nabu Casa** ($6.50/mes) — servicio oficial de Home Assistant, da acceso remoto sin abrir puertos
- **Cloudflare Tunnel** (gratis) — alternativa self-hosted

**Instalar Home Assistant OS en la Pi 3:**
1. Descarga la imagen de [Home Assistant OS para Pi 3](https://www.home-assistant.io/installation/raspberrypi)
2. Grábala en la microSD con Raspberry Pi Imager
3. Arranca la Pi y entra a `http://homeassistant.local:8123`
4. En Home Assistant → **Settings → Add-ons → Mosquitto broker** (instala el add-on oficial)
5. Configura las credenciales MQTT en el add-on y actualiza tu `.env`

**Instalar SeeNGo en la Pi 3** (una vez que Home Assistant OS esté corriendo):
```bash
# Home Assistant OS no tiene Python nativo — usa el add-on "Terminal & SSH"
# o instala en un contenedor Docker separado
pip install -r requirements.txt
pip install -r requirements-pi.txt
```

`requirements.txt` (runtime compartido Windows + Pi):
```
opencv-python
mediapipe==0.10.14
numpy
scikit-learn
joblib
paho-mqtt
pymongo
pyyaml
pydantic
python-dotenv
```

`requirements-pi.txt` (solo en la Pi):
```
picamera2
```

---

## 5. Plan de desarrollo paso a paso

> **Cómo usar esta sección:** cada hito (M) es una pieza pequeña, aislada y **verificable por sí
> sola**. Hazlo **tú primero** para entenderlo; donde veas 🤖 es donde tiene más sentido que yo
> (Claude) te acelere generando el archivo y revisándolo juntos. **No pases al siguiente hito hasta
> que el "✅ Verifica" del actual funcione.**

### M0 — Setup y esqueleto
**Objetivo:** dejar la estructura lista y el video corriendo (todavía sin clasificar).
**Pasos:**
1. Actualiza `requirements.txt` y crea `requirements-pi.txt` (ver sección 4).
2. Crea las carpetas `src/`, `tools/`, `models/`, `data/`.
3. Crea `config.yaml` (broker, deviceId, umbral de confianza, cooldown, ruta del modelo) y `.env`
   (`MONGO_URI`, credenciales MQTT). Asegúrate de que `.env` esté en `.gitignore`.
4. Crea `src/config.py` que cargue ambos y los valide con pydantic.
5. Mueve la lógica de `app/vision/` a `src/camera.py` y `src/landmarks.py`.

**✅ Verifica:** `python src/main.py` abre la webcam y muestra el video. Presiona `q` para salir.
🤖 Buen candidato para que yo arme el esqueleto y `config.py`.

### M1 — Landmarks → 63 features normalizados  *(el corazón del sistema)*
**Objetivo:** convertir la mano detectada en un vector estable de 63 números.
**Pasos:**
1. En `src/landmarks.py`, configura MediaPipe Hands con `static_image_mode=False` (video) y
   `max_num_hands=1` (una seña = una mano).
2. Escribe **una** función `extract_features(hand_landmarks) -> np.ndarray (63,)` que:
   - tome los 21 puntos `(x, y, z)`,
   - **traslade** todos restando la muñeca (landmark 0) → la muñeca queda en el origen,
   - **escale** dividiendo por una distancia de referencia (p. ej. muñeca → nudillo del dedo medio,
     landmark 9) para invarianza a tamaño,
   - aplane a un vector de 63 floats.
3. Dibuja en pantalla el vector (o solo los primeros valores) en vivo, para inspeccionarlo.

**✅ Verifica:** mueve y acerca/aleja la mano; el vector de una misma seña debe mantenerse parecido.
*Concepto a dominar:* por qué normalizar (sección 1). **Hazlo tú** — es la pieza más importante.

### M2 — Captura de dataset etiquetado
**Objetivo:** generar los datos para entrenar el modelo.
**Pasos:**
1. En `tools/capture_dataset.py`, abre la cámara y reusa `extract_features()`.
2. Define los **gestos** con nombres neutros (p. ej. teclas: `1`=`palma_abierta`, `2`=`puño`, …).
   Al presionar una tecla, guarda una fila `label,f0,f1,...,f62` en `data/landmarks.csv`.
3. Captura **~100–200 muestras por gesto**, variando un poco la posición/orientación de la mano.

**✅ Verifica:** abre `data/landmarks.csv` y confirma que cada clase tiene un número similar de filas
(dataset balanceado). Empieza con 3–4 gestos bien distintos entre sí.

### M3 — Entrenamiento del Random Forest
**Objetivo:** producir `models/rf_signs.joblib`.
**Pasos:**
1. En `tools/train_rf.py`: carga el CSV, separa `X` (63 columnas) e `y` (label).
2. `train_test_split` (p. ej. 80/20), entrena `RandomForestClassifier(n_estimators=100)`.
3. Imprime **accuracy** y la **matriz de confusión** sobre el set de prueba.
4. Guarda el modelo con `joblib.dump(modelo, "models/rf_signs.joblib")`.

**✅ Verifica:** accuracy alta (>90% con señas distintas). Si dos señas se confunden, captura más
datos de ellas (M2). *Concepto a dominar:* qué dice la matriz de confusión. **Hazlo tú.**

### M4 — Clasificador en runtime
**Objetivo:** predecir la seña en vivo, con confianza.
**Pasos:**
1. En `src/classifier.py`, carga el `.joblib` una vez.
2. Expón `predict(features) -> (sign, confidence)` usando `predict_proba()` (la confianza es la
   probabilidad máxima entre las clases).
3. Aplica el **umbral de confianza** desde `config.yaml`: si la confianza es menor, ignora.
4. Integra en el loop y muestra en pantalla `seña + confianza`.

**✅ Verifica:** haz cada seña entrenada y confirma que el texto en pantalla es correcto.

### M5 — Anti-rebote (debounce)
**Objetivo:** disparar una sola vez por seña sostenida.
**Pasos:**
1. En `src/debounce.py`, guarda el timestamp del último disparo por seña.
2. `should_fire(sign) -> bool`: True solo si pasó el `cooldown` (de config, ~1 s) desde el último.

**✅ Verifica:** sostén una seña; debe registrarse **una sola vez**, no muchas por segundo.

### M6 — Resolución de acción + caché en memoria
**Objetivo:** traducir seña → `{deviceId, action}` sin tocar la red.
**Pasos:**
1. En `src/action_resolver.py`, construye un dict `{gesture: {deviceId, action}}`.
2. **Por ahora** cárgalo de un JSON local (stub) con la forma de `user_signs` (sección 3).
3. `resolve(gesture) -> {deviceId, action}` en O(1).

**✅ Verifica:** un gesto reconocido imprime su `deviceId` y `action` resueltos.

### M7 — Publicación MQTT (primero stub, luego real)
**Objetivo:** emitir el comando al broker.
**Pasos:**
1. En `src/mqtt_publisher.py`, define una interfaz `Publisher.publish(command)`.
2. `StubPublisher`: solo imprime el comando (para desarrollar sin broker).
3. `MqttPublisher` (paho-mqtt): publica el payload de la sección 3 en `seengo/comandos/{deviceId}`.

**✅ Verifica:** con `StubPublisher` ves el comando en consola. Luego levanta Mosquitto (sección 4)
y en otra terminal: `mosquitto_sub -t "seengo/comandos/#"` → debes ver el mensaje real.

### M8 — Registro de eventos en MongoDB (stub → real)
**Objetivo:** telemetría de cada reconocimiento, sin tumbar el loop.
**Pasos:**
1. En `src/event_logger.py`: `StubLogger` (imprime) + `MongoLogger` (pymongo) que inserta el evento
   de la sección 3 en la colección `sign_events`.
2. **Tolerante a fallos:** envuelve la escritura en `try/except`; si Mongo no responde, loguea y
   continúa (el loop **nunca** se cae por Mongo).
3. Cambia `action_resolver` (M6) para que lea `user_signs` **real** de Mongo al inicio de sesión.

**✅ Verifica:** levanta MongoDB, reconoce una seña y consulta `sign_events` (debe haber un documento).

### M9 — Sesión + orquestación final (`main.py`)
**Objetivo:** unir todo según el flujo de ejecución.
**Pasos (orden del loop):**
1. `src/session.py`: recibe el `userId` por argumento CLI (`--user migueldr12`) o `config.yaml`.
2. `src/main.py`: carga config → carga modelo → lee `user_signs` y arma el caché → entra al loop:
   - capturar frame → extraer landmarks (si no hay mano, continuar)
   - `classifier.predict()` → seña + confianza
   - si confianza ≥ umbral **y** `debounce.should_fire()` → `action_resolver.resolve()`
   - `mqtt_publisher.publish()` y `event_logger.log()`

**✅ Verifica:** end-to-end (ver sección 6).

### M10 — Despliegue en la Raspberry Pi  *(fuera del loop de dev en Windows)*
**Objetivo:** correr el mismo código en hardware real.
**Pasos:**
1. Implementa `CSICamera` (Picamera2) tras la **misma** interfaz de cámara que `WebcamCamera`.
2. Instala `requirements-pi.txt` en la Pi.
3. Configura la cámara en `/boot/firmware/config.txt`: `camera_auto_detect=0` y `dtoverlay=imx219`.

**✅ Verifica:** el mismo `main.py` corre en la Pi cambiando solo la implementación de cámara.

---

## 6. Verificación end-to-end

Al terminar M9, con la webcam en Windows:

1. Levanta infra: Mosquitto + MongoDB (sección 4).
2. En una terminal, suscríbete: `mosquitto_sub -t "seengo/comandos/#"`.
3. Corre el pipeline: `python src/main.py --user migueldr12`.
4. Haz una seña entrenada y confirma las **tres** cosas:
   - aparece el comando JSON en `mosquitto_sub`,
   - hay un documento nuevo en la colección `sign_events` de Mongo,
   - sostener la seña **no** dispara comandos repetidos (debounce funciona).

---

## 7. Despliegue en la Raspberry Pi

### Configurar la cámara CSI

Cámara Freenove IMX219 (clon). En `/boot/firmware/config.txt` añade y reinicia:
```
camera_auto_detect=0
dtoverlay=imx219
```

### Optimizaciones de carga para Pi 3

La Pi 3 tiene 1 GB de RAM y 4 núcleos ARM Cortex-A53 a 1.2 GHz. MediaPipe + Home Assistant
juntos pueden saturarla. Aplica estas optimizaciones (ya implementadas en el código):

| Optimización | Dónde | Impacto |
|---|---|---|
| `skip_frames: 2` en `config.yaml` | `config.yaml` → `inference` | Inferencia cada 2 frames; el video sigue fluido |
| Resolución 640×480 | `config.yaml` → `camera` | No subir; más resolución = más CPU en MediaPipe |
| `max_num_hands=1` en MediaPipe | `src/landmarks.py` | Solo rastrear una mano reduce carga |
| MongoDB en Atlas (nube) | `.env` → `MONGO_URI` | Saca las escrituras de la RAM local |

**`skip_frames` explicado:** el pipeline lee cada frame de la cámara pero solo corre
MediaPipe + Random Forest en 1 de cada N frames. Los frames omitidos se muestran en pantalla
igualmente (video fluido) pero no consumen CPU de inferencia. Con `skip_frames: 2` reduces
la carga de inferencia a la mitad; con `3`, a un tercio.

Para domótica esto es suficiente — no necesitas clasificar a 30 FPS para detectar una seña sostenida.

### MongoDB Atlas (nube gratuita)

1. Crea cuenta en [mongodb.com/cloud/atlas](https://www.mongodb.com/cloud/atlas)
2. Crea un cluster gratuito (M0, 512 MB)
3. Crea usuario de base de datos y copia el URI de conexión
4. En tu `.env` en la Pi: `MONGO_URI=mongodb+srv://usuario:password@cluster.mongodb.net/`
5. En Atlas → Network Access → añade la IP de la Pi (o `0.0.0.0/0` para desarrollo)

### Autoarranque del pipeline al encender la Pi

Crea el archivo `/etc/systemd/system/seengo.service`:
```ini
[Unit]
Description=SeeNGo Gesture Pipeline
After=network.target

[Service]
User=pi
WorkingDirectory=/home/pi/seengo-gesture-pipeline
ExecStart=/home/pi/seengo-gesture-pipeline/env/bin/python main.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Actívalo:
```bash
sudo systemctl enable seengo
sudo systemctl start seengo
```

---

## 8. Glosario

| Término          | Significado breve                                                                 |
| ---------------- | --------------------------------------------------------------------------------- |
| Landmark         | Uno de los 21 puntos `(x,y,z)` que MediaPipe detecta en la mano.                  |
| Feature vector   | Los 63 números (21×3) normalizados que entran al modelo.                          |
| Random Forest    | Clasificador de muchos árboles de decisión que votan la predicción.              |
| `.joblib`        | Archivo binario donde se guarda el modelo entrenado.                              |
| `predict_proba`  | Devuelve la probabilidad por clase; su máximo es nuestra "confianza".            |
| MQTT             | Protocolo publish/subscribe; publicamos comandos en un *topic*.                  |
| Broker (Mosquitto)| Servidor MQTT que reparte los mensajes a los suscriptores.                       |
| Topic            | "Canal" MQTT, aquí `seengo/comandos/{deviceId}`.                                  |
| Debounce         | Cooldown para no disparar una seña sostenida muchas veces.                        |
| Caché en memoria | Mapeo gesto→acción leído de Mongo **una vez** por sesión y guardado en RAM.      |
| Gesto vs. acción | El *gesto* (forma de mano) es clase fija del modelo; la *acción* es el mapeo en Mongo, editable sin re-entrenar. |
