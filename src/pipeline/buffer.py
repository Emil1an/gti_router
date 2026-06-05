import os
import asyncio
from pathlib import Path
from src.utils.logging import logger

class BufferManager:
    def __init__(self, buffer_dir: str, max_hours: int = 4, segment_duration: int = 4):
        self.buffer_dir = Path(buffer_dir)
        self.max_hours = max_hours
        self.segment_duration = segment_duration

        # Matemáticas simples:
        # Si guardamos 4 horas (14,400 segundos) y cada video dura 4 segundos...
        # 14,400 / 4 = 3,600 archivos máximos permitidos en la memoria.
        self.max_files = (max_hours * 3600) // segment_duration

    async def cleanup_old_segments(self, uploaded_files: set):
        """
        Revisa la carpeta y borra los archivos más viejos para liberar espacio,
        PERO solo borra los que ya fueron subidos a AWS exitosamente.
        """
        if not self.buffer_dir.exists():
            return

        # Busca todos los videos (.ts) y los ordena del más viejo al más nuevo
        files = sorted(self.buffer_dir.glob("*.ts"), key=os.path.getmtime)

        # Si excedimos el límite de horas (ej. más de 3,600 archivos)
        if len(files) > self.max_files:
            files_to_remove = len(files) - self.max_files
            logger.warning(f"Buffer al límite. Intentando eliminar {files_to_remove} segmentos antiguos...")

            removed = 0
            for file_path in files:
                # Si ya borramos suficientes, detenemos el ciclo
                if removed >= files_to_remove:
                    break

                # REGLA DE ORO: Solo borramos si el archivo ya se subió a AWS
                if str(file_path) in uploaded_files:
                    try:
                        file_path.unlink() # Borra físicamente el archivo del disco
                        uploaded_files.remove(str(file_path)) # Lo quita de la lista de limpieza
                        removed += 1
                        logger.debug(f"Segmento viejo eliminado del disco: {file_path.name}")
                    except Exception as e:
                        logger.error(f"Error al borrar {file_path.name}: {e}")

            # Si no pudimos borrar suficientes porque no había internet y no se han subido...
            if removed < files_to_remove:
                logger.error("¡ALERTA CRÍTICA! El disco se está llenando y hay archivos que aún no se han podido subir a la nube.")
