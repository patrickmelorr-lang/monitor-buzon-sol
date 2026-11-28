"""Lectura/escritura del Excel de registro y del estado anti-duplicados.

- vistos.json es la fuente de verdad de "ya avisé esto" (no depende de que el Excel esté cerrado).
- El Excel es la vista humana. Si la contadora lo tiene abierto, las filas se encolan en
  data/pendientes.jsonl y se escriben en la siguiente corrida.
"""

from __future__ import annotations
import hashlib
import json
import re
from datetime import datetime

import openpyxl

import config

PENDIENTES = config.ESTADO_VISTOS.parent / "pendientes.jsonl"


def hacer_id(ruc: str, fecha_txt: str, asunto: str) -> str:
    asunto = re.sub(r"\s+", " ", asunto).strip()
    return hashlib.sha1(f"{ruc}|{fecha_txt}|{asunto}".encode()).hexdigest()[:12]


# ---------------- empresas ----------------
def leer_empresas(solo_activas: bool = True) -> list[dict]:
    ws = openpyxl.load_workbook(config.EXCEL_REGISTRO, data_only=True)["EMPRESAS"]
    out = []
    for f in ws.iter_rows(min_row=2, values_only=True):
        if not f[2]:
            continue
        e = {"razon": f[1], "ruc": str(f[2]).strip(), "alias": f[3] or f[1], "monitorear": f[4]}
        if not solo_activas or str(e["monitorear"]).upper() in ("SÍ", "SI"):
            out.append(e)
    return out


# ---------------- estado anti-duplicados ----------------
def cargar_estado() -> dict:
    """ids: IDs ya registrados · rucs: RUC con carga inicial hecha ·
    ultimo: {ruc: último estado} (para avisar fallas solo cuando cambian) · latido: fecha del último aviso diario."""
    if config.ESTADO_VISTOS.exists():
        d = json.loads(config.ESTADO_VISTOS.read_text(encoding="utf-8"))
        return {"ids": set(d["ids"]), "rucs": set(d["rucs"]),
                "ultimo": d.get("ultimo", {}), "latido": d.get("latido", ""),
                "correos": d.get("correos", [])}       # Message-ID de correos ya avisados (Propuesta A)
    # primera vez: sembrar con los IDs que ya estén en el Excel (no marca RUC como inicializados)
    ws = openpyxl.load_workbook(config.EXCEL_REGISTRO, data_only=True)["NOTIFICACIONES"]
    return {"ids": {str(f[0]) for f in ws.iter_rows(min_row=2, values_only=True) if f[0]},
            "rucs": set(), "ultimo": {}, "latido": "", "correos": []}


def guardar_estado(estado: dict) -> None:
    config.ESTADO_VISTOS.parent.mkdir(parents=True, exist_ok=True)
    tmp = config.ESTADO_VISTOS.with_suffix(".tmp")
    datos = {k: sorted(v) if isinstance(v, set) else v for k, v in estado.items()}
    tmp.write_text(json.dumps(datos, indent=0, ensure_ascii=False), encoding="utf-8")
    tmp.replace(config.ESTADO_VISTOS)                      # escritura atómica


def leer_notificaciones(limite: int = 300) -> list[dict]:
    """Las notificaciones registradas, de la más reciente a la más antigua.
    Alimenta la tabla del panel para que la contadora vea qué llegó sin entrar a SUNAT."""
    try:
        ws = openpyxl.load_workbook(config.EXCEL_REGISTRO, data_only=True)["NOTIFICACIONES"]
    except Exception:
        return []
    filas = []
    for f in ws.iter_rows(min_row=2, values_only=True):
        if not f[0] or not f[6]:
            continue
        filas.append({
            "detectada": f[1], "empresa": f[2] or "", "buzon": f[4] or "",
            "deposito": f[5], "asunto": f[6] or "", "tipo": f[7] or "",
            "numero": f[8] or "", "etiqueta": f[9] or "", "prioridad": f[10] or "",
            "avisada": f[11] or "", "estado": f[13] or "",
        })
    filas.sort(key=lambda d: (d["deposito"] is not None, d["deposito"]), reverse=True)
    return filas[:limite]


def ultima_por_ruc() -> dict[str, dict]:
    """La notificación con fecha de depósito más reciente de cada RUC, según el Excel."""
    ws = openpyxl.load_workbook(config.EXCEL_REGISTRO, data_only=True)["NOTIFICACIONES"]
    ultimas: dict[str, dict] = {}
    for f in ws.iter_rows(min_row=2, values_only=True):
        ruc, fecha = str(f[3] or "").strip(), f[5]
        if not (ruc and isinstance(fecha, datetime) and f[6]):
            continue
        if ruc not in ultimas or fecha > ultimas[ruc]["_fecha"]:
            ultimas[ruc] = {"_fecha": fecha, "asunto": f[6], "fecha_txt": f"{fecha:%d/%m/%Y %H:%M:%S}",
                            "etiqueta": f[9] or "", "buzon": f[4] or "Notificaciones"}
    return ultimas


# ---------------- Excel ----------------
def fila_notificacion(n: dict, empresa: dict, alertada: bool) -> list:
    ahora = datetime.now()
    try:
        fecha = datetime.strptime(n["fecha_txt"], "%d/%m/%Y %H:%M:%S")
    except ValueError:
        fecha = n["fecha_txt"]
    return [n["id"], ahora, empresa["alias"], empresa["ruc"], n["buzon"], fecha, n["asunto"],
            n["tipo"], n["numero"], n["etiqueta"], n["prioridad"],
            "SÍ" if alertada else ("NO" if n.get("silenciosa") else "ERROR"),
            ahora if alertada else None, "PENDIENTE",
            "Carga inicial (sin alerta)" if n.get("silenciosa") else None]


def guardar_corrida(notifs: list[list], logs: list[list], revisiones: dict[str, tuple]) -> bool:
    """notifs/logs = filas ya armadas; revisiones = {ruc: (fecha, resultado)}.
    Devuelve True si quedó escrito en el Excel."""
    previas = []
    if PENDIENTES.exists():
        previas = [json.loads(l) for l in PENDIENTES.read_text(encoding="utf-8").splitlines() if l]
    lote = {"notifs": [], "logs": [], "revisiones": {}}
    for p in previas + [{"notifs": notifs, "logs": logs, "revisiones": revisiones}]:
        lote["notifs"] += p["notifs"]; lote["logs"] += p["logs"]; lote["revisiones"].update(p["revisiones"])

    try:
        wb = openpyxl.load_workbook(config.EXCEL_REGISTRO)
        for f in lote["notifs"]:
            wb["NOTIFICACIONES"].append([_fecha(v) for v in f])
            wb["NOTIFICACIONES"].cell(row=wb["NOTIFICACIONES"].max_row, column=6).number_format = "dd/mm/yyyy hh:mm:ss"
        for f in lote["logs"]:
            wb["LOG_REVISIONES"].append([_fecha(v) for v in f])
        ws = wb["EMPRESAS"]
        for fila in ws.iter_rows(min_row=2):
            ruc = str(fila[2].value or "").strip()
            if ruc in lote["revisiones"]:
                fecha, resultado = lote["revisiones"][ruc]
                fila[6].value, fila[7].value = _fecha(fecha), resultado
        wb.save(config.EXCEL_REGISTRO)
        PENDIENTES.unlink(missing_ok=True)
        return True
    except PermissionError:                                # Excel abierto por alguien
        PENDIENTES.parent.mkdir(parents=True, exist_ok=True)
        PENDIENTES.write_text(json.dumps(lote, default=str, ensure_ascii=False) + "\n", encoding="utf-8")
        print("[registro] Excel abierto: filas encoladas en", PENDIENTES.name)
        return False


def _fecha(v):
    if isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(\.\d+)?", v):
        return datetime.fromisoformat(v)                    # vuelve de la cola JSON como texto
    return v
