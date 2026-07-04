from src.action_resolver import ActionResolver
from src.debounce import Debouncer
from src.camera import Camera
from src.config import load_config
from src.classifier import Classifier
from src.mqtt_publisher import StubPublisher, MqttPublisher
from src.event_logger import StubLogger, MongoLogger

import warnings

warnings.filterwarnings("ignore", category=UserWarning, module="google.protobuf")
warnings.filterwarnings("ignore", category=UserWarning, module="sklearn")


def main():
    config = load_config()

    print(f"Broker MQTT : {config.mqtt.host}:{config.mqtt.port}")
    print(f"MongoDB     : {config.mongo.uri}")
    print(f"Usuario     : {config.session.user_id}")
    print(f"Umbral      : {config.inference.confidence_threshold}")
    print()

    classifier = Classifier(umbral=config.inference.confidence_threshold)

    debouncer = Debouncer(cooldown=config.inference.cooldown_seconds)

    # Cargamos el mapeo gesto→accion: primero Mongo, si falla el stub JSON.
    # Es UNA sola lectura al inicio de sesion (el loop nunca toca la red).
    signs = ActionResolver.load_signs_from_mongo(
        uri=config.mongo.uri,
        database=config.mongo.database,
        collection=config.mongo.collection_signs,
        user_id=config.session.user_id,
    )
    if signs is not None:
        print(f"Mapeo       : MongoDB ({len(signs)} gestos)")
    else:
        signs = ActionResolver.load_signs_from_stub()
        print(f"Mapeo       : stub JSON local ({len(signs)} gestos) — Mongo no disponible")

    action_resolver = ActionResolver(signs)

    # Elegimos el logger de eventos: stub (imprime) o mongo (Atlas)
    if config.mongo.logger == "mongo":
        event_logger = MongoLogger(
            uri=config.mongo.uri,
            database=config.mongo.database,
            collection=config.mongo.collection_events,
        )
        print("Logger      : MongoDB real")
    else:
        event_logger = StubLogger()
        print("Logger      : Stub (solo consola)")

    # Elegimos el publisher segun config: stub (imprime) o mqtt (broker real)
    if config.mqtt.publisher == "mqtt":
        publisher = MqttPublisher(
            host=config.mqtt.host,
            port=config.mqtt.port,
            topic_prefix=config.mqtt.topic_prefix,
            user=config.mqtt.user,
            password=config.mqtt.password,
        )
        print(f"Publisher   : MQTT real → {config.mqtt.host}:{config.mqtt.port}")
    else:
        publisher = StubPublisher()
        print("Publisher   : Stub (solo consola)")

    camera = Camera(
        camera_index=config.camera.index,
        classifier=classifier,
        debouncer=debouncer,
        action_resolver=action_resolver,
        publisher=publisher,
        event_logger=event_logger,
        skip_frames=config.inference.skip_frames,
        camera_type=config.camera.type,
        width=config.camera.width,
        height=config.camera.height,
        headless=config.camera.headless,
        hflip=config.camera.hflip,
        vflip=config.camera.vflip,
        user_id=config.session.user_id,
    )
    camera.start()


if __name__ == "__main__":
    main()
