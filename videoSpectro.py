### videoSpectro.py — Modo Video en Tiempo Real Mejorado

import os
import cv2
import csv
import datetime
import numpy as np
import tkinter as tk
from PIL import Image, ImageTk
from picamera2 import Picamera2
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import threading

# === CALIBRACIÓN ===
def pixel_to_wavelength(x):
    return -0.0003603 * x**2 + 1.4657 * x - 255.63


# === CONFIGURACIÓN ===
roi_top = 0.4
roi_height = 0.2
paused = False
os.makedirs("datos", exist_ok=True)

picam2 = Picamera2(1)
picam2.configure(picam2.create_preview_configuration(main={"size": (1280, 720)}))
picam2.start()

# === INTERFAZ ===
root = tk.Tk()
root.title("Video Espectro Avanzado")

fig = Figure(figsize=(7, 4), dpi=100)
ax = fig.add_subplot(111)
linea, = ax.plot([], [], color='blue')
ax.set_title("Intensidad espectral")
ax.set_xlabel("Longitud de onda (nm)")
ax.set_ylabel("Intensidad")
for ref in [408, 531.8, 652]:
    ax.axvline(x=ref, color='gray', linestyle='--')
canvas = FigureCanvasTkAgg(fig, master=root)
canvas.draw()
canvas.get_tk_widget().pack()

frame_slider = tk.Frame(root)
frame_slider.pack()
xmin_slider = tk.Scale(frame_slider, from_=350, to=850, orient="horizontal", label="X min (nm)")
xmin_slider.set(400)
xmin_slider.pack(side="left")
xmax_slider = tk.Scale(frame_slider, from_=400, to=900, orient="horizontal", label="X max (nm)")
xmax_slider.set(780)
xmax_slider.pack(side="left")

video_label = tk.Label(root)
video_label.pack()

controls = tk.Frame(root)
controls.pack()

# === FUNCIONES ===
def toggle_pause():
    global paused
    paused = not paused
    pause_button.config(text="Reanudar" if paused else "Pausar")

def guardar_datos(frame, perfil):
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    base = f"espectro_{timestamp}"
    cv2.imwrite(f"datos/{base}.jpg", cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
    with open(f"datos/{base}.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Longitud de onda (nm)", "Intensidad"])
        for i, val in enumerate(perfil):
            writer.writerow([pixel_to_wavelength(i), val])
    print(f"Guardado: {base}")

def iniciar_integracion():
    global integrando, integracion_frames
    integrando = True
    integracion_frames = []
    duracion = integracion_slider.get()
    threading.Thread(target=terminar_integracion, args=(duracion,), daemon=True).start()

def terminar_integracion(duracion):
    global integrando
    time.sleep(duracion)
    if integracion_frames:
        suma = np.sum(integracion_frames, axis=0)
        perfil = suma / len(integracion_frames)
        guardar_datos(current_frame, perfil)
    integrando = False

def iniciar_grabacion():
    global grabando, writer_video
    if not grabando:
        grabando = True
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        writer_video = cv2.VideoWriter(f"datos/video_{ts}.avi", cv2.VideoWriter_fourcc(*'XVID'), 10, (1280, 720))
        grabar_button.config(text="Detener grabación")
    else:
        grabando = False
        writer_video.release()
        grabar_button.config(text="Grabar video")

def activar_autodisparo():
    global autodisparo
    autodisparo = not autodisparo
    auto_button.config(text="Desactivar autodisparo" if autodisparo else "Activar autodisparo")

# === BOTONES ===
pause_button = tk.Button(controls, text="Pausar", command=toggle_pause)
pause_button.pack(side="left", padx=5)
tk.Button(controls, text="Guardar espectro", command=lambda: guardar_datos(current_frame, current_profile)).pack(side="left", padx=5)
grabando = False
writer_video = None
grabar_button = tk.Button(controls, text="Grabar video", command=iniciar_grabacion)
grabar_button.pack(side="left", padx=5)

integracion_slider = tk.Scale(controls, from_=1, to=10, orient="horizontal", label="Integrar (s)")
integracion_slider.set(3)
integracion_slider.pack(side="left")
tk.Button(controls, text="Iniciar integración", command=iniciar_integracion).pack(side="left", padx=5)

umbral_slider = tk.Scale(controls, from_=10, to=200, orient="horizontal", label="Umbral")
umbral_slider.set(50)
umbral_slider.pack(side="left")
autodisparo = False
auto_button = tk.Button(controls, text="Activar autodisparo", command=activar_autodisparo)
auto_button.pack(side="left", padx=5)

# === LOOP PRINCIPAL ===
integrando = False
integracion_frames = []
def update_frame():
    global current_frame, current_profile
    if not paused:
        frame = picam2.capture_array()
        h = frame.shape[0]
        y1, y2 = int(h * roi_top), int(h * (roi_top + roi_height))
        frame_roi = frame[y1:y2, :]
        gray = cv2.cvtColor(frame_roi, cv2.COLOR_RGB2GRAY)
        profile = np.mean(gray, axis=0)
        current_frame = frame_roi.copy()
        current_profile = profile

        x_nm = [pixel_to_wavelength(i) for i in range(len(profile))]
        x_min, x_max = xmin_slider.get(), xmax_slider.get()
        mask = [(x >= x_min and x <= x_max) for x in x_nm]
        linea.set_data(np.array(x_nm)[mask], np.array(profile)[mask])
        ax.set_xlim(x_min, x_max)
        ax.set_ylim(0, max(profile) * 1.1 if len(profile) > 0 else 1)
        canvas.draw()

        img_pil = Image.fromarray(frame_roi)
        video_label.imgtk = ImageTk.PhotoImage(image=img_pil)
        video_label.configure(image=video_label.imgtk)

        if integrando:
            integracion_frames.append(profile)

        if grabando:
            writer_video.write(cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))

        if autodisparo and max(profile) > umbral_slider.get():
            guardar_datos(current_frame, current_profile)

    root.after(30, update_frame)

update_frame()
root.mainloop()
picam2.stop()
