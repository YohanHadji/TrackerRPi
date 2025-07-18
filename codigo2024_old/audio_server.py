from flask import Flask, Response, render_template
import pyaudio
import wave
import io

app = Flask(__name__)

class AudioServer:
    def __init__(self, audio_device_index=None):
        self.audio = pyaudio.PyAudio()
        self.audio_device_index = audio_device_index
        self.audio_stream = self.audio.open(
            format=pyaudio.paInt16,
            channels=2,
            rate=48000,
            input=True,
            input_device_index=self.audio_device_index,
            frames_per_buffer=1024
        )

    def get_audio_chunk(self):
        try:
            return self.audio_stream.read(1024, exception_on_overflow=False)
        except OSError as e:
            print(f"Error al leer audio: {e}")
            return None

    def stop(self):
        if hasattr(self, 'audio_stream') and self.audio_stream:
            self.audio_stream.stop_stream()
            self.audio_stream.close()
        self.audio.terminate()

audio_device_index = 0  # Cambia esto al índice correcto
server = AudioServer(audio_device_index)

@app.route('/')
def index():
    return render_template('audio_index.html')  # Renderiza el archivo index.html

@app.route('/audio_feed')
def audio_feed():
    def generate_audio():
        wav_header = io.BytesIO()
        with wave.open(wav_header, 'wb') as wav_file:
            wav_file.setnchannels(2)
            wav_file.setsampwidth(2)
            wav_file.setframerate(48000)
            wav_file.writeframes(b'')
        yield wav_header.getvalue()

        while True:
            audio_chunk = server.get_audio_chunk()
            if audio_chunk is None:
                break
            yield audio_chunk

    return Response(generate_audio(), mimetype='audio/wav')

if __name__ == '__main__':
    try:
        app.run(host='0.0.0.0', port=5003, threaded=True)
    finally:
        server.stop()
