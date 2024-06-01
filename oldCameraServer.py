from flask import Flask, Response
import cv2
import io
from libcamera import Camera

app = Flask(__name__)

# Initialize the camera
camera = Camera()
camera.start()

def gen_frames():
    while True:
        # Capture frame-by-frame
        frame = camera.capture_frame()
        
        # Convert the frame to JPEG
        ret, buffer = cv2.imencode('.jpg', frame)
        frame = buffer.tobytes()

        # Yield frame to Flask response
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n\r\n')

@app.route('/video_feed')
def video_feed():
    return Response(gen_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/')
def index():
    return app.send_static_file('/templates/oldIndex.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
