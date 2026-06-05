import asyncio
import json
from src.utils.logging import logger
from src.utils.retry import with_retry

# Definimos nuestras propias alertas (Excepciones) por si algo sale mal
class RTSPConnectionError(Exception): pass
class RTSPAuthError(Exception): pass
class RTSPCodecError(Exception): pass

class RTSPClient:
    def __init__(self, url: str, timeout: int = 10):
        self.url = url
        self.timeout = timeout

    # Si la cámara no responde a la primera, lo intentará 3 veces antes de rendirse.
    @with_retry(max_retries=3, base_delay=2.0)
    async def probe(self):
        """
        Se conecta a la cámara usando ffprobe para verificar que el video existe
        y obtener sus datos (resolución, codec, etc).
        """
        logger.info(f"Iniciando probe (prueba de conexión) a: {self.url}")

        # Armamos el comando de ffprobe para leer la cámara por TCP
        # Nota: El timeout en ffprobe se mide en microsegundos, por eso multiplicamos por 1,000,000
        cmd = [
            'ffprobe',
            '-v', 'quiet',
            '-print_format', 'json',
            '-show_streams',
            '-select_streams', 'v:0',  # Solo queremos el video, no el audio
            '-rtsp_transport', 'tcp',  # TCP es más seguro y pierde menos paquetes que UDP
            '-timeout', str(self.timeout * 1000000),
            self.url
        ]

        try:
            # Ejecutamos el comando de forma asíncrona para no congelar la Raspberry
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            # Esperamos la respuesta de la cámara
            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                error_msg = stderr.decode().strip()
                if "401" in error_msg or "Unauthorized" in error_msg:
                    raise RTSPAuthError("Usuario o contraseña incorrectos para la cámara.")
                raise RTSPConnectionError(f"No se pudo conectar a la cámara: {error_msg}")

            # Leemos el JSON que nos devolvió la cámara
            data = json.loads(stdout.decode())
            if not data.get('streams'):
                raise RTSPCodecError("Se conectó a la cámara, pero no se encontró ningún stream de video.")

            stream = data['streams'][0]

            metadata = {
                'codec': stream.get('codec_name'),
                'width': stream.get('width'),
                'height': stream.get('height'),
                'fps': eval(stream.get('r_frame_rate', '0/1')) # Convierte '30/1' a 30.0
            }

            logger.info(f"Cámara conectada exitosamente. Metadata: {metadata}")
            return metadata

        except FileNotFoundError:
            logger.error("FFmpeg no está instalado en el sistema. Se requiere para capturar video.")
            raise
        except json.JSONDecodeError:
            raise RTSPCodecError("La cámara devolvió información ilegible.")

# Bloque de prueba (solo se ejecuta si corres este archivo directamente)
if __name__ == "__main__":
    async def test_cam():
        # Esta es una URL de prueba genérica, obviamente fallará si no hay cámara
        cam = RTSPClient("rtsp://admin:admin123@192.168.1.100:554/stream1")
        try:
            await cam.probe()
        except Exception as e:
            print(f"Error esperado en la prueba: {e}")

    asyncio.run(test_cam())
