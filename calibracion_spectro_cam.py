import numpy as np
import tkinter as tk
from tkinter import filedialog, simpledialog, messagebox
import matplotlib.pyplot as plt
from matplotlib.backend_bases import MouseButton
from matplotlib.widgets import Button as MplButton
import cv2
import os

# === Lista de puntos seleccionados ===
pixeles_cal = []
longitudes_cal = []
lineas_dibujadas = []
textos_dibujados = []

# === Cargar imágenes y calcular perfil promedio ===
def cargar_imagenes():
    rutas = filedialog.askopenfilenames(
        title="Seleccionar imágenes del espectro",
        filetypes=[("Imágenes", "*.jpg *.png *.jpeg")])
    if not rutas:
        return None, None
    perfiles = []
    for ruta in rutas:
        img = cv2.imread(ruta)
        if img is not None:
            gris = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            perfil = np.mean(gris, axis=0)
            perfiles.append(perfil)
        else:
            print(f"[ERROR] No se pudo cargar {ruta}")
    if not perfiles:
        return None, None
    promedio = np.mean(perfiles, axis=0)
    return np.arange(len(promedio)), promedio

# === Clic en el gráfico para asignar longitud de onda ===
def on_click(event):
    if event.button is MouseButton.LEFT and event.inaxes == ax:
        pixel = event.xdata
        lam = simpledialog.askfloat("Longitud de onda conocida", f"Pixel {int(pixel)}: Ingrese longitud de onda (nm)")
        if lam is not None:
            pixeles_cal.append(pixel)
            longitudes_cal.append(lam)
            lineas_dibujadas.append(ax.axvline(pixel, color='green', linestyle='--'))
            textos_dibujados.append(ax.text(pixel, event.ydata, f"{lam:.1f} nm", rotation=90, color='green', va='bottom'))
            fig.canvas.draw_idle()

# === Calcular y guardar calibración sin preguntar ruta ===
def calibrar():
    if len(pixeles_cal) < 3:
        messagebox.showwarning("Calibración", "Se necesitan al menos 3 puntos para calibrar.")
        return
    try:
        coef = np.polyfit(pixeles_cal, longitudes_cal, 2)
        print(f"[DEBUG] Coeficientes: a={coef[0]}, b={coef[1]}, c={coef[2]}")
        if np.any(np.isnan(coef)):
            raise ValueError("Coeficientes inválidos (NaN)")

        ruta_base = "/home/pi/TrackerRPi/datos/calibracion_actual"
        ruta_py = ruta_base + ".py"
        ruta_png = ruta_base + "_calibracion.png"

        contenido = (
            "def pixel_to_wavelength(x):\n"
            f"    return {coef[0]:.10f} * x**2 + {coef[1]:.10f} * x + {coef[2]:.10f}\n"
        )

        with open(ruta_py, 'w') as f:
            f.write(contenido)
            f.flush()
            os.fsync(f.fileno())

        fig.savefig(ruta_png, dpi=150)

        print(f"[OK] Función guardada en: {ruta_py}")
        print(f"[OK] Imagen guardada en:  {ruta_png}")
        messagebox.showinfo("Calibración completa", f"Guardado:\n{ruta_py}\n{ruta_png}")

    except Exception as e:
        print(f"[ERROR] Falló la calibración: {e}")
        messagebox.showerror("Error", f"Falló la calibración:\n{e}")

# === Limpiar puntos seleccionados ===
def limpiar():
    pixeles_cal.clear()
    longitudes_cal.clear()
    for l in lineas_dibujadas + textos_dibujados:
        l.remove()
    lineas_dibujadas.clear()
    textos_dibujados.clear()
    fig.canvas.draw_idle()

# === Interfaz principal ===
root = tk.Tk()
root.withdraw()

pixels, intensities = cargar_imagenes()
if pixels is None:
    raise SystemExit

fig, ax = plt.subplots()
ax.plot(pixels, intensities, color='blue')
ax.set_title("Seleccionar al menos 3 picos y hacer clic en Calibrar")
ax.set_xlabel("Pixel (horizontal)")
ax.set_ylabel("Intensidad promedio (gris)")
fig.canvas.mpl_connect('button_press_event', on_click)

btn_ax1 = fig.add_axes([0.65, 0.01, 0.12, 0.05])
btn1 = MplButton(btn_ax1, "Calibrar")
btn1.on_clicked(lambda _: calibrar())

btn_ax2 = fig.add_axes([0.80, 0.01, 0.12, 0.05])
btn2 = MplButton(btn_ax2, "Limpiar")
btn2.on_clicked(lambda _: limpiar())

plt.show()
