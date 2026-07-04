# Importamos la libreria de OpenCv
import cv2

from src.landmarks import HandDetector


class Camera:

    # Constructor de la clase de la camara
    # Este se ejecuta cuando se instancia la clase
    # camara_index = 0 quiere decir que se usa la camara por defecto del sistema
    # classifier como None
    #  Si se tienen varias camaras 0 = camara principal, 1 = segunda camara
    def __init__(
        self,
        camera_index=0,
        classifier=None,
        debouncer=None,
        action_resolver=None,
        skip_frames=1,
    ):
        #  Guardamos el índice de la cámara en la instancia
        self.camera_index = camera_index

        # Guardamos el clasificador
        self.classifier = classifier

        # Guardamos el resolvedor de acciones
        self.action_resolver = action_resolver

        # Guardamos el debouncer
        self.debouncer = debouncer

        # Procesar 1 de cada skip_frames frames
        self.skip_frames = skip_frames
        self._frame_count = 0

        # Guardamos el opjeto de videocapture de openCv
        self.cap = None

        # Instanciamos el detector
        self.hand_detector = HandDetector()

    def start(self):

        # Creamos el objeto de VideoCapture, OpenCb intenta conectarse a la cámara indicada
        self.cap = cv2.VideoCapture(self.camera_index)

        # Validamos que la camara se abrió, si no devolvemos un error
        if not self.cap.isOpened():
            raise Exception("No se pudo abrir la camara")

        # Crearemos un bucle infinito para leer los frames constantemento
        while True:
            # Leemos un frame desde la camara
            #  la funcion read() devuelve dos cosas
            #
            #  success -> True si el frame se leyo correctamente
            # frame -> imagen capturada
            success, frame = self.cap.read()
            # Si ocurrió un error leyendo el frame
            if not success:

                # Mostramos mensaje de error
                print("No se pudo leer el frame")

                # Rompemos el loop
                break

            # Saltamos frames para reducir carga de CPU en Pi 3
            # El video se muestra siempre; la inferencia solo corre cada skip_frames frames

            self._frame_count += 1
            if self._frame_count % self.skip_frames != 0:
                cv2.imshow("Gesture Assitant", frame)
                key = cv2.waitKey(1)
                if key == ord("q"):
                    break
                continue

            # Usamos el frame que detecto OpenCV y lo procesamos
            # detect() ahora devuelve (frame, features)
            # features es None si no hay mano en el frame
            frame, features = self.hand_detector.detect(frame)

            # Si se muestra una manu hace la valuación
            if features is not None:
                gesto, confianza = self.classifier.predict(features)
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
                        print(f"Ejecutando acción: {accion}")
                    if accion is None:
                        print(f"No hay acción para el gesto: {gesto}")

            # Primer parametro, nombre de la ventana. Segundo parametro, frame que queremos mostrar
            cv2.imshow("Gesture Assitant", frame)

            # waitKey espera una tecla del teclado
            #
            # El parámetro 1 significa:
            # esperar 1 milisegundo
            #
            # Esto es IMPORTANTÍSIMO:
            # sin waitKey la ventana se congela
            key = cv2.waitKey(1)

            # Salimos de la ventana si el usuario aprieta q
            if key == ord("q"):
                # Salimos del loop
                break
        # Cuando el loop termina, liberamos recursos
        self.stop()

    # Método para cerrar correctamente la cámara
    def stop(self):

        # Verificamos que la cámara exista
        if self.cap:

            # Liberamos la cámara
            #
            # Esto es MUY importante
            # porque si no:
            # - la cámara queda bloqueada
            # - otros programas no podrán usarla
            self.cap.release()

        # Cerramos todas las ventanas de OpenCV
        cv2.destroyAllWindows()
