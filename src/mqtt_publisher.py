import json

import paho.mqtt.client as mqtt


class Publisher:
    """Interfaz base: cualquier publisher debe implementar publish(command)."""

    def publish(self, command: dict) -> None:
        raise NotImplementedError


class StubPublisher(Publisher):
    """Publisher falso para desarrollo: solo imprime el comando en consola."""

    def publish(self, command: dict) -> None:
        print(f"[STUB MQTT] {json.dumps(command, ensure_ascii=False)}")


class MqttPublisher(Publisher):
    """Publisher real: publica comandos al broker Mosquitto con paho-mqtt."""

    def __init__(self, host: str, port: int, topic_prefix: str, user: str = "", password: str = ""):
        self.topic_prefix = topic_prefix

        # paho-mqtt 2.x cambio la firma del constructor; esto soporta ambas versiones
        try:
            self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)
        except AttributeError:
            self.client = mqtt.Client()

        if user:
            self.client.username_pw_set(user, password)

        self.client.connect(host, port)

        # loop_start corre un hilo en segundo plano que mantiene la conexion
        # viva y reconecta solo si el broker se cae
        self.client.loop_start()

    def publish(self, command: dict) -> None:
        # Topic final: seengo/comandos/{deviceId}
        topic = f"{self.topic_prefix}/{command['deviceId']}"
        payload = json.dumps(command, ensure_ascii=False)

        # El publish nunca debe tumbar el loop de inferencia
        try:
            self.client.publish(topic, payload)
        except Exception as e:
            print(f"[MQTT] Error publicando: {e}")

    def stop(self) -> None:
        self.client.loop_stop()
        self.client.disconnect()
