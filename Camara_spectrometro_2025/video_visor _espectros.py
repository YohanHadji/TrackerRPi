import cv2
import numpy as np
import matplotlib.pyplot as plt
import tkinter as tk
from tkinter import filedialog, ttk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

def pixel_to_wavelength(x):
    return -0.0006947613 * x**2 + 1.8956101093 * x - 398.0146563877

def visualizar_videos_espectro():
    root = tk.Tk()
    root.title("Visor Espectros en Tiempo Real")

    # Seleccionar múltiples videos
    video_paths = filedialog.askopenfilenames(filetypes=[("Video AVI", "*.avi")])
    if not video_paths:
        print("No se seleccionaron videos.")
        return

    cap = None
    fps_video = 0
    frame_idx = 0
    total_frames = 0
    playing = True
    velocidad = tk.DoubleVar(value=10.0)
    
    # --- Gráfico ---
    fig = plt.Figure(figsize=(7, 3), dpi=100)
    ax = fig.add_subplot(111)
    linea, = ax.plot([], [], color='blue')
    ax.set_xlim(400, 780)
    ax.set_ylim(0, 255)
    ax.set_title("Espectro en tiempo real")
    ax.set_xlabel("Longitud de onda (nm)")
    ax.set_ylabel("Intensidad")

    canvas = FigureCanvasTkAgg(fig, master=root)
    canvas.get_tk_widget().pack()

    tiempo_label = tk.Label(root, text="Tiempo: 0.0 s")
    tiempo_label.pack()

    # --- Slider de línea de tiempo ---
    slider_tiempo = tk.Scale(root, from_=0, to=100, orient="horizontal", length=400, label="Posición del video")
    slider_tiempo.pack()

    # --- Funciones de control ---
    def cargar_video(index):
        nonlocal cap, fps_video, frame_idx, total_frames
        if cap:
            cap.release()
        cap = cv2.VideoCapture(video_paths[index])
        fps_video = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        slider_tiempo.config(to=total_frames)
        frame_idx = 0
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

    def toggle_play():
        nonlocal playing
        playing = not playing
        play_button.config(text="Play" if not playing else "Pause")

    def retroceder():
        nonlocal frame_idx
        if cap:
            frame_idx = max(0, frame_idx - int(fps_video))
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            slider_tiempo.set(frame_idx)

    def cambiar_video(event=None):
        idx = combo_videos.current()
        cargar_video(idx)

    def mover_slider(val):
        nonlocal frame_idx
        if cap:
            frame_idx = int(float(val))
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)

    play_button = tk.Button(root, text="Pause", command=toggle_play)
    play_button.pack(side="left", padx=5)
    tk.Button(root, text="Retroceder 1s", command=retroceder).pack(side="left", padx=5)
    tk.Label(root, text="Velocidad (fps)").pack(side="left")
    tk.Scale(root, from_=1, to=60, variable=velocidad, orient="horizontal").pack(side="left")

    # --- Selector de videos ---
    combo_videos = ttk.Combobox(root, width=100, values=video_paths)
    combo_videos.current(0)
    combo_videos.pack(side="left", padx=5)
    combo_videos.bind("<<ComboboxSelected>>", cambiar_video)

    slider_tiempo.bind("<ButtonRelease-1>", lambda e: mover_slider(slider_tiempo.get()))

    cargar_video(0)

    def reproducir():
        nonlocal frame_idx
        if cap and playing:
            ret, frame = cap.read()
            if ret:
                frame_idx += 1
                h = frame.shape[0]
                y1, y2 = int(h * 0.4), int(h * 0.6)
                frame_roi = frame[y1:y2, :]
                gray = cv2.cvtColor(frame_roi, cv2.COLOR_BGR2GRAY)
                profile = np.mean(gray, axis=0)
                x_nm = [pixel_to_wavelength(i) for i in range(len(profile))]
                ymax = max(profile) if len(profile) > 0 else 1
                if ymax < 1:
                    ymax = 1
                linea.set_data(x_nm, profile)
                ax.set_ylim(0, ymax * 1.1)
                canvas.draw()
                tiempo_actual = frame_idx / fps_video
                tiempo_label.config(text=f"Tiempo relativo: {tiempo_actual:.2f} s")
                slider_tiempo.set(frame_idx)
            else:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                frame_idx = 0
        delay = int(1000 / velocidad.get())
        root.after(delay, reproducir)

    reproducir()
    root.mainloop()
    if cap:
        cap.release()

if __name__ == "__main__":
    visualizar_videos_espectro()
