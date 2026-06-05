import asyncio
from pathlib import Path
from src.utils.logging import logger

class UploadQueue:
    def __init__(self, backlog_ratio: int = 3):
        self.backlog_ratio = backlog_ratio

        # Creamos dos "filas de espera" independientes
        self.realtime_queue = asyncio.Queue()
        self.backlog_queue = asyncio.Queue()

        # Un contador para saber cuántos videos en vivo hemos subido seguidos
        self.realtime_counter = 0

    async def enqueue(self, segment_path: str, is_backlog: bool = False):
        """Añade un segmento de video a la fila correspondiente."""
        if is_backlog:
            await self.backlog_queue.put(segment_path)
            logger.debug(f"Añadido al historial (backlog): {segment_path}")
        else:
            await self.realtime_queue.put(segment_path)
            logger.debug(f"Añadido a fila en vivo (realtime): {segment_path}")

    async def get_next_segment(self) -> tuple[str, bool]:
        """
        Devuelve el siguiente video a subir, respetando la regla de oro:
        3 segmentos en vivo por cada 1 segmento del historial.
        Retorna: (ruta_del_archivo, es_del_historial)
        """
        # Escenario 1: Hay videos en ambas filas. Aplicamos el ratio 3:1
        if not self.realtime_queue.empty() and not self.backlog_queue.empty():
            if self.realtime_counter < self.backlog_ratio:
                self.realtime_counter += 1
                segment = await self.realtime_queue.get()
                return segment, False
            else:
                # Ya subimos 3 en vivo, toca 1 viejo
                self.realtime_counter = 0
                segment = await self.backlog_queue.get()
                return segment, True

        # Escenario 2: Solo hay videos en vivo
        if not self.realtime_queue.empty():
            self.realtime_counter += 1
            segment = await self.realtime_queue.get()
            return segment, False

        # Escenario 3: Solo hay videos viejos (internet acaba de regresar)
        if not self.backlog_queue.empty():
            self.realtime_counter = 0
            segment = await self.backlog_queue.get()
            return segment, True

        # Escenario 4: Todo está vacío, esperamos tranquilamente a que llegue un video nuevo
        self.realtime_counter += 1
        segment = await self.realtime_queue.get()
        return segment, False

    def mark_done(self, is_backlog: bool = False):
        """Le avisa al sistema que el archivo ya se subió con éxito."""
        if is_backlog:
            self.backlog_queue.task_done()
        else:
            self.realtime_queue.task_done()

    def get_sizes(self) -> dict:
        """Devuelve el tamaño actual de las filas para monitoreo de salud."""
        return {
            "realtime": self.realtime_queue.qsize(),
            "backlog": self.backlog_queue.qsize()
        }
