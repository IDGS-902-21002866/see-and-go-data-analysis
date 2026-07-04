import json
import os

_DEFAULT_STUB = os.path.join(os.path.dirname(__file__), "..", "data", "user_signs_stub.json")


class ActionResolver:
    def __init__(self, stub_path: str = _DEFAULT_STUB):
        stub = json.load(open(stub_path, "r"))

        signs = stub.get("signs", [])

        cache = {}

        for sign in signs:
            name = sign["gesture"]

            action = {"deviceId": sign["deviceId"], "action": sign["action"]}

            cache[name] = action

        self.cache = cache

    def resolve(self, gesture: str) -> dict | None:
        return self.cache.get(gesture, None)
