import yaml
import os
from pathlib import Path
from src.utils.logging import logger

class ConfigError(Exception):
    """Excepción personalizada para errores de configuración."""
    pass

def load_config(config_path="config/router.yaml"):
    """
    Carga, parsea y valida el archivo YAML de configuración.
    """
    path = Path(config_path)

    # Si no existe router.yaml, intentamos usar el .example para pruebas
    if not path.exists():
        fallback_path = Path("config/router.yaml.example")
        if fallback_path.exists():
            logger.warning(f"No se encontró {config_path}. Usando archivo de ejemplo.")
            path = fallback_path
        else:
            raise ConfigError(f"No se encontró el archivo de configuración en {config_path}")

    try:
        with open(path, 'r', encoding='utf-8') as file:
            config = yaml.safe_load(file)

        _validate_config(config)
        logger.info("Configuración cargada y validada exitosamente.")
        return config

    except yaml.YAMLError as e:
        raise ConfigError(f"Error de sintaxis en el archivo YAML: {e}")

def _validate_config(config):
    """Valida que los campos obligatorios existan y tengan valores lógicos."""
    if not config:
        raise ConfigError("El archivo de configuración está vacío.")

    if 'device' not in config or 'id' not in config['device']:
        raise ConfigError("Falta la configuración de 'device.id'.")

    if 'cameras' not in config or not isinstance(config['cameras'], list):
        raise ConfigError("Debe definir al menos una cámara en una lista bajo 'cameras'.")

    # Validar rangos dictados por el PRD
    if 'hls' in config:
        seg_duration = config['hls'].get('segment_duration', 4)
        if not (2 <= seg_duration <= 8):
            raise ConfigError("segment_duration debe estar entre 2 y 8 segundos.")

# Si ejecutas este archivo directamente, hace una prueba
if __name__ == "__main__":
    try:
        cfg = load_config()
        print("ID del Router:", cfg['device']['id'])
        print("Número de cámaras:", len(cfg['cameras']))
    except Exception as e:
        print("Error:", e)
