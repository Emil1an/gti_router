import aiohttp
from src.utils.logging import logger
from src.utils.retry import with_retry

class DeviceRegistration:
    def __init__(self, supabase_url: str, supabase_key: str, device_id: str, device_name: str):
        # Configuramos la URL para apuntar a la tabla "routers" mediante REST API
        self.api_url = f"{supabase_url}/rest/v1/routers"
        self.device_id = device_id
        self.device_name = device_name
        self.firmware_version = "0.1.0"

        # Cabeceras obligatorias para hablar con Supabase
        self.headers = {
            "apikey": supabase_key,
            "Authorization": f"Bearer {supabase_key}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates" # Esto significa UPSERT (Si no existe, créalo; si existe, actualízalo)
        }

    # Intentaremos registrarnos 5 veces. Si Supabase está caído, no importa, el Router debe seguir grabando.
    @with_retry(max_retries=5, base_delay=3.0)
    async def register(self):
        """Registra el dispositivo en Supabase al momento de encender."""
        logger.info(f"Registrando router '{self.device_name}' en Supabase...")

        # Los datos que mandaremos a la tabla 'routers'
        payload = {
            # En la versión final, el device_id debería ser un UUID válido
            # "router_id": self.device_id,
            "device_name": self.device_name,
            "firmware_version": self.firmware_version,
            "status": "online"
        }

        try:
            # Hacemos la petición POST de forma asíncrona
            async with aiohttp.ClientSession() as session:
                async with session.post(self.api_url, headers=self.headers, json=payload) as response:
                    # Supabase devuelve 200, 201 o 204 cuando todo sale bien
                    if response.status not in (200, 201, 204):
                        error_text = await response.text()
                        raise Exception(f"Error HTTP {response.status}: {error_text}")

                    logger.info("✅ Registro en Supabase exitoso. ¡El router está en línea!")
                    return True
        except Exception as e:
            logger.warning(f"No se pudo contactar a Supabase: {e}")
            raise
# Bloque de prueba (solo se ejecuta si corres este archivo directamente)
if __name__ == "__main__":
    import asyncio

    async def test_registro():
        logger.info("Iniciando prueba de registro...")

        # Le pasamos datos falsos para forzar un error de red
        registro = DeviceRegistration(
            supabase_url="https://url-inventada-que-no-existe.supabase.co",
            supabase_key="clave-falsa-123",
            device_id="router-norte-001",
            device_name="Router de Prueba"
        )

        try:
            await registro.register()
        except Exception as e:
            logger.error(f"La prueba terminó con el error esperado: {e}")

    # Ejecutamos la prueba asíncrona
    asyncio.run(test_registro())
