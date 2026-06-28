import os
import yaml
from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()


class MqttConfig(BaseModel):
    host: str
    port: int
    topic_prefix: str
    user: str = ""
    password: str = ""


class MongoConfig(BaseModel):
    uri: str
    database: str
    collection_signs: str
    collection_events: str


class ModelConfig(BaseModel):
    path: str


class CameraConfig(BaseModel):
    index: int
    width: int
    height: int


class InferenceConfig(BaseModel):
    confidence_threshold: float
    cooldown_seconds: float


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
