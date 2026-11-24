"""Reglas de negocio: qué tipo de documento es y qué tan urgente es."""

from __future__ import annotations
import re

RE_TIPO_NUM = re.compile(
    r"Notificaci[oó]n\s+(?:de\s+)?(?P<tipo>.+?)\s+N\s*\.?\s*[°º]\s*(?P<num>\d[\dA-Z-]{5,})", re.I)   # incluye Esquelas: 003577020267E1600

# Etiquetas de color que pone SUNAT en el buzón (ver hoja ETIQUETAS del Excel)
PRIORIDAD_POR_ETIQUETA = {
    "RESOLUCIONES DE EJECUCIÓN COACTIVA": "ALTA",
    "RESOLUCIONES DE COBRANZA": "ALTA",
    "VALORES": "ALTA",
    "RESOLUCIONES DE FISCALIZACION": "ALTA",
    "ÓRDENES DE PAGO": "ALTA",
    "RESOLUCIONES DE FRACCIONAMIENTO": "MEDIA",
    "RESOLUCIONES NO CONTENCIOSAS": "MEDIA",
    "AVISOS": "BAJA",
    "NOTIFICACIONES ANTERIORES": "BAJA",
}

# Palabras del asunto que por sí solas indican urgencia (embargo, cobranza, multas...)
PALABRAS_URGENTES = ("coactiva", "embargo", "retención a terceros", "multa",
                     "determinación", "orden de pago", "requerimiento", "fiscalización")


def tipo_y_numero(asunto: str) -> tuple[str, str]:
    m = RE_TIPO_NUM.search(asunto)
    if not m:
        return "", ""
    return m.group("tipo").strip(" -"), m.group("num")


def prioridad(etiqueta: str, asunto: str) -> str:
    """Devuelve "ALTA", "MEDIA" o "BAJA" para una notificación.

    etiqueta: texto de la etiqueta de color de SUNAT, en MAYÚSCULAS (puede venir vacío "").
    asunto:   texto completo del asunto, p. ej.
              "Notificación Resolución Coactiva Retención a Terceros N° 0300071919581"
    """
    # TODO(human): decidir cómo combinar etiqueta y asunto.
    return "MEDIA"   # provisional: reemplazar por tu regla
