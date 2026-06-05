from src.utils.logging import logger

# Intentamos importar la librería del sistema operativo Linux (systemd)
try:
    from systemd.daemon import notify
    HAS_SYSTEMD = True
except ImportError:
    # Si estamos en Windows (o no está instalada), apagamos el perro guardián silenciosamente
    HAS_SYSTEMD = False

def notify_watchdog():
    """
    Envía el latido (heartbeat) a systemd.
    Le dice al sistema operativo de la Raspberry: "¡Sigo vivo, no me reinicies!"
    """
    if HAS_SYSTEMD:
        try:
            # Esta es la instrucción mágica que el PRD pide para calmar al watchdog
            notify("WATCHDOG=1")
        except Exception as e:
            logger.debug(f"Error enviando latido al watchdog: {e}")
