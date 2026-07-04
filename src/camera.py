# Importamos la libreria de OpenCv
import cv2
from datetime import datetime, timezone

from src.landmarks import HandDetector


class Camera:

    # Constructor de la clase de la camara
    # camera_type: "webcam" (dev en Windows, OpenCV) | "csi" (Raspberry Pi, Picamera2)
    # headless: True = sin ventana de video (para correr por SSH sin monitor)
    # hflip/vflip: volteo de imagen, solo aplica a la camara CSI (ambos = rotacion 180°)
    def __init__(
        self,
        camera_index=0,
        classifier=None,
        debouncer=None,
        action_resolver=None,
        publisher=None,
        event_logger=None,
        skip_frames=1,
        camera_type="webcam",
        width=640,
        height=480,
        headless=False,
        hflip=False,
        vflip=False,
        user_id="",
    ):
        #  Guardamos el índice de la cámara en la instancia
        self.camera_index = camera_index

        # Guardamos el clasificador
        self.classifier = classifier

        # Guardamos el resolvedor de acciones
        self.action_resolver = action_resolver

        # Guardamos el debouncer
        self.debouncer = debouncer

        # Guardamos el publisher (stub o MQTT real)
        self.publisher = publisher

        # Guardamos el logger de eventos (stub o Mongo real)
        self.event_logger = event_logger

        # Procesar 1 de cada skip_frames frames
        self.skip_frames = skip_frames
        self._frame_count = 0

        # Configuracion de tipo de camara y modo de ejecucion
        self.camera_type = camera_type
        self.width = width
        self.height = height
        self.headless = headless
        self.hflip = hflip
        self.vflip = vflip

        # Usuario de la sesion (viaja en cada comando publicado)
        self.user_id = user_id

        # Guardamos el objeto de captura (VideoCapture o Picamera2 segun el tipo)
        self.cap = None
        self.picam2 = None

        # Instanciamos el detector
        self.hand_detector = HandDetector()

    # -----------------------------------------------------------------
    # Apertura y lectura de frames segun el tipo de camara
    # -----------------------------------------------------------------

    def _open(self):
        if self.camera_type == "csi":
            # Import perezoso: picamera2 solo existe en la Raspberry Pi
            from picamera2 import Picamera2
            from libcamera import Transform

            self.picam2 = Picamera2()
            config = self.picam2.create_preview_configuration(
                # RGB888 en Picamera2 entrega los bytes en orden BGR,
                # que es justo lo que espera OpenCV / nuestro HandDetector
                main={"format": "RGB888", "size": (self.width, self.height)},
                transform=Transform(hflip=int(self.hflip), vflip=int(self.vflip)),
            )
            self.picam2.configure(config)
            self.picam2.start()
        else:
            self.cap = cv2.VideoCapture(self.camera_index)
            if not self.cap.isOpened():
                raise Exception("No se pudo abrir la camara")

    def _read_frame(self):
        if self.camera_type == "csi":
            # capture_array siempre entrega un frame (bloquea hasta tenerlo)
            frame = self.picam2.capture_array()
            return True, frame
        return self.cap.read()

    # -----------------------------------------------------------------
    # Loop principal
    # -----------------------------------------------------------------

    def start(self):

        self._open()

        try:
            # Bucle infinito para leer los frames constantemente
            # En headless se detiene con Ctrl+C (KeyboardInterrupt)
            while True:
                success, frame = self._read_frame()
                if not success:
                    print("No se pudo leer el frame")
                    break

                # Saltamos frames para reducir carga de CPU en Pi 3
                # Los frames saltados no se procesan NI se muestran: la ventana
                # conserva el ultimo frame anotado (evita el parpadeo)
                self._frame_count += 1
                if self._frame_count % self.skip_frames != 0:
                    if not self.headless:
                        # Mantenemos viva la ventana sin redibujarla
                        if cv2.waitKey(1) == ord("q"):
                            break
                    continue

                # Procesamos el frame: detect() devuelve (frame, features)
                # features es None si no hay mano en el frame
                frame, features = self.hand_detector.detect(frame)

                # Si hay una mano, clasificamos
                if features is not None:
                    gesto, confianza = self.classifier.predict(features)

                    # gesto es None cuando la confianza no supera el umbral
                    if gesto is not None:
                        if not self.headless:
                            cv2.putText(
                                frame,
                                f"{gesto} {confianza: .0%}",
                                (10, 60),
                                cv2.FONT_HERSHEY_SIMPLEX,
                                0.8,
                                (0, 255, 255),
                                2,
                            )

                        if self.debouncer.should_fire(gesto):
                            accion = self.action_resolver.resolve(gesto)
                            if accion is not None:
                                # Construimos el comando segun el contrato (CLAUDE.md §5.2)
                                comando = {
                                    "deviceId": accion["deviceId"],
                                    "action": accion["action"],
                                    "userId": self.user_id,
                                    "ts": datetime.now(timezone.utc).isoformat(),
                                }
                                print(f"[{gesto} {confianza:.0%}] → {comando['deviceId']} / {comando['action']}")
                                self.publisher.publish(comando)

                                # Registramos el evento (contrato CLAUDE.md §5.3)
                                # float() porque numpy.float no serializa a Mongo
                                if self.event_logger is not None:
                                    self.event_logger.log(
                                        {
                                            "userId": self.user_id,
                                            "gesture": gesto,
                                            "confidence": float(confianza),
                                            "deviceId": accion["deviceId"],
                                            "action": accion["action"],
                                            "ts": comando["ts"],
                                        }
                                    )
                            else:
                                print(f"No hay acción para el gesto: {gesto}")

                # En headless no hay ventana: seguimos al siguiente frame
                if self.headless:
                    continue

                cv2.imshow("Gesture Assitant", frame)

                # waitKey espera 1 ms una tecla; sin el la ventana se congela
                if cv2.waitKey(1) == ord("q"):
                    break
        except KeyboardInterrupt:
            # Ctrl+C en la terminal (unico modo de salir en headless)
            print("\nDeteniendo pipeline...")
        finally:
            # Pase lo que pase, liberamos recursos
            self.stop()

    # Método para cerrar correctamente la cámara
    def stop(self):

        # Liberamos la camara segun el tipo
        # Esto es MUY importante: si no, la camara queda bloqueada
        # y otros programas no podran usarla
        if self.cap:
            self.cap.release()

        if self.picam2:
            self.picam2.stop()

        # Cerramos todas las ventanas de OpenCV
        if not self.headless:
            cv2.destroyAllWindows()
