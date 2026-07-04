import os
import yaml
from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()


class MqttConfig(BaseModel):
    host: str
    port: int
    topic_prefix: str
    publisher: str = "stub"  # stub | mqtt
    user: str = ""
    password: str = ""


class MongoConfig(BaseModel):
    uri: str
    database: str
    collection_signs: str
    collection_events: str
    collection_devices: str = "user_devices"
    logger: str = "stub"  # stub | mongo


class ModelConfig(BaseModel):
    path: str


class CameraConfig(BaseModel):
    type: str = "webcam"  # webcam | csi
    index: int
    width: int
    height: int
    headless: bool = False
    hflip: bool = False
    vflip: bool = False


class InferenceConfig(BaseModel):
    confidence_threshold: float
    cooldown_seconds: float
    skip_frames: int = 1


class SessionConfig(BaseModel):
    user_id: str


class AppConfig(BaseModel):
    mqtt: MqttConfig
    mongo: MongoConfig
    model: ModelConfig
    camera: CameraConfig
    inference: InferenceConfig
    session: SessionConfig


def load_config(path: str = "config.yaml") -> AppConfig:
    with open(path, "r") as f:
        raw = yaml.safe_load(f)

    # Inyectar secretos desde .env en las secciones correspondientes
    raw["mqtt"]["user"] = os.getenv("MQTT_USER", "")
    raw["mqtt"]["password"] = os.getenv("MQTT_PASSWORD", "")
    raw["mongo"]["uri"] = os.getenv("MONGO_URI", "mongodb://localhost:27017")

    return AppConfig(**raw)
