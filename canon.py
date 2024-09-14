import time

import time
from threading import Condition, Thread

from libcamera import Transform

import cv2
import numpy as np

# Initialize the webcam (Elgato USB cam link)
cap = cv2.VideoCapture(0)
cap.set(cv2.CAP_PROP_FOURCC,cv2.VideoWriter_fourcc('M','J','P','G'))

class FrameServerCanon:
    def __init__(self):
        """A simple class that can serve up frames from one of the Picamera2's configured streams to multiple other threads.

        Pass in the Picamera2 object and the name of the stream for which you want
        to serve up frames.
        """
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
        """To stop the FrameServer

        First stop any client threads (that might be
        blocked in wait_for_frame), then call this stop method. Don't stop the
        Picamera2 object until the FrameServer has been stopped.
        """
        self._running = False
        cap.release()
        self._thread.join()

    def _thread_func(self):
        while self._running:
            ret, array = cap.read()
            
            # print("Got frame")
            try: 
                # print(array.shape)
                self._count += 1
                with self._condition:
                    self._array = array
                    # timestamp is time since start of code in nanoseconds
                    self._timestamp = time.monotonic_ns()
                    self._condition.notify_all()
            except:
                print("Error getting frame")

    def wait_for_frame(self, previous=None):
        """You may optionally pass in the previous frame that you got last time you called this function.

        This will guarantee that you don't get duplicate frames
        returned in the event of spurious wake-ups, and it may even return more
        quickly in the case where a new frame has already arrived.
        """
        with self._condition:
            if previous is not None and self._array is not previous:
                return self._array, self._timestamp
            while True:
                self._condition.wait()
                if self._array is not previous:
                    return self._array, self._timestamp