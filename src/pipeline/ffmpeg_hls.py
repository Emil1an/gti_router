import asyncio
from pathlib import Path
from src.utils.logging import logger
from src.utils.retry import with_retry

class HLSPipeline:
    def __init__(self, camera_url: str, output_dir: str, segment_duration: int = 4):
        self.camera_url = camera_url
        self.output_dir = Path(output_dir)
        self.segment_duration = segment_duration
        self.process = None
        self.is_running = False

        # Este callback (función) se usará más adelante para avisarle a AWS
        # que ya hay un nuevo pedacito de video listo para subir.
        self.on_segment_ready_callback = None

    @with_retry(max_retries=5, base_delay=2.0)
    async def start(self):
        """
        Inicia el proceso de FFmpeg para capturar el video RTSP y
        segmentarlo en archivos HLS (.ts) de 4 segundos.
        """
        # Asegurarnos de que la carpeta donde se guardarán los videos exista
        self.output_dir.mkdir(parents=True, exist_ok=True)

        playlist_path = self.output_dir / "playlist.m3u8"
        segment_path = self.output_dir / "segment_%05d.ts"

        logger.info(f"Iniciando captura HLS. Guardando en: {self.output_dir}")

        # Aquí armamos la instrucción exacta para el motor de video FFmpeg
        cmd = [
            'ffmpeg',
            '-rtsp_transport', 'tcp',        # Usar TCP para no perder calidad
            '-i', self.camera_url,           # Origen del video (URL de la cámara)
            '-c', 'copy',                    # PASSTHROUGH: No comprimir, solo copiar (ahorra 99% de CPU)
            '-f', 'hls',                     # Formato de salida: HLS
            '-hls_time', str(self.segment_duration), # Duración de cada pedacito (4s)
            '-hls_playlist_type', 'event',   # Tipo de playlist para video en vivo
            '-hls_flags', 'append_list',     # Que siga agregando a la lista, no la borre
            '-hls_segment_filename', str(segment_path),
            str(playlist_path)
        ]

        self.is_running = True

        # Arrancar FFmpeg en segundo plano
        self.process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        # Iniciamos una tarea asíncrona para leer lo que escupe FFmpeg
        # y saber si hay errores o si ya se generó un segmento.
        asyncio.create_task(self._monitor_process())

    async def _monitor_process(self):
        """Vigila a FFmpeg y avisa cuando un nuevo segmento está listo."""
        try:
            async for line in self.process.stderr:
                line_str = line.decode().strip()

                # FFmpeg imprime algo como: Opening 'data/buffer/cam-01/segment_00000.ts' for writing
                if "Opening" in line_str and ".ts" in line_str and self.on_segment_ready_callback:
                    # Partimos el texto usando las comillas simples (') para extraer la ruta exacta
                    partes = line_str.split("'")
                    if len(partes) >= 3:
                        segment_path = partes[1]
                        logger.debug(f"¡Nuevo segmento listo!: {segment_path}")

                        # Le mandamos el archivo a la fila de espera de AWS
                        # Usamos asyncio.create_task para no bloquear a FFmpeg
                        asyncio.create_task(self.on_segment_ready_callback(segment_path))

        except asyncio.CancelledError:
            pass
        finally:
            await self.process.wait()
            self.is_running = False

            if self.process.returncode != 0 and self.process.returncode != 255:
                logger.error(f"FFmpeg se cerró con código de error: {self.process.returncode}")
                raise Exception("El pipeline de video se cayó.")
            else:
                logger.info("FFmpeg detenido correctamente.")

    async def stop(self):
        """Detiene la captura de video de forma segura."""
        if self.process and self.is_running:
            logger.info("Deteniendo el pipeline de video...")
            self.process.terminate()
            await self.process.wait()
            self.is_running = False
