import psutil
from src.utils.logging import logger

class SystemMonitor:
    def __init__(self, temp_threshold=80.0):
        self.temp_threshold = temp_threshold

    def get_metrics(self) -> dict:
        """Recolecta los signos vitales del dispositivo físico."""

        # 1. Uso de CPU
        cpu_percent = psutil.cpu_percent(interval=0.5)

        # 2. Uso de Memoria RAM
        ram = psutil.virtual_memory()
        memory_percent = ram.percent

        # 3. Uso del Disco Duro (tarjeta SD)
        # Usamos '/' en Linux/Raspberry, pero para pruebas en Windows usamos 'C:\\'
        disk_path = '/' if hasattr(psutil, "POSIX") and psutil.POSIX else 'C:\\'
        disk = psutil.disk_usage(disk_path)
        disk_percent = disk.percent

        # 4. Temperatura (Solo funciona en Linux/Raspberry Pi)
        temperature = self._get_temperature()

        # Alertamos si la temperatura está por las nubes
        if temperature and temperature >= self.temp_threshold:
            logger.warning(f"¡ALERTA TÉRMICA! Temperatura en {temperature}°C")

        return {
            "cpu_percent": cpu_percent,
            "memory_percent": memory_percent,
            "disk_percent": disk_percent,
            "temperature_celsius": temperature
        }

    def _get_temperature(self):
        """Intenta leer el sensor de temperatura. Falla silenciosamente en Windows."""
        try:
            # Esta es la ruta típica de los sensores en Linux/Raspberry Pi
            temps = psutil.sensors_temperatures()
            if not temps:
                return None

            # En la Raspberry Pi, el CPU se llama 'cpu_thermal'
            if 'cpu_thermal' in temps:
                return temps['cpu_thermal'][0].current
            # Si es otra computadora Linux, agarramos el primer sensor que encuentre
            else:
                return list(temps.values())[0][0].current
        except Exception:
            # Si estamos en Windows (como ahorita en tu máquina), esto no funciona
            return None

# Bloque de prueba
if __name__ == "__main__":
    monitor = SystemMonitor()
    metricas = monitor.get_metrics()
    print("--- Signos Vitales ---")
    print(f"CPU: {metricas['cpu_percent']}%")
    print(f"RAM: {metricas['memory_percent']}%")
    print(f"Disco: {metricas['disk_percent']}%")
    print(f"Temperatura: {metricas['temperature_celsius']}°C")
