import asyncio
from onvif import ONVIFCamera
from src.utils.logging import logger

# Definimos excepciones personalizadas para los motores
class PTZConnectionError(Exception): pass
class PTZCommandError(Exception): pass

class PTZController:
    def __init__(self, ip: str, port: int, user: str, password: str, timeout: int = 5):
        self.ip = ip
        self.port = port
        self.user = user
        self.password = password
        self.timeout = timeout

        self.camera = None
        self.ptz_service = None
        self.media_service = None
        self.profile_token = None

        # Guardaremos de qué es capaz esta cámara
        self.capabilities = {
            "supports_pan": False,
            "supports_tilt": False,
            "supports_zoom": False,
            "supports_presets": False,
            "preset_count": 0
        }

    async def connect(self):
        """Se conecta a la cámara y descubre sus capacidades físicas."""
        logger.info(f"Conectando a ONVIF PTZ en {self.ip}:{self.port}...")
        try:
            # Ejecutamos la conexión síncrona en un hilo separado para no bloquear el video
            self.camera = await asyncio.to_thread(
                ONVIFCamera, self.ip, self.port, self.user, self.password
            )

            # Obtenemos los servicios de Media y PTZ
            self.media_service = self.camera.create_media_service()
            self.ptz_service = self.camera.create_ptz_service()

            # Necesitamos el 'token' del perfil principal para saber a qué lente mover
            profiles = await asyncio.to_thread(self.media_service.GetProfiles)
            if not profiles:
                raise PTZConnectionError("La cámara no tiene perfiles de video configurados.")
            self.profile_token = profiles[0].token

            # Evaluamos las capacidades (si la cámara nos devuelve una configuración PTZ)
            if profiles[0].PTZConfiguration:
                self.capabilities["supports_pan"] = True
                self.capabilities["supports_tilt"] = True
                # Revisamos si soporta Zoom
                if hasattr(profiles[0].PTZConfiguration, 'DefaultPTZSpeed') and \
                   hasattr(profiles[0].PTZConfiguration.DefaultPTZSpeed, 'Zoom'):
                    self.capabilities["supports_zoom"] = True
                self.capabilities["supports_presets"] = True  # Asumimos soporte básico

            logger.info(f"Conexión PTZ exitosa. Capacidades: {self.capabilities}")
            return self.capabilities

        except Exception as e:
            logger.error(f"Fallo al conectar ONVIF PTZ: {e}")
            raise PTZConnectionError(f"No se pudo establecer control PTZ: {e}")

    async def continuous_move(self, pan_speed: float, tilt_speed: float, zoom_speed: float = 0.0):
        """Mueve la cámara de forma continua. Velocidades van de -1.0 a 1.0."""
        if not self.ptz_service:
            raise PTZCommandError("El servicio PTZ no está inicializado.")

        try:
            request = self.ptz_service.create_type('ContinuousMove')
            request.ProfileToken = self.profile_token
            request.Velocity = {
                'PanTilt': {'x': pan_speed, 'y': tilt_speed},
                'Zoom': {'x': zoom_speed}
            }
            await asyncio.to_thread(self.ptz_service.ContinuousMove, request)
            logger.debug(f"Moviendo continuamente (P:{pan_speed}, T:{tilt_speed}, Z:{zoom_speed})")
        except Exception as e:
            raise PTZCommandError(f"Error en movimiento continuo: {e}")

    async def stop(self):
        """Detiene cualquier movimiento actual inmediatamente."""
        if not self.ptz_service:
            return

        try:
            request = self.ptz_service.create_type('Stop')
            request.ProfileToken = self.profile_token
            request.PanTilt = True
            request.Zoom = True
            await asyncio.to_thread(self.ptz_service.Stop, request)
            logger.debug("Movimiento PTZ detenido.")
        except Exception as e:
            raise PTZCommandError(f"Error al detener PTZ: {e}")

    async def absolute_move(self, pan_pos: float, tilt_pos: float, zoom_pos: float = 0.0):
        """Mueve la cámara a una coordenada exacta."""
        if not self.ptz_service:
            raise PTZCommandError("Servicio PTZ no inicializado.")

        try:
            request = self.ptz_service.create_type('AbsoluteMove')
            request.ProfileToken = self.profile_token
            request.Position = {
                'PanTilt': {'x': pan_pos, 'y': tilt_pos},
                'Zoom': {'x': zoom_pos}
            }
            await asyncio.to_thread(self.ptz_service.AbsoluteMove, request)
            logger.debug(f"Movimiento absoluto a (P:{pan_pos}, T:{tilt_pos}, Z:{zoom_pos})")
        except Exception as e:
            raise PTZCommandError(f"Error en movimiento absoluto: {e}")

    async def relative_move(self, pan_delta: float, tilt_delta: float, zoom_delta: float = 0.0):
        """Mueve la cámara sumando coordenadas relativas a su posición actual."""
        if not self.ptz_service:
            raise PTZCommandError("Servicio PTZ no inicializado.")

        try:
            request = self.ptz_service.create_type('RelativeMove')
            request.ProfileToken = self.profile_token
            request.Translation = {
                'PanTilt': {'x': pan_delta, 'y': tilt_delta},
                'Zoom': {'x': zoom_delta}
            }
            await asyncio.to_thread(self.ptz_service.RelativeMove, request)
            logger.debug(f"Movimiento relativo por (P:{pan_delta}, T:{tilt_delta}, Z:{zoom_delta})")
        except Exception as e:
            raise PTZCommandError(f"Error en movimiento relativo: {e}")

    async def get_position(self) -> dict:
        """Pregunta a la cámara dónde está apuntando actualmente."""
        if not self.ptz_service:
            return {}

        try:
            request = self.ptz_service.create_type('GetStatus')
            request.ProfileToken = self.profile_token
            status = await asyncio.to_thread(self.ptz_service.GetStatus, request)

            return {
                "pan": status.Position.PanTilt.x if status.Position.PanTilt else 0.0,
                "tilt": status.Position.PanTilt.y if status.Position.PanTilt else 0.0,
                "zoom": status.Position.Zoom.x if status.Position.Zoom else 0.0
            }
        except Exception as e:
            logger.warning(f"No se pudo obtener la posición: {e}")
            return {}

    async def get_presets(self):
        """Obtiene la lista de posiciones pre-guardadas en la cámara."""
        if not self.ptz_service:
            return []

        try:
            request = self.ptz_service.create_type('GetPresets')
            request.ProfileToken = self.profile_token
            presets = await asyncio.to_thread(self.ptz_service.GetPresets, request)
            self.capabilities["preset_count"] = len(presets) if presets else 0
            return [{"token": p.token, "name": p.Name} for p in presets] if presets else []
        except Exception as e:
            logger.warning(f"No se pudieron obtener presets: {e}")
            return []

    async def go_to_preset(self, preset_token: str):
        """Mueve la cámara a una posición pre-guardada."""
        if not self.ptz_service:
            raise PTZCommandError("Servicio PTZ no inicializado.")

        try:
            request = self.ptz_service.create_type('GotoPreset')
            request.ProfileToken = self.profile_token
            request.PresetToken = preset_token
            await asyncio.to_thread(self.ptz_service.GotoPreset, request)
            logger.debug(f"Moviendo a preset {preset_token}")
        except Exception as e:
            raise PTZCommandError(f"Error al mover al preset: {e}")
