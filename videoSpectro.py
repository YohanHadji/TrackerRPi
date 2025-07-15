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

# === CALIBRACIÓN ===
def pixel_to_wavelength(x):
    return 0.000077 * x**2 + 2.0196 * x - 109.95

# === ROI (zona del espectro) ===
roi_top = 0.4
roi_height = 0.2
paused = False

# === CARPETAS ===
os.makedirs("datos", exist_ok=True)

# === CÁMARA ===
picam2 = Picamera2(1)
config = picam2.create_preview_configuration(main={"size": (640, 480)})
picam2.configure(config)
picam2.start()

# === FUNCIONES ===
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

def toggle_pause():
    global paused
    paused = not paused
    pause_button.config(text="Reanudar" if paused else "Pausar")

# === VENTANA PRINCIPAL ===
root = tk.Tk()
root.title("Espectrómetro Simplificado")

# === GRÁFICO ===
fig = Figure(figsize=(7, 4), dpi=100)
ax = fig.add_subplot(111)
ax.set_title("Intensidad espectral")
ax.set_xlabel("Longitud de onda (nm)")
ax.set_ylabel("Intensidad")
linea, = ax.plot([], [], color='blue')

# Líneas de referencia
ref_lines = [408, 531.8, 652]
for ref in ref_lines:
    ax.axvline(x=ref, color='gray', linestyle='--')

canvas = FigureCanvasTkAgg(fig, master=root)
canvas.draw()
canvas.get_tk_widget().pack()

# === SLIDERS PARA RANGO DE GRAFICO ===
frame_slider = tk.Frame(root)
frame_slider.pack()
tk.Label(frame_slider, text="X min (nm)").pack(side="left")
xmin_slider = tk.Scale(frame_slider, from_=350, to=850, orient="horizontal")
xmin_slider.set(400)
xmin_slider.pack(side="left")
tk.Label(frame_slider, text="X max (nm)").pack(side="left")
xmax_slider = tk.Scale(frame_slider, from_=400, to=900, orient="horizontal")
xmax_slider.set(780)
xmax_slider.pack(side="left")

# === VIDEO ===
video_label = tk.Label(root)
video_label.pack()

# === BOTONES ===
controls = tk.Frame(root)
controls.pack()
pause_button = tk.Button(controls, text="Pausar", command=toggle_pause)
pause_button.pack(side="left", padx=10)
tk.Button(controls, text="Guardar espectro", command=lambda: guardar_datos(current_frame, current_profile)).pack(side="left", padx=10)

# === LOOP DE ACTUALIZACIÓN ===
def update_frame():
    global current_frame, current_profile
    if not paused:
        full_frame = picam2.capture_array()
        h = full_frame.shape[0]
        y1, y2 = int(h * roi_top), int(h * (roi_top + roi_height))
        frame_roi = full_frame[y1:y2, :]
        gray = cv2.cvtColor(frame_roi, cv2.COLOR_RGB2GRAY)
        profile = np.mean(gray, axis=0)
        current_frame = frame_roi.copy()
        current_profile = profile

        img_pil = Image.fromarray(frame_roi)
        video_label.imgtk = ImageTk.PhotoImage(image=img_pil)
        video_label.configure(image=video_label.imgtk)

        x_nm = [pixel_to_wavelength(i) for i in range(len(profile))]
        x_min = xmin_slider.get()
        x_max = xmax_slider.get()

        # Filtrar datos dentro del rango visible seleccionado
        mask = [(x >= x_min and x <= x_max) for x in x_nm]
        x_visible = np.array(x_nm)[mask]
        y_visible = np.array(profile)[mask]

        linea.set_data(x_visible, y_visible)
        ax.set_xlim(x_min, x_max)
        ax.set_ylim(0, max(y_visible) * 1.1 if len(y_visible) > 0 else 1)
        canvas.draw()

    root.after(30, update_frame)

update_frame()
root.mainloop()
picam2.stop()
