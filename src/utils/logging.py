import logging
import sys

def setup_logger(name="gti_router", level=logging.INFO):
    """
    Configura y retorna el logger principal del sistema.
    Formato: {timestamp} [{level}] [{module}] {message}
    """
    logger = logging.getLogger(name)

    # Evitar agregar múltiples handlers si se llama varias veces
    if not logger.handlers:
        logger.setLevel(level)

        # Crear el formato requerido por el PRD
        formatter = logging.Formatter(
            '%(asctime)s [%(levelname)s] [%(module)s] %(message)s'
        )

        # Configurar para que imprima en la consola
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger

# Instancia global por defecto
logger = setup_logger()
