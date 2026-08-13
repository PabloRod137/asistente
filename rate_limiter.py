"""
Limitador de tasa simple en memoria para los endpoints públicos (/webhook, /chat-web).

No sustituye a un límite a nivel de proxy/firewall en producción, pero cierra el hueco de
"cualquiera puede mandar tráfico ilimitado" detectado en la auditoría: sin esto, no había
ningún control sobre cuántas peticiones entrantes podían llegar, solo sobre la velocidad de
las llamadas *salientes* a Gemini (gemini_limiter.py).
"""
import time
import logging
from collections import defaultdict, deque

logger = logging.getLogger(__name__)

_historial: dict[str, deque] = defaultdict(deque)


def permitido(clave: str, max_peticiones: int = 20, ventana_segundos: int = 60) -> bool:
    """
    Devuelve True si la petición identificada por `clave` (ej. un número de teléfono o una IP)
    está dentro del límite (`max_peticiones` en los últimos `ventana_segundos`), False si lo supera.
    """
    ahora = time.time()
    cola = _historial[clave]

    while cola and ahora - cola[0] > ventana_segundos:
        cola.popleft()

    if len(cola) >= max_peticiones:
        logger.warning(f"[RateLimiter] Límite superado para '{clave}': {len(cola)} peticiones en {ventana_segundos}s.")
        return False

    cola.append(ahora)
    return True
