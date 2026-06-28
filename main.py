from src.camera import Camera
from src.config import load_config
from src.classifier import Classifier


def main():
    config = load_config()

    print(f"Broker MQTT : {config.mqtt.host}:{config.mqtt.port}")
    print(f"MongoDB     : {config.mongo.uri}")
    print(f"Usuario     : {config.session.user_id}")
    print(f"Umbral      : {config.inference.confidence_threshold}")
    print()

    classifier = Classifier(umbral=config.inference.confidence_threshold)

    camera = Camera(camera_index=config.camera.index, classifier=classifier)
    camera.start()


if __name__ == "__main__":
    main()
