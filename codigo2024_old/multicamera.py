from flask import Flask, send_from_directory, request, Response
import requests

app = Flask(__name__)  # Mueve esta línea al inicio

@app.route('/')
def serve_html():
    return send_from_directory('.', 'fusion_buscador_index.html')  # Asegúrate de que el archivo esté en el directorio correcto

@app.route('/video_feed_1')
def video_feed_1():
    try:
        resp = requests.get('http://localhost:5000/video_feed', stream=True)
        return Response(resp.iter_content(chunk_size=10 * 1024),
                        content_type=resp.headers['Content-Type'])
    except requests.exceptions.RequestException as e:
        return f"Error al obtener video_feed_1: {e}", 500

@app.route('/video_feed_2')
def video_feed_2():
    try:
        resp = requests.get('http://localhost:5002/video_feed', stream=True)
        return Response(resp.iter_content(chunk_size=10 * 1024),
                        content_type=resp.headers['Content-Type'])
    except requests.exceptions.RequestException as e:
        return f"Error al obtener video_feed_2: {e}", 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)
