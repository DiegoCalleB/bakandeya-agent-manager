"""
Paquete `lib` — clientes de servicios externos (Sheets, Gmail, IA, Telegram).

Al importar cualquier módulo de `lib`, este `__init__` se ejecuta primero y hace que Python
use el **almacén de certificados del sistema operativo** (Windows) en lugar del bundle de
`certifi`. Es imprescindible en máquinas tras un proxy de inspección TLS corporativo (Zscaler,
Netskope, etc.): ese proxy re-firma el tráfico HTTPS con una CA propia que está instalada en
Windows pero NO en `certifi`, así que sin esto las conexiones a Google Sheets, Gemini o Gmail
fallan de forma intermitente con `CERTIFICATE_VERIFY_FAILED` cuando el proxy está activo.

`truststore.inject_into_ssl()` debe llamarse ANTES de crear cualquier conexión SSL; por eso vive
aquí, en el import del paquete, y no dentro de una función.
"""

try:
    import truststore

    truststore.inject_into_ssl()
except (ImportError, AttributeError):
    # Sin truststore instalado o si hay incompatibilidad de urllib3, se usa certifi.
    pass
