import os
import aioboto3
from pathlib import Path
from src.utils.logging import logger
from src.utils.retry import with_retry

class S3Uploader:
    def __init__(self, bucket: str, region: str, router_id: str, user_id: str = "default_user"):
        self.bucket = bucket
        self.region = region
        self.router_id = router_id
        self.user_id = user_id
        # Inicializamos la sesión asíncrona de aioboto3
        self.session = aioboto3.Session()

    def _get_s3_key(self, camera_id: str, filename: str) -> str:
        """
        Construye la ruta (prefijo) del archivo dentro del bucket S3.
        El PRD pide esta estructura: {user_id}/{router_id}/{camera_id}/archivo
        """
        return f"{self.user_id}/{self.router_id}/{camera_id}/{filename}"

    # Reintentamos hasta 5 veces si el internet se corta durante la subida
    @with_retry(max_retries=5, base_delay=2.0)
    async def upload_segment(self, local_path: str, camera_id: str) -> str:
        """Sube un segmento de video (.ts) a S3."""
        path = Path(local_path)
        if not path.exists():
            raise FileNotFoundError(f"El segmento no existe en disco: {local_path}")

        s3_key = self._get_s3_key(camera_id, path.name)
        logger.debug(f"Subiendo segmento {path.name} a S3...")

        # Conexión a AWS y subida del archivo
        async with self.session.client('s3', region_name=self.region) as s3_client:
            await s3_client.upload_file(
                Filename=str(path),
                Bucket=self.bucket,
                Key=s3_key,
                # Le avisamos a AWS que es un archivo de video HLS
                ExtraArgs={'ContentType': 'video/MP2T'}
            )

        s3_url = f"s3://{self.bucket}/{s3_key}"
        logger.info(f"Segmento subido exitosamente: {s3_url}")
        return s3_url

    # Aplicamos el mismo retry para la lista de reproducción
    @with_retry(max_retries=5, base_delay=2.0)
    async def upload_playlist(self, local_path: str, camera_id: str) -> str:
        """Sube el archivo de índice playlist (.m3u8)."""
        path = Path(local_path)
        if not path.exists():
            raise FileNotFoundError(f"El playlist no existe en disco: {local_path}")

        s3_key = self._get_s3_key(camera_id, path.name)

        async with self.session.client('s3', region_name=self.region) as s3_client:
            await s3_client.upload_file(
                Filename=str(path),
                Bucket=self.bucket,
                Key=s3_key,
                ExtraArgs={
                    # Este Content-Type es fundamental para los .m3u8
                    'ContentType': 'application/vnd.apple.mpegurl',
                    # Evitamos que AWS guarde versiones viejas en caché
                    'CacheControl': 'max-age=1'
                }
            )

        logger.debug(f"Playlist actualizado en S3: {s3_key}")
        return s3_key
