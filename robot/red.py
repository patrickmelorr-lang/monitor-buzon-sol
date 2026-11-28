"""Confianza en certificados para redes de oficina.

Muchas empresas (y varios antivirus) inspeccionan el tráfico HTTPS: abren la conexión,
la revisan y la vuelven a firmar con un certificado propio. Windows confía en ese
certificado porque está instalado en el equipo, pero Python trae su propia lista y no
lo conoce. El síntoma es:

    self signed certificate in chain

Este módulo hace que Python confíe EN LO MISMO que confía Windows. No baja la seguridad:
sigue verificando el certificado, solo que ahora contra el almacén del sistema, que es
donde está el certificado legítimo de la empresa.

Nunca se desactiva la verificación: estaríamos enviando datos tributarios sin comprobar
con quién hablamos.
"""
from __future__ import annotations

_estado = None


def preparar() -> str:
    """Se llama una vez al arrancar. Devuelve una descripción de lo que se activó."""
    global _estado
    if _estado is not None:
        return _estado
    try:
        import truststore
        truststore.inject_into_ssl()
        _estado = "almacen de certificados de Windows"
    except ImportError:
        _estado = "certificados propios de Python (truststore no instalado)"
    except Exception as e:                                  # noqa: BLE001
        _estado = f"certificados propios de Python ({type(e).__name__})"
    return _estado


def diagnostico(host: str = "api.telegram.org") -> tuple[bool, str]:
    """Comprueba si se puede abrir una conexión segura. Para el botón de diagnóstico
    del panel: distingue 'no hay internet' de 'el antivirus intercepta'."""
    import socket
    import ssl
    preparar()
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, 443), timeout=10) as s:
            with ctx.wrap_socket(s, server_hostname=host) as ss:
                emisor = dict(x[0] for x in ss.getpeercert().get("issuer", []))
                return True, f"conexion segura verificada (emisor: {emisor.get('organizationName', '?')})"
    except ssl.SSLCertVerificationError as e:
        return False, ("El antivirus o la red de la oficina esta interceptando la conexion y "
                       "Python no reconoce su certificado. Instalar 'truststore' lo resuelve. "
                       f"Detalle: {e.verify_message or e}")
    except socket.timeout:
        return False, "Sin respuesta: puede no haber internet o un cortafuegos bloquea la salida."
    except Exception as e:                                  # noqa: BLE001
        return False, f"{type(e).__name__}: {str(e)[:160]}"
