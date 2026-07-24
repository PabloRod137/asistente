import asyncio
import time
import logging

logger = logging.getLogger("gemini_limiter")

class GeminiRateLimiter:
    """
    Limitador de ritmo global y asíncrono para las llamadas a la API de Gemini.
    Garantiza que las llamadas se serialicen (Semáforo = 1) y mantengan un espaciado mínimo
    entre ejecuciones para evitar picos de RPM en el tier gratuito de Google AI Studio.
    """
    def __init__(self, delay_seconds=4.2):
        self.semaphore = asyncio.Semaphore(1)
        self.last_call_time = 0.0
        self.delay_seconds = delay_seconds

    async def __aenter__(self):
        await self.semaphore.acquire()
        elapsed = time.time() - self.last_call_time
        if elapsed < self.delay_seconds:
            wait_time = self.delay_seconds - elapsed
            # logger.info(f"Gemini Rate Limiter: Espaciando llamada por {wait_time:.2f}s...")
            await asyncio.sleep(wait_time)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.last_call_time = time.time()
        self.semaphore.release()

# Instancia global compartida para todo el bot Maira
limiter = GeminiRateLimiter(delay_seconds=4.2)
