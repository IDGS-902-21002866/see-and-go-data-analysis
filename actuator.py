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
import socket
import time

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
        # Conexion DIRECTA por TCP al puerto 9999 (sin discovery UDP):
        # el discovery se pierde facil en WiFi; TCP es confiable
        try:
            from kasa.iot import IotBulb  # python-kasa >= 0.6
        except ImportError:
            from kasa import SmartBulb as IotBulb  # versiones anteriores

        dev = IotBulb(device_cfg["host"])
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
    """Control LOCAL de dispositivos Tuya (Smart Life) con tinytuya.

    Requiere en el registro: tuya_id, local_key y version (los da
    `python -m tinytuya wizard` tras vincular la cuenta en iot.tuya.com).
    tinytuya es sincrono → lo corremos en un hilo para no bloquear el loop.
    """
    import tinytuya

    def _run():
        d = tinytuya.OutletDevice(
            device_cfg["tuya_id"], device_cfg["host"], device_cfg["local_key"]
        )
        d.set_version(float(device_cfg.get("version", 3.3)))
        d.set_socketTimeout(5)

        if action == "on":
            resultado = d.turn_on()
        elif action == "off":
            resultado = d.turn_off()
        elif action == "toggle":
            estado = d.status()
            if "Error" in estado:
                raise ConnectionError(f"tuya status: {estado}")
            # dps '1' es el switch principal en enchufes Tuya
            encendido = bool(estado.get("dps", {}).get("1"))
            resultado = d.turn_off() if encendido else d.turn_on()
        else:
            raise ValueError(f"Accion desconocida: {action}")

        if isinstance(resultado, dict) and "Error" in resultado:
            raise ConnectionError(f"tuya: {resultado}")

    await asyncio.to_thread(_run)


def _cozylife_request(host: str, payload: dict, timeout: float = 5) -> dict:
    """Manda un mensaje JSON al puerto 5555 y devuelve la respuesta parseada.

    Protocolo local CozyLife: JSON + \r\n sobre TCP. cmd 0 = info,
    cmd 2 = consultar estado, cmd 3 = controlar. attr 1 = switch principal.
    """
    s = socket.create_connection((host, 5555), timeout=timeout)
    try:
        s.sendall((json.dumps(payload) + "\r\n").encode())
        s.settimeout(timeout)
        data = b""
        while b"\n" not in data:
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
        return json.loads(data.decode())
    finally:
        s.close()


async def _driver_cozylife(device_id: str, device_cfg: dict, action: str):
    """Control local del Smart Socket XLD01 (app CozyLife) sin nube ni claves."""
    host = device_cfg["host"]

    def _run():
        sn = str(int(time.time() * 1000))

        if action == "toggle":
            estado = _cozylife_request(
                host, {"cmd": 2, "pv": 0, "sn": sn, "msg": {"attr": [1]}}
            )
            encendido = bool(estado.get("msg", {}).get("data", {}).get("1"))
            valor = 0 if encendido else 255
        elif action == "on":
            valor = 255
        elif action == "off":
            valor = 0
        else:
            raise ValueError(f"Accion desconocida: {action}")

        resp = _cozylife_request(
            host, {"cmd": 3, "pv": 0, "sn": sn, "msg": {"attr": [1], "data": {"1": valor}}}
        )

        # Algunos firmware esperan 1 en vez de 255 para encender
        if resp.get("res") != 0 and valor == 255:
            resp = _cozylife_request(
                host, {"cmd": 3, "pv": 0, "sn": sn, "msg": {"attr": [1], "data": {"1": 1}}}
            )

        if resp.get("res") != 0:
            raise ConnectionError(f"cozylife respondio res={resp.get('res')}")

    await asyncio.to_thread(_run)


DRIVERS = {
    "kasa": _driver_kasa,
    "tuya": _driver_tuya,
    "cozylife": _driver_cozylife,
}


# -----------------------------------------------------------------
# Auto-recuperacion por MAC: la MAC es la identidad permanente del
# aparato; la IP es solo un cache que se refresca solo si cambia.
# -----------------------------------------------------------------


def _normalizar_mac(mac: str) -> str:
    return (mac or "").lower().replace("-", ":")


async def _rediscover_by_mac(device_id: str, device_cfg: dict) -> str | None:
    """Barre la subred con discovery DIRIGIDO buscando la MAC del dispositivo.

    Dirigido IP por IP (no broadcast), asi funciona aunque el router lo
    bloquee. Devuelve la nueva IP, o None si no aparecio en la red.
    """
    mac_objetivo = _normalizar_mac(device_cfg.get("mac"))
    if not mac_objetivo:
        print(f"[actuador] {device_id} no tiene MAC registrada; no puedo re-descubrir")
        return None

    # Subred /24 a partir de la ultima IP conocida: "192.168.1.14" → "192.168.1"
    base = device_cfg["host"].rsplit(".", 1)[0]
    print(f"[actuador] Buscando {device_id} (MAC {mac_objetivo}) en {base}.0/24 ...")

    # Maximo 50 sondeos simultaneos para no saturar la Pi
    sem = asyncio.Semaphore(50)

    async def sondear(ip: str) -> str | None:
        async with sem:
            try:
                dev = await Discover.discover_single(ip, timeout=2)
                if _normalizar_mac(dev.mac) == mac_objetivo:
                    return ip
            except Exception:
                pass  # IP sin dispositivo kasa: silencio y seguimos
            return None

    resultados = await asyncio.gather(*[sondear(f"{base}.{i}") for i in range(1, 255)])
    for ip in resultados:
        if ip is not None:
            return ip
    return None


# Handle a la coleccion user_devices (se asigna en main si Mongo respondio);
# permite persistir la IP nueva para que sobreviva reinicios del actuador
_devices_collection = None


def _update_host_in_mongo(device_id: str, host: str) -> None:
    if _devices_collection is None:
        return
    try:
        _devices_collection.update_one({"deviceId": device_id}, {"$set": {"host": host}})
        print(f"[actuador] Registro actualizado en Mongo: {device_id} → {host}")
    except Exception as e:
        print(f"[actuador] No se pudo actualizar host en Mongo: {e}")


async def ejecutar(device_id: str, device_cfg: dict, action: str):
    tipo = device_cfg.get("type")
    driver = DRIVERS.get(tipo)

    if driver is None:
        print(f"[actuador] Tipo '{tipo}' sin driver ({device_id})")
        return

    try:
        await driver(device_id, device_cfg, action)
        print(f"[actuador] {device_id} → {action} OK")
        return
    except Exception as e:
        # Si el aparato cambio de IP o se desconecto, olvidamos el cache
        # para forzar un re-descubrimiento en el siguiente comando
        _kasa_cache.pop(device_id, None)
        print(f"[actuador] Error con {device_id}: {e}")

    # Auto-recuperacion: quiza la IP cambio. Buscamos el aparato por su MAC
    # (solo kasa por ahora; el barrido usa el discovery de python-kasa)
    if tipo != "kasa":
        return

    nueva_ip = await _rediscover_by_mac(device_id, device_cfg)
    if nueva_ip is None:
        print(f"[actuador] {device_id} no encontrado en la red")
        return

    print(f"[actuador] {device_id} reapareció en {nueva_ip}")

    # Actualizamos el registro en memoria (device_cfg es el dict compartido)
    # y lo persistimos en Mongo para que sobreviva reinicios
    device_cfg["host"] = nueva_ip
    _update_host_in_mongo(device_id, nueva_ip)

    # Reintentamos el comando una vez con la IP nueva
    try:
        await driver(device_id, device_cfg, action)
        print(f"[actuador] {device_id} → {action} OK (tras re-descubrir)")
    except Exception as e:
        print(f"[actuador] Sigue fallando {device_id}: {e}")


# -----------------------------------------------------------------
# Registro de dispositivos: Mongo primero, config.yaml como fallback
# -----------------------------------------------------------------


def load_devices_from_mongo(uri: str, database: str, collection: str) -> dict | None:
    """Lee user_devices y devuelve {deviceId: doc}, o None si Mongo falla."""
    global _devices_collection
    try:
        client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        col = client[database][collection]
        docs = list(col.find({}))
        if not docs:
            print("[actuador] user_devices vacio en Mongo")
            return None
        # Guardamos el handle para poder persistir IPs re-descubiertas
        _devices_collection = col
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
