import time
from threading import Condition, Thread
from libcamera import Transform
import cv2
import numpy as np
import os
import subprocess
import re

# Función para detectar automáticamente el dispositivo Cam Link 4K
def get_camlink_device():
    """
    Busca y retorna el primer dispositivo asociado a 'Cam Link 4K'.
    """
    try:
        # Ejecutar el comando v4l2-ctl para listar los dispositivos
        output = subprocess.check_output(['v4l2-ctl', '--list-devices'], text=True)

        # Buscar secciones asociadas con 'Cam Link 4K'
        devices = re.split(r'\n(?=\w)', output)
        for device in devices:
            if 'Cam Link 4K' in device:
                # Extraer los paths de los dispositivos /dev/video*
                video_devices = re.findall(r'/dev/video\\d+', device)
                if video_devices:
                    return video_devices[0]  # Retornar el primer dispositivo encontrado

        print("No se encontró ningún dispositivo 'Cam Link 4K'.")
        return None

    except subprocess.CalledProcessError as e:
        print(f"Error ejecutando v4l2-ctl: {e}")
        return None


# Clase FrameServerCanon
class FrameServerCanon:
    def __init__(self, video_device='/dev/video0'):
        """
        Inicializa el servidor de frames con el dispositivo de video especificado.
        """
        self.cap = cv2.VideoCapture(video_device)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

        self._array = None
        self._timestamp = None
        self._condition = Condition()
        self._running = True
        self._count = 0
        self._thread = Thread(target=self._thread_func, daemon=True)

    @property
    def count(self):
        """A count of the number of frames received."""
        return self._count

    def start(self):
        """To start the FrameServer, you will also need to start the Picamera2 object."""
        self._thread.start()

    def stop(self):
        """To stop the FrameServer"""
        self._running = False
        self.cap.release()
        self._thread.join()

    def _thread_func(self):
        while self._running:
            ret, array = self.cap.read()
            try:
                self._count += 1
                with self._condition:
                    self._array = array
                    self._timestamp = time.monotonic_ns()
                    self._condition.notify_all()
            except Exception as e:
                print(f"Error getting frame: {e}")

    def wait_for_frame(self, previous=None):
        with self._condition:
            if previous is not None and self._array is not previous:
                return self._array, self._timestamp
            while True:
                self._condition.wait()
                if self._array is not previous:
                    return self._array, self._timestamp


# Función principal
def main():
    """
    Detecta automáticamente el dispositivo Cam Link 4K y utiliza FrameServerCanon.
    """
    camlink_device = get_camlink_device()

    if camlink_device:
        print(f"Dispositivo 'Cam Link 4K' detectado en: {camlink_device}")
        serverPlayerOne = FrameServerCanon(camlink_device)
    else:
        print("No se pudo detectar el dispositivo 'Cam Link 4K'. Usando dispositivo predeterminado '/dev/video0'.")
        serverPlayerOne = FrameServerCanon()

    try:
        serverPlayerOne.start()
        # Simulación de captura durante 10 segundos
        time.sleep(10)
    finally:
        serverPlayerOne.stop()


if __name__ == "__main__":
    main()
