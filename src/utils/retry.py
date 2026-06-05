import asyncio
from functools import wraps
from src.utils.logging import logger

def with_retry(max_retries=10, base_delay=1.0, max_delay=60.0):
    """
    Decorador asíncrono para reintentar operaciones que fallan,
    usando backoff exponencial (1s, 2s, 4s, 8s... hasta max_delay).
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            delay = base_delay

            for attempt in range(max_retries):
                try:
                    # Intenta ejecutar la función
                    return await func(*args, **kwargs)
                except Exception as e:
                    # Si es el último intento, lanza el error para que el sistema principal decida qué hacer
                    if attempt == max_retries - 1:
                        logger.error(f"Fallo definitivo en {func.__name__} tras {max_retries} intentos. Error: {e}")
                        raise

                    # Registra la advertencia y espera antes del siguiente intento
                    logger.warning(f"Error en {func.__name__}: {e}. Reintentando en {delay}s (Intento {attempt + 1}/{max_retries})")
                    await asyncio.sleep(delay)

                    # Duplica el tiempo de espera, pero sin pasarse del límite máximo
                    delay = min(delay * 2, max_delay)

        return wrapper
    return decorator
