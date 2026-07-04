"""Actuador SeeNGo: consume comandos MQTT y controla los dispositivos fisicos.

Es el "otro componente" de la arquitectura (CLAUDE.md §8): el pipeline solo
publica comandos; este servicio se suscribe a seengo/comandos/# y ejecuta la
accion sobre el aparato real.

Escalabilidad:
- El registro de dispositivos vive en Mongo (user_devices); config.yaml es
  solo el fallback sin red. La futura app/API dara de alta dispositivos
  editando Mongo, sin tocar este codigo.
- Patron de drivers: agregar una marca nueva = una funcion async + una
  entrada en DRIVERS. Nada mas.

Corre como proceso separado en la Pi:
    python actuator.py
"""

import asyncio
import json
import os

import paho.mqtt.client as mqtt
import yaml
from dotenv import load_dotenv
from kasa import Discover
from pymongo import MongoClient

load_dotenv()

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.yaml")

# -----------------------------------------------------------------
# Drivers: una funcion async por tipo de dispositivo.
# Firma: driver(device_id, device_cfg, action)
# -----------------------------------------------------------------

# Cache de dispositivos kasa ya descubiertos: deviceId → objeto kasa.
# Evita re-descubrir el foco en cada comando (el discover tarda ~1 s).
_kasa_cache = {}


async def _driver_kasa(device_id: str, device_cfg: dict, action: str):
    dev = _kasa_cache.get(device_id)
    if dev is None:
        # discover_single es DIRIGIDO a la IP (no broadcast): funciona
        # aunque el router bloquee el discovery general
        dev = await Discover.discover_single(device_cfg["host"], timeout=5)
        _kasa_cache[device_id] = dev

    # update() refresca el estado real (is_on) antes de actuar
    await dev.update()

    if action == "on":
        await dev.turn_on()
    elif action == "off":
        await dev.turn_off()
    elif action == "toggle":
        if dev.is_on:
            await dev.turn_off()
        else:
            await dev.turn_on()
    else:
        raise ValueError(f"Accion desconocida: {action}")


async def _driver_tuya(device_id: str, device_cfg: dict, action: str):
    # Pendiente (Fase 2): requiere device_id + local_key de tinytuya wizard
    raise NotImplementedError("Driver tuya pendiente — Fase 2")


DRIVERS = {
    "kasa": _driver_kasa,
    "tuya": _driver_tuya,
}


async def ejecutar(device_id: str, device_cfg: dict, action: str):
    tipo = device_cfg.get("type")
    driver = DRIVERS.get(tipo)

    if driver is None:
        print(f"[actuador] Tipo '{tipo}' sin driver ({device_id})")
        return

    try:
        await driver(device_id, device_cfg, action)
        print(f"[actuador] {device_id} → {action} OK")
    except Exception as e:
        # Si el aparato cambio de IP o se desconecto, olvidamos el cache
        # para forzar un re-descubrimiento en el siguiente comando
        _kasa_cache.pop(device_id, None)
        print(f"[actuador] Error con {device_id}: {e}")


# -----------------------------------------------------------------
# Registro de dispositivos: Mongo primero, config.yaml como fallback
# -----------------------------------------------------------------


def load_devices_from_mongo(uri: str, database: str, collection: str) -> dict | None:
    """Lee user_devices y devuelve {deviceId: doc}, o None si Mongo falla."""
    try:
        client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        docs = list(client[database][collection].find({}))
        if not docs:
            print("[actuador] user_devices vacio en Mongo")
            return None
        return {d["deviceId"]: d for d in docs}
    except Exception as e:
        print(f"[actuador] No se pudo leer user_devices: {e}")
        return None


def main():
    with open(CONFIG_PATH, "r") as f:
        raw = yaml.safe_load(f)

    mqtt_cfg = raw["mqtt"]
    mongo_cfg = raw["mongo"]
    uri = os.getenv("MONGO_URI", "mongodb://localhost:27017")

    # Registro de dispositivos: una sola lectura al arrancar (como user_signs)
    devices = load_devices_from_mongo(
        uri, mongo_cfg["database"], mongo_cfg.get("collection_devices", "user_devices")
    )
    if devices is not None:
        print(f"[actuador] Registro: MongoDB ({len(devices)} dispositivos)")
    else:
        devices = raw.get("devices", {})
        print(f"[actuador] Registro: config.yaml ({len(devices)} dispositivos) — Mongo no disponible")

    if not devices:
        print("[actuador] Sin dispositivos configurados; nada que hacer")
        return

    # Loop de asyncio en el hilo principal; paho corre en su propio hilo
    # y le manda las corrutinas con run_coroutine_threadsafe
    loop = asyncio.new_event_loop()

    def on_message(client, userdata, msg):
        try:
            comando = json.loads(msg.payload)
        except json.JSONDecodeError:
            print(f"[actuador] Payload invalido en {msg.topic}")
            return

        device_id = comando.get("deviceId")
        action = comando.get("action")

        device_cfg = devices.get(device_id)
        if device_cfg is None:
            print(f"[actuador] deviceId sin registrar: {device_id}")
            return

        print(f"[actuador] Comando recibido: {device_id} / {action}")
        asyncio.run_coroutine_threadsafe(ejecutar(device_id, device_cfg, action), loop)

    # paho-mqtt 2.x cambio la firma del constructor; soportamos ambas
    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)
    except AttributeError:
        client = mqtt.Client()

    user = os.getenv("MQTT_USER", "")
    if user:
        client.username_pw_set(user, os.getenv("MQTT_PASSWORD", ""))

    client.on_message = on_message
    client.connect(mqtt_cfg["host"], mqtt_cfg["port"])
    client.subscribe(f"{mqtt_cfg['topic_prefix']}/#")
    client.loop_start()

    print(f"[actuador] Escuchando {mqtt_cfg['topic_prefix']}/# — dispositivos: {list(devices)}")

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        print("\n[actuador] Deteniendo...")
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
