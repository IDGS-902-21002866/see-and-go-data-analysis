import time


class Debouncer:
    def __init__(self, cooldown: float):
        self.cooldown = cooldown
        self.last_fired = {}

    def should_fire(self, gesture: str) -> bool:
        now = time.time()
        last_fired = self.last_fired.get(gesture, 0)

        time_delta = now - last_fired

        if time_delta >= self.cooldown:
            self.last_fired[gesture] = now
            return True

        return False
