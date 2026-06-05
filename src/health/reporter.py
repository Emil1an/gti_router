import aiohttp
from datetime import datetime, timezone
from collections import deque
from src.utils.logging import logger
from src.health.monitor import SystemMonitor

class HealthReporter:
    def __init__(self, supabase_url: str, supabase_key: str, router_id: str):
        # Apuntamos a la tabla 'router_health'
        self.api_url = f"{supabase_url}/rest/v1/router_health"
        self.headers = {
            "apikey": supabase_key,
            "Authorization": f"Bearer {supabase_key}",
            "Content-Type": "application/json"
        }
        self.router_id = router_id
        self.monitor = SystemMonitor()

        # El PRD exige encolar máximo 1 hora de reportes si no hay internet.
        # Como enviamos 1 por minuto, 60 reportes = 1 hora.
        # deque(maxlen=60) es mágico: si llega el reporte 61, borra automáticamente el más viejo.
        self.offline_queue = deque(maxlen=60)

    async def send_report(self, app_metrics: dict = None):
        """Genera el reporte médico completo y lo envía a la base de datos."""
        if app_metrics is None:
            app_metrics = {}

        # 1. Juntamos los datos físicos con los datos del programa
        hw_metrics = self.monitor.get_metrics()
        report = {
            "router_id": self.router_id,
            "reported_at": datetime.now(timezone.utc).isoformat(),
            **hw_metrics,
            **app_metrics
        }

        # 2. Intentamos enviarlo a Supabase
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.api_url, headers=self.headers, json=report) as response:
                    if response.status in (200, 201, 204):
                        logger.debug("Signos vitales enviados exitosamente.")

                        # Si el internet regresó, aprovechamos para enviar los reportes que se habían quedado atorados
                        if self.offline_queue:
                            await self._flush_offline_queue(session)
                        return True
                    else:
                        raise Exception(f"HTTP {response.status}")

        except Exception as e:
            # ¡No hay internet! Guardamos el reporte en la memoria local para después.
            logger.warning(f"No se pudo enviar el health report: {e}. Guardando en memoria (Pendientes: {len(self.offline_queue)+1}/60)")
            self.offline_queue.append(report)
            return False

    async def _flush_offline_queue(self, session):
        """Intenta vaciar la memoria de reportes atorados."""
        logger.info(f"Intentando enviar {len(self.offline_queue)} reportes atrasados...")

        # Mientras haya reportes en la fila...
        while self.offline_queue:
            old_report = self.offline_queue[0] # Vemos el más viejo
            try:
                async with session.post(self.api_url, headers=self.headers, json=old_report) as response:
                    if response.status in (200, 201, 204):
                        # Se envió con éxito, lo sacamos de la fila
                        self.offline_queue.popleft()
                    else:
                        break # Si falla, dejamos de intentar y conservamos los que sobran
            except Exception:
                break

        if not self.offline_queue:
            logger.info("Todos los reportes atrasados fueron enviados.")
