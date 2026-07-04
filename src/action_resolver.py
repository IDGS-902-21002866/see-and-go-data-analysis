import json
import os

from pymongo import MongoClient

_DEFAULT_STUB = os.path.join(os.path.dirname(__file__), "..", "data", "user_signs_stub.json")


class ActionResolver:
    """Cache en memoria gesto → {deviceId, action}.

    Se construye UNA vez al inicio de la sesion con la lista de signs
    (leida de Mongo o del stub JSON). Durante el loop, resolve() es O(1) sin red.
    """

    def __init__(self, signs: list):
        cache = {}

        for sign in signs:
            name = sign["gesture"]

            action = {"deviceId": sign["deviceId"], "action": sign["action"]}

            cache[name] = action

        self.cache = cache

    def resolve(self, gesture: str) -> dict | None:
        return self.cache.get(gesture, None)

    # -----------------------------------------------------------------
    # Cargadores: de donde sacar la lista de signs al iniciar sesion
    # -----------------------------------------------------------------

    @staticmethod
    def load_signs_from_mongo(uri: str, database: str, collection: str, user_id: str) -> list | None:
        """Lee el documento user_signs del usuario desde MongoDB.

        Devuelve la lista de signs, o None si Mongo no responde o no hay
        documento — el caller decide el fallback (stub JSON).
        """
        try:
            client = MongoClient(uri, serverSelectionTimeoutMS=5000)
            doc = client[database][collection].find_one({"userId": user_id})
            if doc is None:
                print(f"[Mongo] No hay documento user_signs para '{user_id}'")
                return None
            return doc.get("signs", [])
        except Exception as e:
            print(f"[Mongo] No se pudo leer user_signs: {e}")
            return None

    @staticmethod
    def load_signs_from_stub(stub_path: str = _DEFAULT_STUB) -> list:
        """Lee la lista de signs del JSON local (fallback sin red)."""
        with open(stub_path, "r") as f:
            stub = json.load(f)
        return stub.get("signs", [])
