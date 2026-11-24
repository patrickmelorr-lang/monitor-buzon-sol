"""Panel de control del Monitor Buzón SOL — para la contadora.

  • Botón para revisar AHORA las empresas marcadas (por defecto, todas).
  • Lista de empresas con casillas: se elige cuáles analizar.
  • Botón CANCELAR: corta la revisión en curso y cierra Chrome.
  • Modo AUTOMÁTICO cada cierto tiempo (mientras el panel esté abierto).
  • Registro en vivo: qué empresa se está leyendo, cuándo envía Telegram, etc.

No instala nada: usa Tkinter, que viene con Python.
    python panel.py          (o doble clic en  abrir-panel.bat)
"""

from __future__ import annotations
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk

import config
import registro

ROBOT = Path(__file__).resolve().parent
PY = sys.executable
PS1 = ROBOT / "instalar_tarea.ps1"
LOCK = config.ESTADO_VISTOS.parent / "robot.lock"

INTERVALOS = {"Cada 30 minutos": 30, "Cada 1 hora": 60, "Cada 2 horas": 120}
# Estados que el robot imprime cuando una empresa no se pudo leer. No son fatales:
# el robot sigue con las demás y reintenta en la próxima vuelta.
ESTADOS_FALLA = {"LOGIN_FALLIDO", "CAPTCHA", "CAMBIO_PAGINA", "ERROR",
                 "TIMEOUT", "SESION_ACTIVA", "VENTANA_CERRADA"}
SIN_VENTANA = 0x08000000                              # CREATE_NO_WINDOW: oculta la consola negra
# Entorno para el robot. Dos cosas:
#  - PYTHONUTF8: sin esto el subproceso usa cp1252 (Windows) y revienta al imprimir acentos.
#  - Se quitan PYTHONHOME/PYTHONPATH: otro programa de la PC (p. ej. ZKBioTime) puede dejarlas
#    apuntando a SU propio Python, y entonces el nuestro carga la libreria equivocada
#    ("SRE module mismatch"). No se toca la configuracion global, solo este proceso hijo.
ENTORNO_UTF8 = {k: v for k, v in os.environ.items() if k not in ("PYTHONHOME", "PYTHONPATH")}
ENTORNO_UTF8.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})


class PanelMonitor:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.cola: queue.Queue = queue.Queue()        # puente hilo-de-trabajo → interfaz
        self.proc: subprocess.Popen | None = None
        self.corriendo = False
        self.cancelado = False
        self.fallas = 0
        self.auto = False
        self.after_auto = None
        self.empresas = self._cargar_empresas()
        self.vars_emp: dict[str, tk.BooleanVar] = {}
        self._construir()
        self.root.after(200, self._bombear_cola)

    @staticmethod
    def _cargar_empresas() -> list[dict]:
        try:
            return registro.leer_empresas(solo_activas=False)
        except Exception as e:                                   # noqa: BLE001
            messagebox.showerror("No pude leer el Excel", str(e))
            return []

    # ---------- interfaz ----------
    def _construir(self):
        self.root.title("Monitor Buzón SOL — SUNAT")
        self.root.geometry("640x760")
        self.root.minsize(560, 640)
        cont = ttk.Frame(self.root, padding=14)
        cont.pack(fill="both", expand=True)

        ttk.Label(cont, text="Monitor de Notificaciones SUNAT",
                  font=("Segoe UI", 15, "bold")).pack(anchor="w")
        ttk.Label(cont, text="Revisa el Buzón SOL y avisa por Telegram lo que llegó nuevo.",
                  foreground="#555").pack(anchor="w", pady=(0, 10))

        # --- empresas ---
        caja = ttk.LabelFrame(cont, text="Empresas a revisar", padding=8)
        caja.pack(fill="x")
        barra = ttk.Frame(caja); barra.pack(fill="x", pady=(0, 6))
        ttk.Button(barra, text="Todas", width=8,
                   command=lambda: self._marcar(True)).pack(side="left")
        ttk.Button(barra, text="Ninguna", width=8,
                   command=lambda: self._marcar(False)).pack(side="left", padx=4)
        self.lbl_sel = ttk.Label(barra, text="", foreground="#1F4E78")
        self.lbl_sel.pack(side="right")

        lienzo = tk.Canvas(caja, height=150, highlightthickness=0)
        scroll = ttk.Scrollbar(caja, orient="vertical", command=lienzo.yview)
        interior = ttk.Frame(lienzo)
        interior.bind("<Configure>",
                      lambda e: lienzo.configure(scrollregion=lienzo.bbox("all")))
        lienzo.create_window((0, 0), window=interior, anchor="nw")
        lienzo.configure(yscrollcommand=scroll.set)
        lienzo.pack(side="left", fill="x", expand=True)
        scroll.pack(side="right", fill="y")

        for i, emp in enumerate(self.empresas):
            activa = str(emp.get("monitorear", "")).upper() in ("SÍ", "SI")
            var = tk.BooleanVar(value=activa)            # por defecto: las 11 activas, marcadas
            self.vars_emp[emp["ruc"]] = var
            ttk.Checkbutton(interior, variable=var, command=self._contar,
                            text=f"{emp['alias']}  ·  {emp['ruc']}").grid(
                row=i, column=0, sticky="w", padx=4, pady=1)

        # --- acción principal ---
        fila_btn = ttk.Frame(cont); fila_btn.pack(fill="x", pady=(12, 0))
        self.btn = tk.Button(fila_btn, text="🔍  Revisar ahora", font=("Segoe UI", 13, "bold"),
                             bg="#1F4E78", fg="white", activebackground="#163a5a",
                             height=2, cursor="hand2", command=self.revisar_ahora)
        self.btn.pack(side="left", fill="x", expand=True)
        self.btn_cancel = tk.Button(fila_btn, text="⛔\nCancelar", font=("Segoe UI", 10, "bold"),
                                    bg="#9c2b2b", fg="white", activebackground="#7a2121",
                                    width=10, state="disabled", cursor="hand2",
                                    command=self.cancelar)
        self.btn_cancel.pack(side="left", padx=(8, 0), fill="y")

        # --- automático ---
        auto = ttk.LabelFrame(cont, text="Automático", padding=10)
        auto.pack(fill="x", pady=10)
        fila = ttk.Frame(auto); fila.pack(fill="x")
        self.var_auto = tk.BooleanVar(value=False)
        ttk.Checkbutton(fila, text="Revisar sola cada:", variable=self.var_auto,
                        command=self.cambiar_auto).pack(side="left")
        self.var_int = tk.StringVar(value="Cada 1 hora")
        ttk.Combobox(fila, textvariable=self.var_int, values=list(INTERVALOS), width=16,
                     state="readonly").pack(side="left", padx=8)
        self.lbl_prox = ttk.Label(auto, text="Automático: apagado", foreground="#555")
        self.lbl_prox.pack(anchor="w", pady=(8, 0))
        ttk.Label(auto, text=f"Espera máx. por empresa: {config.TIMEOUT_MS // 1000} s  ·  "
                             f"pausa entre empresas: {config.PAUSA_ENTRE_EMPRESAS_S} s",
                  foreground="#888").pack(anchor="w")

        otras = ttk.Frame(cont); otras.pack(fill="x")
        ttk.Button(otras, text="Probar Telegram", command=self.probar_telegram).pack(side="left")
        ttk.Button(otras, text="Seguir aunque cierre ▸ Windows",
                   command=self.instalar_windows).pack(side="left", padx=6)
        ttk.Button(otras, text="Apagar Windows", command=self.apagar_windows).pack(side="left")

        self.estado = ttk.Label(cont, text="Listo.", font=("Segoe UI", 10, "bold"))
        self.estado.pack(anchor="w", pady=(12, 2))
        self.lbl_ultima = ttk.Label(cont, text="Última revisión: —", foreground="#555")
        self.lbl_ultima.pack(anchor="w")

        self.log = scrolledtext.ScrolledText(cont, height=12, font=("Consolas", 9),
                                             state="disabled", bg="#111", fg="#d6d6d6")
        self.log.pack(fill="both", expand=True, pady=(8, 0))
        self.root.protocol("WM_DELETE_WINDOW", self._cerrar)
        self._contar()

    def _marcar(self, valor: bool):
        for v in self.vars_emp.values():
            v.set(valor)
        self._contar()

    def _contar(self):
        self.lbl_sel.config(text=f"{len(self.seleccionadas())} de {len(self.vars_emp)} marcadas")

    def seleccionadas(self) -> list[str]:
        return [ruc for ruc, v in self.vars_emp.items() if v.get()]

    def _log(self, txt: str):
        self.log.config(state="normal")
        self.log.insert("end", txt + "\n")
        self.log.see("end")
        self.log.config(state="disabled")

    # ---------- revisar ahora ----------
    def revisar_ahora(self):
        if self.corriendo:
            return
        rucs = self.seleccionadas()
        if not rucs:
            messagebox.showinfo("Sin empresas", "Marca al menos una empresa para revisar.")
            return
        self.corriendo, self.cancelado, self.fallas = True, False, 0
        self.btn.config(state="disabled", text="Revisando…")
        self.btn_cancel.config(state="normal")
        self.estado.config(text=f"Revisando {len(rucs)} empresa(s)…")
        self._log(f"── {datetime.now():%H:%M:%S}  inicio ({len(rucs)} empresas) ──")
        threading.Thread(target=self._correr, args=(rucs,), daemon=True).start()

    def _correr(self, rucs: list[str]):
        # Si están TODAS marcadas se manda el barrido completo (así sale el resumen diario);
        # si es un subconjunto, se pasan los RUC elegidos.
        args = [PY, "-u", str(ROBOT / "robot.py"), "--visible"]
        if len(rucs) < len(self.vars_emp):
            args += ["--rucs", ",".join(rucs)]
        try:
            self.proc = subprocess.Popen(args, cwd=str(ROBOT), stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                         errors="replace", env=ENTORNO_UTF8,
                                         creationflags=SIN_VENTANA)
            for linea in self.proc.stdout:
                self.cola.put(("log", linea.rstrip()))
            self.proc.wait()
            self.cola.put(("fin", self.proc.returncode))
        except Exception as e:                               # noqa: BLE001
            self.cola.put(("log", f"ERROR al lanzar el robot: {e}"))
            self.cola.put(("fin", -1))

    def cancelar(self):
        if not (self.corriendo and self.proc):
            return
        self.cancelado = True
        self._log("⛔ cancelando… (cerrando Chrome)")
        try:
            # /T mata también a Chrome, que es hijo del robot; si no, quedaría abierto.
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(self.proc.pid)],
                           creationflags=SIN_VENTANA, capture_output=True)
        except Exception as e:                               # noqa: BLE001
            self._log(f"No pude cerrar del todo: {e}")
        LOCK.unlink(missing_ok=True)                         # el robot murió sin soltar el candado

    def _fin(self, code: int):
        self.corriendo = False
        self.proc = None
        self.btn.config(state="normal", text="🔍  Revisar ahora")
        self.btn_cancel.config(state="disabled")
        self.lbl_ultima.config(text=f"Última revisión: {datetime.now():%d/%m %H:%M}")
        if self.cancelado:
            self.estado.config(text="Cancelado por el usuario.")
            self._log("── cancelado ──")
        elif self.fallas:
            # Importante para la contadora: que una empresa no cargue NO rompe nada.
            self.estado.config(
                text=f"Terminó. {self.fallas} empresa(s) no cargaron — es normal.")
            self._log(f"── fin · {self.fallas} empresa(s) no cargaron ──")
            self._log("   Es normal: SUNAT a veces va lento o pide captcha.")
            self._log("   El monitor NO se detuvo y las reintenta en la próxima revisión.")
            self._log("   Si una falla varias veces seguidas: márcala SOLA y dale Revisar.")
        else:
            self.estado.config(text="Listo, todas revisadas. Revisa Telegram."
                               if code == 0 else "Terminó con avisos (mira el registro).")
            self._log(f"── fin (código {code}) ──")
        if self.auto and not self.cancelado:
            self._programar()

    # ---------- automático en el panel ----------
    def cambiar_auto(self):
        self.auto = self.var_auto.get()
        if self.auto:
            self._programar()
            if not self.corriendo:
                self.revisar_ahora()                         # una corrida ya, sin esperar el ciclo
        elif self.after_auto:
            self.root.after_cancel(self.after_auto)
            self.after_auto = None
            self.lbl_prox.config(text="Automático: apagado")

    def _programar(self):
        if self.after_auto:
            self.root.after_cancel(self.after_auto)
        mins = INTERVALOS[self.var_int.get()]
        self.after_auto = self.root.after(mins * 60_000, self._tic_auto)
        self.lbl_prox.config(
            text=f"Próxima automática: {datetime.now() + timedelta(minutes=mins):%H:%M}")

    def _tic_auto(self):
        if self.corriendo:
            self._programar()                                # ocupado: reprograma sin encimar
        else:
            self.revisar_ahora()

    # ---------- otras acciones ----------
    def probar_telegram(self):
        def hilo():
            r = subprocess.run([PY, "-u", str(ROBOT / "robot.py"), "--prueba-telegram"],
                               cwd=str(ROBOT), capture_output=True, text=True, encoding="utf-8",
                               errors="replace", env=ENTORNO_UTF8, creationflags=SIN_VENTANA)
            self.cola.put(("log", (r.stdout or r.stderr).strip()))
        threading.Thread(target=hilo, daemon=True).start()

    def _ps(self, args: list[str], ok: str):
        try:
            subprocess.run(["powershell", "-ExecutionPolicy", "Bypass", "-File", str(PS1), *args],
                           cwd=str(ROBOT), creationflags=SIN_VENTANA, check=False)
            self._log(ok)
        except Exception as e:                               # noqa: BLE001
            self._log(f"No se pudo: {e}")

    def instalar_windows(self):
        mins = INTERVALOS[self.var_int.get()]
        self._ps(["-Minutos", str(mins)],
                 f"Tarea de Windows activada: cada {mins} min, sigue aunque cierres el panel.")

    def apagar_windows(self):
        self._ps(["-Quitar"], "Tarea de Windows apagada.")

    # ---------- bucle ----------
    def _bombear_cola(self):
        try:
            while True:
                tipo, dato = self.cola.get_nowait()
                if tipo == "log":
                    if dato.strip().split(" ")[0] in ESTADOS_FALLA:
                        self.fallas += 1
                    self._log(dato)
                else:
                    self._fin(dato)
        except queue.Empty:
            pass
        self.root.after(200, self._bombear_cola)

    def _cerrar(self):
        if self.corriendo and not messagebox.askyesno(
                "Revisión en curso", "Hay una revisión trabajando. ¿Cerrar igual?"):
            return
        if self.corriendo:
            self.cancelar()
        self.root.destroy()


if __name__ == "__main__":
    raiz = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    PanelMonitor(raiz)
    raiz.mainloop()
