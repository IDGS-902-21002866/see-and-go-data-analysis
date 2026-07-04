import queue
import threading

from pymongo import MongoClient


class EventLogger:
    """Interfaz base: cualquier logger debe implementar log(event)."""

    def log(self, event: dict) -> None:
        raise NotImplementedError


class StubLogger(EventLogger):
    """Logger falso para desarrollo: solo imprime el evento en consola."""

    def log(self, event: dict) -> None:
        print(f"[STUB EVENT] {event}")


class MongoLogger(EventLogger):
    """Logger real: escribe eventos en MongoDB sin bloquear el loop de inferencia.

    Usa una cola + hilo trabajador: log() solo encola (instantaneo) y el hilo
    aparte hace el insert a Mongo (lento, pero fuera del loop). Si Mongo falla,
    se imprime el error y el pipeline sigue — nunca se tumba por telemetria.
    """

    def __init__(self, uri: str, database: str, collection: str):
        # serverSelectionTimeoutMS corto: si Atlas no responde, fallamos rapido
        client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        self.collection = client[database][collection]

        self.queue = queue.Queue()

        # daemon=True: el hilo muere solo cuando el programa termina
        threading.Thread(target=self._worker, daemon=True).start()

    def log(self, event: dict) -> None:
        # Instantaneo: solo encola, la red la toca el hilo trabajador
        self.queue.put(event)

    def _worker(self) -> None:
        while True:
            event = self.queue.get()
            try:
                self.collection.insert_one(event)
            except Exception as e:
                print(f"[Mongo] Error guardando evento: {e}")
