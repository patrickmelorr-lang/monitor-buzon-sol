"""Panel del Monitor de Notificaciones SUNAT — Grupo Zaragoza Constructora.

Interfaz de escritorio para contabilidad. Sin consola, sin comandos y sin íconos
decorativos: la información se distingue por color, tipografía y posición.

    python panel.py          (o doble clic en  abrir-panel.bat)
"""
from __future__ import annotations

import os
import queue
import re
import subprocess
import sys
import threading
import tkinter as tk
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import messagebox

import ttkbootstrap as tb
from ttkbootstrap.style import ThemeDefinition

import config
import red
import registro

ROBOT = Path(__file__).resolve().parent
RECURSOS = ROBOT / "recursos"
PY = sys.executable
PS1 = ROBOT / "instalar_tarea.ps1"
LOCK = config.ESTADO_VISTOS.parent / "robot.lock"
TAREA = "Monitor Buzon SOL SUNAT"

SIN_VENTANA = 0x08000000
ENTORNO = {k: v for k, v in os.environ.items() if k not in ("PYTHONHOME", "PYTHONPATH")}
ENTORNO.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})

# Identidad visual tomada del logotipo de Grupo Zaragoza.
AZUL, ORO, GRIS = "#061E40", "#AD8A41", "#5D6167"
MARCA = {
    "primary": AZUL, "secondary": GRIS, "success": "#1E7B4D", "info": "#2D6CA8",
    "warning": ORO, "danger": "#A4262C", "light": "#F4F5F7", "dark": AZUL,
    "bg": "#FFFFFF", "fg": "#1B2430", "selectbg": AZUL, "selectfg": "#FFFFFF",
    "border": "#D6DAE0", "inputfg": "#1B2430", "inputbg": "#FFFFFF", "active": "#E8EBEF",
}

# Cómo se presenta cada estado del robot a una persona de contabilidad.
ESTADOS = {
    "OK":             ("Revisada",            "ok"),
    "VACIO":          ("Sin notificaciones",  "ok"),
    "SIN_CONFIRMAR":  ("No se pudo verificar", "duda"),
    "CAPTCHA":        ("SUNAT pidió verificación", "falla"),
    "LOGIN_FALLIDO":  ("Clave rechazada",     "falla"),
    "SESION_ACTIVA":  ("Sesión abierta en SUNAT", "espera"),
    "TIMEOUT":        ("SUNAT no respondió",  "espera"),
    "CAMBIO_PAGINA":  ("No se halló el buzón", "falla"),
    "VENTANA_CERRADA": ("Ventana cerrada",    "espera"),
    "ERROR":          ("Error",               "falla"),
}
INTERVALOS = {"Cada 30 minutos": 30, "Cada hora": 60, "Cada 2 horas": 120, "Cada 4 horas": 240}


class Panel:
    def __init__(self, raiz: tb.Window):
        self.raiz = raiz
        self.cola: queue.Queue = queue.Queue()
        self.proc: subprocess.Popen | None = None
        self.corriendo = False
        self.cancelado = False
        self.auto_panel = False
        self.after_auto = None
        self.filas_emp: dict[str, str] = {}      # ruc -> id de fila en la tabla
        self.marcadas: dict[str, bool] = {}
        self.total_paso = 0
        self.hecho_paso = 0
        self.imagenes: list = []                 # evita que el recolector borre los PNG
        self.empresas = self._cargar_empresas()
        self._construir()
        self.raiz.after(150, self._bombear)
        self._refrescar_notificaciones()
        self._refrescar_estado_tarea()
        self._revisar_telegram()

    # ───────────────────────── datos ─────────────────────────
    @staticmethod
    def _cargar_empresas() -> list[dict]:
        try:
            return registro.leer_empresas(solo_activas=False)
        except Exception as e:                               # noqa: BLE001
            messagebox.showerror("No pude leer el Excel", str(e))
            return []

    # ─────────────────────── construcción ────────────────────
    def _construir(self):
        self.raiz.title("Monitor de Notificaciones SUNAT — Grupo Zaragoza")
        self.raiz.geometry("1060x700")
        self.raiz.minsize(900, 600)
        ico = RECURSOS / "app.ico"
        if ico.exists():
            try:
                self.raiz.iconbitmap(str(ico))
            except Exception:
                pass

        self._cabecera()
        self._barra_acciones()

        self.nb = tb.Notebook(self.raiz, bootstyle="primary")
        self.nb.pack(fill="both", expand=True, padx=16, pady=(10, 0))
        self._pestana_empresas()
        self._pestana_notificaciones()
        self._pestana_automatico()
        self._pestana_tecnico()
        self._barra_estado()
        self.raiz.protocol("WM_DELETE_WINDOW", self._cerrar)

    def _cabecera(self):
        cab = tk.Frame(self.raiz, bg=AZUL, height=78)
        cab.pack(fill="x")
        cab.pack_propagate(False)
        logo = RECURSOS / "logo-panel.png"
        if logo.exists():
            try:
                img = tk.PhotoImage(file=str(logo))
                self.imagenes.append(img)
                tk.Label(cab, image=img, bg=AZUL).pack(side="left", padx=(18, 14))
            except Exception:
                pass
        txt = tk.Frame(cab, bg=AZUL)
        txt.pack(side="left", pady=14)
        tk.Label(txt, text="MONITOR DE NOTIFICACIONES SUNAT", bg=AZUL, fg="#FFFFFF",
                 font=("Segoe UI Semibold", 15)).pack(anchor="w")
        tk.Label(txt, text="Grupo Zaragoza Constructora", bg=AZUL, fg=ORO,
                 font=("Segoe UI", 10)).pack(anchor="w")

        der = tk.Frame(cab, bg=AZUL)
        der.pack(side="right", padx=18)
        self.lbl_tg = tk.Label(der, text="Telegram: comprobando", bg=AZUL, fg="#C9D1DB",
                               font=("Segoe UI", 9))
        self.lbl_tg.pack(anchor="e", pady=(0, 2))
        self.lbl_reloj = tk.Label(der, text="", bg=AZUL, fg="#8A97A8", font=("Segoe UI", 9))
        self.lbl_reloj.pack(anchor="e")
        self._tic_reloj()

    def _tic_reloj(self):
        self.lbl_reloj.config(text=datetime.now().strftime("%d/%m/%Y  %H:%M"))
        self.raiz.after(30_000, self._tic_reloj)

    def _barra_acciones(self):
        barra = tb.Frame(self.raiz, padding=(16, 12, 16, 0))
        barra.pack(fill="x")
        self.btn = tb.Button(barra, text="Revisar ahora", bootstyle="primary",
                             width=18, command=self.revisar_ahora)
        self.btn.pack(side="left")
        self.btn_stop = tb.Button(barra, text="Detener", bootstyle="danger-outline",
                                  width=12, state="disabled", command=self.cancelar)
        self.btn_stop.pack(side="left", padx=8)

        self.lbl_progreso = tb.Label(barra, text="", bootstyle="secondary")
        self.lbl_progreso.pack(side="right")
        self.barra_prog = tb.Progressbar(barra, bootstyle="primary", length=260, maximum=100)
        self.barra_prog.pack(side="right", padx=12)

    def _pestana_empresas(self):
        p = tb.Frame(self.nb, padding=12)
        self.nb.add(p, text="  Empresas  ")
        sup = tb.Frame(p)
        sup.pack(fill="x", pady=(0, 8))
        tb.Button(sup, text="Marcar todas", bootstyle="secondary-outline", width=14,
                  command=lambda: self._marcar(True)).pack(side="left")
        tb.Button(sup, text="Desmarcar todas", bootstyle="secondary-outline", width=16,
                  command=lambda: self._marcar(False)).pack(side="left", padx=6)
        tb.Label(sup, text="Haga clic en una empresa para incluirla o excluirla de la revisión.",
                 bootstyle="secondary").pack(side="left", padx=14)
        self.lbl_marcadas = tb.Label(sup, text="", bootstyle="primary")
        self.lbl_marcadas.pack(side="right")

        cols = ("rev", "empresa", "ruc", "estado", "lista", "nuevas", "ultima")
        self.tv_emp = tb.Treeview(p, columns=cols, show="headings", bootstyle="primary")
        for c, t, w, a in [
            ("rev", "Revisar", 70, "center"), ("empresa", "Empresa", 150, "w"),
            ("ruc", "RUC", 110, "center"), ("estado", "Estado", 190, "w"),
            ("lista", "En buzón", 85, "center"), ("nuevas", "Nuevas", 75, "center"),
            ("ultima", "Última revisión", 150, "center"),
        ]:
            self.tv_emp.heading(c, text=t)
            self.tv_emp.column(c, width=w, anchor=a, stretch=(c == "estado"))
        sb = tb.Scrollbar(p, orient="vertical", command=self.tv_emp.yview, bootstyle="primary-round")
        self.tv_emp.configure(yscrollcommand=sb.set)
        self.tv_emp.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        self.tv_emp.tag_configure("ok", foreground="#1E7B4D")
        self.tv_emp.tag_configure("duda", foreground="#9A6B00", background="#FFF8E6")
        self.tv_emp.tag_configure("falla", foreground="#A4262C", background="#FDF0F0")
        self.tv_emp.tag_configure("espera", foreground=GRIS)
        self.tv_emp.tag_configure("curso", foreground=AZUL, background="#EEF2F8")
        self.tv_emp.tag_configure("nuevas", foreground="#8A5A00", background="#FFF4D6")

        for e in self.empresas:
            activa = str(e.get("monitorear", "")).upper() in ("SÍ", "SI")
            self.marcadas[e["ruc"]] = activa
            fid = self.tv_emp.insert("", "end", values=(
                "Sí" if activa else "No", e["alias"], e["ruc"], "—", "", "", "—"))
            self.filas_emp[e["ruc"]] = fid
        self.tv_emp.bind("<Button-1>", self._clic_empresa)
        self._contar()

        # Rueda del mouse: el Treeview ya la maneja, pero se fuerza por si el foco está fuera.
        self.tv_emp.bind("<MouseWheel>",
                         lambda ev: self.tv_emp.yview_scroll(-1 * (ev.delta // 120), "units"))

    def _pestana_notificaciones(self):
        p = tb.Frame(self.nb, padding=12)
        self.nb.add(p, text="  Notificaciones  ")
        sup = tb.Frame(p)
        sup.pack(fill="x", pady=(0, 8))
        tb.Label(sup, text="Notificaciones depositadas por SUNAT, de la más reciente a la más antigua.",
                 bootstyle="secondary").pack(side="left")
        tb.Button(sup, text="Actualizar", bootstyle="secondary-outline", width=12,
                  command=self._refrescar_notificaciones).pack(side="right")

        cols = ("prio", "empresa", "deposito", "tipo", "numero", "detectada", "estado")
        self.tv_not = tb.Treeview(p, columns=cols, show="headings", bootstyle="primary")
        for c, t, w, a in [
            ("prio", "Prioridad", 85, "center"), ("empresa", "Empresa", 120, "w"),
            ("deposito", "Depositada por SUNAT", 160, "center"), ("tipo", "Documento", 260, "w"),
            ("numero", "Número", 150, "w"), ("detectada", "Detectada", 140, "center"),
            ("estado", "Estado", 110, "center"),
        ]:
            self.tv_not.heading(c, text=t)
            self.tv_not.column(c, width=w, anchor=a, stretch=(c == "tipo"))
        sb = tb.Scrollbar(p, orient="vertical", command=self.tv_not.yview, bootstyle="primary-round")
        self.tv_not.configure(yscrollcommand=sb.set)
        self.tv_not.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tv_not.tag_configure("ALTA", foreground="#A4262C")
        self.tv_not.tag_configure("MEDIA", foreground="#8A5A00")
        self.tv_not.tag_configure("BAJA", foreground=GRIS)
        self.tv_not.bind("<MouseWheel>",
                         lambda ev: self.tv_not.yview_scroll(-1 * (ev.delta // 120), "units"))
        self.tv_not.bind("<Double-1>", self._ver_asunto)

    def _pestana_automatico(self):
        p = tb.Frame(self.nb, padding=18)
        self.nb.add(p, text="  Automático  ")

        caja = tb.Labelframe(p, text=" Revisión automática ", padding=16, bootstyle="primary")
        caja.pack(fill="x")
        fila = tb.Frame(caja)
        fila.pack(fill="x")
        self.var_auto = tk.BooleanVar(value=False)
        tb.Checkbutton(fila, text="Activada", variable=self.var_auto, bootstyle="round-toggle",
                       command=self._cambiar_auto_windows).pack(side="left")
        tb.Label(fila, text="    Revisar cada").pack(side="left")
        self.var_int = tk.StringVar(value="Cada hora")
        self.cb_int = tb.Combobox(fila, textvariable=self.var_int, width=18,
                                  values=list(INTERVALOS))
        self.cb_int.pack(side="left", padx=8)
        tb.Label(fila, text="(puede escribir los minutos: 45)",
                 bootstyle="secondary").pack(side="left")

        self.lbl_tarea = tb.Label(caja, text="", bootstyle="secondary", justify="left")
        self.lbl_tarea.pack(anchor="w", pady=(14, 0))
        tb.Label(caja, justify="left", bootstyle="secondary",
                 text=("Sigue funcionando aunque cierre esta ventana.\n"
                       "Requiere la computadora encendida y su sesión de Windows iniciada.\n"
                       "No funciona con la computadora apagada.")).pack(anchor="w", pady=(10, 0))

        caja2 = tb.Labelframe(p, text=" Mientras el panel está abierto ", padding=16,
                              bootstyle="secondary")
        caja2.pack(fill="x", pady=14)
        self.var_auto_panel = tk.BooleanVar(value=False)
        tb.Checkbutton(caja2, text="Repetir la revisión mientras esta ventana siga abierta",
                       variable=self.var_auto_panel, bootstyle="round-toggle",
                       command=self._cambiar_auto_panel).pack(anchor="w")
        self.lbl_prox = tb.Label(caja2, text="Desactivada", bootstyle="secondary")
        self.lbl_prox.pack(anchor="w", pady=(8, 0))

        caja3 = tb.Labelframe(p, text=" Avisos por Telegram ", padding=16, bootstyle="secondary")
        caja3.pack(fill="x")
        f3 = tb.Frame(caja3)
        f3.pack(fill="x")
        tb.Button(f3, text="Enviar mensaje de prueba", bootstyle="secondary-outline",
                  width=24, command=self.probar_telegram).pack(side="left")
        tb.Button(f3, text="Diagnosticar conexión", bootstyle="secondary-outline",
                  width=22, command=self._revisar_telegram).pack(side="left", padx=8)
        self.lbl_tg2 = tb.Label(caja3, text="", bootstyle="secondary", wraplength=820,
                                justify="left")
        self.lbl_tg2.pack(anchor="w", pady=(12, 0))

    def _pestana_tecnico(self):
        p = tb.Frame(self.nb, padding=12)
        self.nb.add(p, text="  Detalle técnico  ")
        tb.Label(p, text="Registro detallado de la última revisión. Útil para soporte.",
                 bootstyle="secondary").pack(anchor="w", pady=(0, 8))
        marco = tb.Frame(p)
        marco.pack(fill="both", expand=True)
        self.log = tk.Text(marco, font=("Consolas", 9), bg="#FBFBFC", fg="#1B2430",
                           relief="flat", borderwidth=1, highlightthickness=1,
                           highlightbackground="#D6DAE0", wrap="word", state="disabled")
        sb = tb.Scrollbar(marco, orient="vertical", command=self.log.yview,
                          bootstyle="secondary-round")
        self.log.configure(yscrollcommand=sb.set)
        self.log.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

    def _barra_estado(self):
        barra = tb.Frame(self.raiz, padding=(16, 8))
        barra.pack(fill="x", side="bottom")
        self.lbl_estado = tb.Label(barra, text="Listo.", bootstyle="secondary")
        self.lbl_estado.pack(side="left")
        self.lbl_ultima = tb.Label(barra, text="", bootstyle="secondary")
        self.lbl_ultima.pack(side="right")

    # ─────────────────────── empresas ────────────────────────
    def _clic_empresa(self, ev):
        fid = self.tv_emp.identify_row(ev.y)
        if not fid or self.corriendo:
            return
        ruc = self.tv_emp.set(fid, "ruc")
        self.marcadas[ruc] = not self.marcadas.get(ruc, False)
        self.tv_emp.set(fid, "rev", "Sí" if self.marcadas[ruc] else "No")
        self._contar()

    def _marcar(self, valor: bool):
        if self.corriendo:
            return
        for ruc, fid in self.filas_emp.items():
            self.marcadas[ruc] = valor
            self.tv_emp.set(fid, "rev", "Sí" if valor else "No")
        self._contar()

    def _contar(self):
        n = sum(1 for v in self.marcadas.values() if v)
        self.lbl_marcadas.config(text=f"{n} de {len(self.marcadas)} empresas marcadas")

    def seleccionadas(self) -> list[str]:
        return [r for r, v in self.marcadas.items() if v]

    # ───────────────────────── revisión ──────────────────────
    def revisar_ahora(self):
        if self.corriendo:
            return
        rucs = self.seleccionadas()
        if not rucs:
            messagebox.showinfo("Sin empresas", "Marque al menos una empresa para revisar.")
            return
        self.corriendo, self.cancelado = True, False
        self.hecho_paso, self.total_paso = 0, len(rucs)
        self.btn.configure(state="disabled", text="Revisando…")
        self.btn_stop.configure(state="normal")
        self.barra_prog.configure(value=0)
        self.lbl_progreso.configure(text=f"0 de {len(rucs)}")
        self.lbl_estado.configure(text="Revisión en curso. No cierre las ventanas de Chrome.")
        for ruc in rucs:
            fid = self.filas_emp[ruc]
            self.tv_emp.item(fid, tags=())
            for c in ("estado", "lista", "nuevas"):
                self.tv_emp.set(fid, c, "" if c != "estado" else "En espera")
        self._log(f"───── {datetime.now():%d/%m/%Y %H:%M:%S} · inicio ({len(rucs)} empresas) ─────")
        threading.Thread(target=self._correr, args=(rucs,), daemon=True).start()

    def _correr(self, rucs: list[str]):
        args = [PY, "-u", str(ROBOT / "robot.py"), "--visible"]
        if len(rucs) < len(self.marcadas):
            args += ["--rucs", ",".join(rucs)]
        try:
            self.proc = subprocess.Popen(args, cwd=str(ROBOT), stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                         errors="replace", env=ENTORNO,
                                         creationflags=SIN_VENTANA)
            for linea in self.proc.stdout:
                self.cola.put(("linea", linea.rstrip()))
            self.proc.wait()
            self.cola.put(("fin", self.proc.returncode))
        except Exception as e:                               # noqa: BLE001
            self.cola.put(("linea", f"ERROR al lanzar el robot: {e}"))
            self.cola.put(("fin", -1))

    def cancelar(self):
        if not (self.corriendo and self.proc):
            return
        self.cancelado = True
        self._log("Cancelando: cerrando Chrome…")
        try:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(self.proc.pid)],
                           creationflags=SIN_VENTANA, capture_output=True)
        except Exception as e:                               # noqa: BLE001
            self._log(f"No pude cerrar del todo: {e}")
        LOCK.unlink(missing_ok=True)

    # ───────────────── protocolo de progreso ─────────────────
    def _evento(self, campos: list[str]):
        tipo = campos[0]
        if tipo == "EMPRESA":
            alias, ruc, i, n = campos[1], campos[2], campos[3], campos[4]
            fid = self.filas_emp.get(ruc)
            if fid:
                self.tv_emp.item(fid, tags=("curso",))
                self.tv_emp.set(fid, "estado", "Revisando…")
                self.tv_emp.see(fid)
            self.lbl_progreso.configure(text=f"{i} de {n}")
            self.lbl_estado.configure(text=f"Revisando {alias}…")
        elif tipo == "PASO":
            fid = self._fila_por_alias(campos[1])
            if fid:
                self.tv_emp.set(fid, "estado", campos[2].capitalize())
        elif tipo == "FIN_EMPRESA":
            self._fin_empresa(campos)
        elif tipo == "NOTIF":
            self.lbl_estado.configure(text=f"{campos[1]}: {campos[3]} {campos[4]}")

    def _fila_por_alias(self, alias: str) -> str | None:
        for fid in self.filas_emp.values():
            if self.tv_emp.set(fid, "empresa") == alias:
                return fid
        return None

    def _fin_empresa(self, c: list[str]):
        alias, estado, lista, nuevas, seg, intentos = c[1], c[2], c[3], c[4], c[5], c[6]
        total_sunat = c[7] if len(c) > 7 else ""
        fid = self._fila_por_alias(alias)
        texto, clase = ESTADOS.get(estado, (estado, "falla"))
        if int(nuevas or 0) > 0 and clase == "ok":
            texto, clase = f"{nuevas} notificación(es) nueva(s)", "nuevas"
        if intentos and int(intentos) > 1 and clase == "ok":
            texto += f" (tras {intentos} intentos)"
        if fid:
            self.tv_emp.item(fid, tags=(clase,))
            self.tv_emp.set(fid, "estado", texto)
            self.tv_emp.set(fid, "lista", f"{lista}/{total_sunat}" if total_sunat else lista)
            self.tv_emp.set(fid, "nuevas", nuevas if int(nuevas or 0) else "")
            self.tv_emp.set(fid, "ultima", datetime.now().strftime("%d/%m %H:%M"))
        self.hecho_paso += 1
        if self.total_paso:
            self.barra_prog.configure(value=self.hecho_paso * 100 / self.total_paso)
            self.lbl_progreso.configure(text=f"{self.hecho_paso} de {self.total_paso}")

    # ─────────────────────── fin de corrida ──────────────────
    def _fin(self, code: int):
        self.corriendo = False
        self.proc = None
        self.btn.configure(state="normal", text="Revisar ahora")
        self.btn_stop.configure(state="disabled")
        self.lbl_ultima.configure(text=f"Última revisión: {datetime.now():%d/%m/%Y %H:%M}")
        self._refrescar_notificaciones()
        if self.cancelado:
            self.lbl_estado.configure(text="Revisión cancelada.")
        else:
            dudas = sum(1 for fid in self.filas_emp.values()
                        if "duda" in self.tv_emp.item(fid, "tags")
                        or "falla" in self.tv_emp.item(fid, "tags"))
            if dudas:
                self.lbl_estado.configure(
                    text=f"Terminó. {dudas} empresa(s) quedaron sin verificar; "
                         f"se reintentan solas en la próxima revisión.")
            else:
                self.lbl_estado.configure(text="Terminó. Todas las empresas verificadas.")
        self.barra_prog.configure(value=100 if not self.cancelado else 0)
        self._log(f"───── fin ─────")
        if self.auto_panel and not self.cancelado:
            self._programar_panel()

    # ───────────────────── notificaciones ────────────────────
    def _refrescar_notificaciones(self):
        for f in self.tv_not.get_children():
            self.tv_not.delete(f)
        self._notifs = registro.leer_notificaciones()
        for n in self._notifs:
            dep = n["deposito"].strftime("%d/%m/%Y %H:%M") if isinstance(n["deposito"], datetime) \
                else str(n["deposito"] or "")
            det = n["detectada"].strftime("%d/%m %H:%M") if isinstance(n["detectada"], datetime) \
                else str(n["detectada"] or "")
            self.tv_not.insert("", "end", tags=(n["prioridad"],), values=(
                n["prioridad"], n["empresa"], dep, n["tipo"] or n["asunto"][:60],
                n["numero"], det, n["estado"]))

    def _ver_asunto(self, _ev):
        sel = self.tv_not.selection()
        if not sel:
            return
        i = self.tv_not.index(sel[0])
        if i < len(getattr(self, "_notifs", [])):
            n = self._notifs[i]
            messagebox.showinfo(
                f"{n['empresa']} — {n['tipo']}",
                f"{n['asunto']}\n\n"
                f"Número: {n['numero']}\nEtiqueta SUNAT: {n['etiqueta']}\n"
                f"Prioridad: {n['prioridad']}\n\n"
                "El documento completo se lee en el Buzón SOL de SUNAT.")

    # ──────────────────────── automático ─────────────────────
    def _minutos(self) -> int:
        v = self.var_int.get().strip()
        if v in INTERVALOS:
            return INTERVALOS[v]
        m = re.search(r"\d+", v)
        return max(15, int(m.group())) if m else 60          # mínimo 15: menos invita al captcha

    def _cambiar_auto_panel(self):
        self.auto_panel = self.var_auto_panel.get()
        if self.auto_panel:
            self._programar_panel()
            if not self.corriendo:
                self.revisar_ahora()
        elif self.after_auto:
            self.raiz.after_cancel(self.after_auto)
            self.after_auto = None
            self.lbl_prox.configure(text="Desactivada")

    def _programar_panel(self):
        if self.after_auto:
            self.raiz.after_cancel(self.after_auto)
        m = self._minutos()
        self.after_auto = self.raiz.after(m * 60_000, self._tic_panel)
        self.lbl_prox.configure(
            text=f"Próxima revisión automática: {datetime.now() + timedelta(minutes=m):%H:%M}")

    def _tic_panel(self):
        if self.corriendo:
            self._programar_panel()
        else:
            self.revisar_ahora()

    def _ps(self, args: list[str]) -> str:
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", *args],
                               cwd=str(ROBOT), capture_output=True, text=True,
                               encoding="utf-8", errors="replace", creationflags=SIN_VENTANA)
            return (r.stdout or "").strip()
        except Exception as e:                               # noqa: BLE001
            return f"ERROR {e}"

    def _refrescar_estado_tarea(self):
        salida = self._ps(["-Command",
                           f"$t=Get-ScheduledTask -TaskName '{TAREA}' -ErrorAction SilentlyContinue;"
                           f"if($t){{$i=Get-ScheduledTaskInfo -TaskName '{TAREA}';"
                           f"\"$($t.State)|$($i.NextRunTime)|$($i.LastRunTime)\"}}else{{'NINGUNA'}}"])
        if not salida or salida.startswith("ERROR") or salida == "NINGUNA":
            self.var_auto.set(False)
            self.lbl_tarea.configure(text="Estado: no configurada en este equipo.")
            return
        partes = (salida.split("|") + ["", ""])[:3]
        activa = partes[0].strip().lower() == "ready"
        self.var_auto.set(activa)
        prox = partes[1].strip() or "—"
        self.lbl_tarea.configure(
            text=(f"Estado: {'activada' if activa else 'desactivada'}    "
                  f"Próxima: {prox}    Última: {partes[2].strip() or '—'}"))

    def _cambiar_auto_windows(self):
        quiere = self.var_auto.get()
        m = self._minutos()
        if quiere:
            self._log(f"Activando revisión automática cada {m} minutos…")
            self._ps(["-File", str(PS1), "-Minutos", str(m)])
        else:
            self._log("Desactivando revisión automática…")
            self._ps(["-Command", f"Disable-ScheduledTask -TaskName '{TAREA}' "
                                  f"-ErrorAction SilentlyContinue | Out-Null"])
        self.raiz.after(900, self._refrescar_estado_tarea)

    # ───────────────────────── telegram ──────────────────────
    def _revisar_telegram(self):
        def hilo():
            ok, msg = red.diagnostico()
            self.cola.put(("tg", (ok, msg)))
        threading.Thread(target=hilo, daemon=True).start()

    def probar_telegram(self):
        def hilo():
            r = subprocess.run([PY, "-u", str(ROBOT / "robot.py"), "--prueba-telegram"],
                               cwd=str(ROBOT), capture_output=True, text=True, encoding="utf-8",
                               errors="replace", env=ENTORNO, creationflags=SIN_VENTANA)
            self.cola.put(("linea", (r.stdout or r.stderr).strip()))
            self.cola.put(("tgmsg", (r.stdout or "").strip()))
        threading.Thread(target=hilo, daemon=True).start()

    # ─────────────────────────── bucle ───────────────────────
    def _log(self, txt: str):
        self.log.configure(state="normal")
        self.log.insert("end", txt + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _bombear(self):
        try:
            while True:
                tipo, dato = self.cola.get_nowait()
                if tipo == "linea":
                    if dato.startswith("@@"):
                        try:
                            self._evento(dato[2:].split("|"))
                        except Exception as e:               # noqa: BLE001
                            self._log(f"(progreso ilegible: {e})")
                    else:
                        self._log(dato)
                elif tipo == "fin":
                    self._fin(dato)
                elif tipo == "tg":
                    ok, msg = dato
                    self.lbl_tg.configure(text="Telegram: conectado" if ok else "Telegram: con problema",
                                          fg="#9BE3B8" if ok else "#F2A6A6")
                    self.lbl_tg2.configure(text=msg)
                elif tipo == "tgmsg":
                    self.lbl_tg2.configure(text=dato)
        except queue.Empty:
            pass
        self.raiz.after(150, self._bombear)

    def _cerrar(self):
        if self.corriendo and not messagebox.askyesno(
                "Revisión en curso", "Hay una revisión trabajando. ¿Cerrar de todos modos?"):
            return
        if self.corriendo:
            self.cancelar()
        self.raiz.destroy()


def main():
    red.preparar()
    raiz = tb.Window(themename="bootstrap-light")
    estilo = tb.Style()
    estilo.register_theme(ThemeDefinition("zaragoza", MARCA, mode="light"))
    estilo.theme_use("zaragoza")
    estilo.configure("Treeview", rowheight=26)
    estilo.configure("Treeview.Heading", font=("Segoe UI Semibold", 9))
    Panel(raiz)
    raiz.mainloop()


if __name__ == "__main__":
    main()
