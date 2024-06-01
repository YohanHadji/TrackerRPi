from flask import Flask, render_template, Response, request, redirect, url_for
from picamera import PiCamera
from picamera.array import PiRGBArray
import cv2
import io
import time
import serial

app = Flask(__name__)

# Initialize the camera
camera = PiCamera()
camera.resolution = (640, 480)
camera.framerate = 24
rawCapture = PiRGBArray(camera, size=(640, 480))

# Allow the camera to warm up
time.sleep(0.1)

# Initialize serial communication with Arduino
ser = serial.Serial('/dev/ttyUSB0', 9600, timeout=1)

def gen_frames():
    for frame in camera.capture_continuous(rawCapture, format="bgr", use_video_port=True):
        image = frame.array
        ret, buffer = cv2.imencode('.jpg', image)
        frame = buffer.tobytes()
        
        # Clear the stream for the next frame
        rawCapture.truncate(0)

        # Yield frame to Flask response
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n\r\n')

@app.route('/video_feed')
def video_feed():
    return Response(gen_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/')
def index():
    return render_template('oldIndex.html')

@app.route('/zoom_in')
def zoom_in():
    ser.write(b'zoom_in\n')
    return redirect(url_for('oldIndex'))

@app.route('/zoom_out')
def zoom_out():
    ser.write(b'zoom_out\n')
    return redirect(url_for('oldIndex'))

@app.route('/record_on')
def record_on():
    ser.write(b'record_on\n')
    return redirect(url_for('oldIndex'))

@app.route('/record_off')
def record_off():
    ser.write(b'record_off\n')
    return redirect(url_for('oldIndex'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
