from flask import Flask, render_template, request, Response
from picamera import PiCamera
import time
import io

app = Flask(__name__)

camera = PiCamera()

# Function to handle POST requests from buttons
def zoom_in():
    print("Zoom + called")

def zoom_out():
    print("Zoom - called")

def record_on():
    print("Record On called")
    # camera.start_recording('video.h264')

def record_off():
    print("Record Off called")
    # camera.stop_recording()

@app.route('/')
def index():
    return render_template('oldIndex.html')

@app.route('/zoom_in', methods=['POST'])
def button1():
    zoom_in()
    return '', 204

@app.route('/zoom_out', methods=['POST'])
def button2():
    zoom_out()
    return '', 204

@app.route('/record_on', methods=['POST'])
def button3():
    record_on()
    return '', 204

@app.route('/record_off', methods=['POST'])
def button4():
    record_off()
    return '', 204

@app.route('/video_feed')
def video_feed():
    return Response(gen(camera), mimetype='multipart/x-mixed-replace; boundary=frame')

def gen(camera):
    while True:
        time.sleep(0.1)  # Adjust delay according to your frame rate requirement
        frame = capture_frame(camera)
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

def capture_frame(camera):
    frame = io.BytesIO()
    camera.capture(frame, format='jpeg', use_video_port=True)
    return frame.getvalue()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
