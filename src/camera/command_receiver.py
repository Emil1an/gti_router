import asyncio
import aiohttp
from datetime import datetime, timezone
from src.utils.logging import logger
from src.camera.ptz_control import PTZController

class CommandReceiver:
    def __init__(self, supabase_url: str, supabase_key: str, router_id: str, ptz_controller: PTZController):
        # Apuntamos a la tabla de comandos dictada por la arquitectura
        self.api_url = f"{supabase_url}/rest/v1/router_commands"
        self.headers = {
            "apikey": supabase_key,
            "Authorization": f"Bearer {supabase_key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation"
        }
        self.router_id = router_id
        self.ptz = ptz_controller
        self.is_listening = False

    async def start_listening(self):
        """Inicia el ciclo de escucha de comandos desde Supabase en segundo plano."""
        self.is_listening = True
        logger.info("Receptor de comandos PTZ iniciado. Escuchando órdenes...")

        async with aiohttp.ClientSession() as session:
            while self.is_listening:
                try:
                    await self._poll_commands(session)
                except Exception as e:
                    logger.warning(f"Error al consultar comandos en la red: {e}")
                    await asyncio.sleep(5) # Si el WiFi falla, esperamos 5s antes de volver a intentar

                # El sistema pregunta cada 2 segundos si hay comandos nuevos
                await asyncio.sleep(2)

    async def _poll_commands(self, session):
        """Pregunta a la base de datos si hay algún comando 'pending' para este router."""
        params = {
            "router_id": f"eq.{self.router_id}",
            "status": "eq.pending",
            "order": "created_at.asc", # Ejecutar primero los comandos más viejos
            "limit": "5" # Traer máximo 5 comandos de golpe para no saturarnos
        }

        async with session.get(self.api_url, headers=self.headers, params=params) as response:
            if response.status == 200:
                commands = await response.json()
                for cmd in commands:
                    # Procesamos cada comando en un "hilo" separado para no detener la escucha
                    asyncio.create_task(self._process_command(session, cmd))

    async def _process_command(self, session, command: dict):
        """Traduce la orden de internet a un movimiento real en el motor de la cámara."""
        cmd_id = command.get("id")
        cmd_type = command.get("command_type")
        payload = command.get("payload", {})

        logger.info(f"Procesando comando PTZ recibido: {cmd_type} (ID: {cmd_id})")

        # 1. Le avisamos a internet que ya empezamos a trabajar ('processing')
        await self._update_command_status(session, cmd_id, "processing")

        try:
            # 2. Ejecutar el comando físico en la cámara dependiendo de la instrucción
            if cmd_type == "ptz_continuous":
                await self.ptz.continuous_move(
                    pan_speed=payload.get("pan", 0.0),
                    tilt_speed=payload.get("tilt", 0.0),
                    zoom_speed=payload.get("zoom", 0.0)
                )
            elif cmd_type == "ptz_stop":
                await self.ptz.stop()
            elif cmd_type == "ptz_preset":
                await self.ptz.go_to_preset(payload.get("preset_token"))
            else:
                logger.warning(f"Comando desconocido ignorado: {cmd_type}")

            # 3. Le avisamos a internet que terminamos ('completed') y le mandamos las coordenadas finales
            final_pos = await self.ptz.get_position()
            await self._update_command_status(session, cmd_id, "completed", final_pos)

        except Exception as e:
            logger.error(f"Fallo mecánico o de red ejecutando comando {cmd_id}: {e}")
            await self._update_command_status(session, cmd_id, "failed", error=str(e))

    async def _update_command_status(self, session, cmd_id: str, status: str, result: dict = None, error: str = None):
        """Actualiza el estatus del comando en la tabla de Supabase."""
        update_url = f"{self.api_url}?id=eq.{cmd_id}"
        data = {
            "status": status,
            "processed_at": datetime.now(timezone.utc).isoformat() if status == "processing" else None,
            "completed_at": datetime.now(timezone.utc).isoformat() if status in ("completed", "failed") else None
        }

        if result:
            data["result"] = result
        if error:
            data["result"] = {"error": error}

        try:
            async with session.patch(update_url, headers=self.headers, json=data) as response:
                if response.status not in (200, 204):
                    logger.debug(f"Aviso: Retraso al actualizar el comando {cmd_id} en la nube.")
        except Exception as e:
            logger.error(f"Error actualizando comando en Supabase: {e}")

    async def stop(self):
        """Apaga el receptor de manera segura."""
        self.is_listening = False
        logger.info("Receptor de comandos PTZ apagado.")
