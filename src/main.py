import asyncio
import sys
import os
from pathlib import Path

from src.config.loader import load_config, ConfigError
from src.camera.rtsp_client import RTSPClient, RTSPConnectionError, RTSPAuthError, RTSPCodecError
from src.pipeline.ffmpeg_hls import HLSPipeline
from src.pipeline.buffer import BufferManager
from src.upload.s3_client import S3Uploader
from src.upload.queue import UploadQueue
from src.health.registration import DeviceRegistration
from src.health.reporter import HealthReporter
from src.health.watchdog import notify_watchdog
from src.utils.logging import logger

# --- NUEVAS IMPORTACIONES PTZ ---
from src.camera.ptz_control import PTZController
from src.camera.command_receiver import CommandReceiver

uploaded_files = set()

# --- TRABAJADORES DE VIDEO Y DISCO ---
async def upload_worker(uploader: S3Uploader, queue: UploadQueue, camera_id: str):
    logger.info("Upload worker iniciado. Esperando videos...")
    while True:
        try:
            segment_path, is_backlog = await queue.get_next_segment()
            await uploader.upload_segment(segment_path, camera_id)

            playlist_path = Path(segment_path).parent / "playlist.m3u8"
            if playlist_path.exists():
                await uploader.upload_playlist(str(playlist_path), camera_id)

            queue.mark_done(is_backlog)
            uploaded_files.add(str(segment_path))
        except Exception as e:
            logger.error(f"Error en upload_worker: {e}")
            await asyncio.sleep(5)

async def buffer_monitor_worker(buffer_mgr: BufferManager):
    logger.info("Monitor de almacenamiento iniciado.")
    while True:
        await asyncio.sleep(60)
        await buffer_mgr.cleanup_old_segments(uploaded_files)

# --- TRABAJADORES DE SALUD (Actualizado con PTZ) ---
async def health_worker(reporter: HealthReporter, queue: UploadQueue, ptz: PTZController):
    """Envía el reporte médico a Supabase, incluyendo la posición de la cámara."""
    logger.info("Paramédico (Health Worker) iniciado.")
    while True:
        await asyncio.sleep(60)
        queue_sizes = queue.get_sizes()

        app_metrics = {
            "realtime_queue_size": queue_sizes["realtime"],
            "backlog_queue_size": queue_sizes["backlog"],
            "rtsp_connected": True,
            "ptz_active": ptz.capabilities["supports_pan"]
        }

        # Si la cámara tiene motores, mandamos a internet hacia dónde está apuntando
        if ptz.capabilities["supports_pan"]:
            app_metrics["ptz_current_position"] = await ptz.get_position()

        await reporter.send_report(app_metrics)

async def watchdog_worker():
    logger.info("Watchdog (perro guardián) activado.")
    while True:
        notify_watchdog()
        await asyncio.sleep(15)

# --- ORQUESTADOR PRINCIPAL ---
async def main():
    logger.info("Iniciando sistema GTI Router (Fase 4 - PTZ Completo)...")

    # 1. CARGAR CONFIGURACIÓN
    try:
        config = load_config()
        router_id = config['device']['id']
        router_name = config['device']['name']

        camera_config = config['cameras'][0]
        cam_url = camera_config.get('url')
        cam_id = camera_config['camera_id']

        # Para ONVIF asumiremos IP y puerto estándar por ahora
        onvif_ip = "192.168.1.100"
        onvif_port = 80

        hls_config = config.get('hls', {})
        segment_duration = hls_config.get('segment_duration', 4)
        buffer_hours = hls_config.get('buffer_hours', 4)
        backlog_ratio = hls_config.get('backlog_ratio', 3)

        aws_config = config.get('aws', {})
        bucket = aws_config.get('bucket', 'default-bucket')
        region = aws_config.get('region', 'us-east-1')

        supabase_url = config.get('supabase', {}).get('url', 'http://localhost')
        supabase_key = os.getenv("SUPABASE_KEY", "clave_falsa")

        output_dir = f"data/buffer/{cam_id}"

    except ConfigError as e:
        logger.error(f"Error de configuración: {e}")
        sys.exit(1)

    # 2. REGISTRO EN SUPABASE
    registration = DeviceRegistration(supabase_url, supabase_key, router_id, router_name)
    try:
        await registration.register()
    except Exception:
        logger.warning("Iniciando en modo degradado (sin conexión inicial a Supabase).")

    # 3. INICIALIZAR MÓDULOS BASE
    s3_uploader = S3Uploader(bucket=bucket, region=region, router_id=router_id)
    upload_queue = UploadQueue(backlog_ratio=backlog_ratio)
    buffer_mgr = BufferManager(buffer_dir=output_dir, max_hours=buffer_hours, segment_duration=segment_duration)
    health_reporter = HealthReporter(supabase_url, supabase_key, router_id)

    # 4. INICIALIZAR SISTEMA PTZ
    ptz_controller = PTZController(ip=onvif_ip, port=onvif_port, user="usuario", password="password")
    command_receiver = CommandReceiver(supabase_url, supabase_key, router_id, ptz_controller)

    try:
        # Intentamos conectar a los motores. Si no hay cámara física en esa IP, fallará suavemente.
        await ptz_controller.connect()
    except Exception as e:
        logger.info("No se detectaron motores PTZ o la conexión ONVIF falló. Operando como cámara fija.")

    # 5. VERIFICAR LA CÁMARA (VIDEO)
    logger.info(f"Conectando a cámara: {cam_id}...")
    if camera_config['input_type'] == 'rtsp_ip':
        rtsp_client = RTSPClient(url=cam_url)
        try:
            await rtsp_client.probe()
        except (RTSPConnectionError, RTSPAuthError, RTSPCodecError) as e:
            logger.error(f"Error fatal de cámara: {e}")
            sys.exit(2)

    # 6. CONFIGURAR EL PIPELINE DE VIDEO
    pipeline = HLSPipeline(camera_url=cam_url, output_dir=output_dir, segment_duration=segment_duration)

    async def on_segment_ready(segment_path):
        await upload_queue.enqueue(segment_path, is_backlog=False)
    pipeline.on_segment_ready_callback = on_segment_ready

    # 7. ENCENDER TODOS LOS TRABAJADORES
    try:
        upload_task = asyncio.create_task(upload_worker(s3_uploader, upload_queue, cam_id))
        buffer_task = asyncio.create_task(buffer_monitor_worker(buffer_mgr))
        health_task = asyncio.create_task(health_worker(health_reporter, upload_queue, ptz_controller))
        watchdog_task = asyncio.create_task(watchdog_worker())

        # ¡Arrancamos el escuchador de comandos!
        receiver_task = asyncio.create_task(command_receiver.start_listening())

        await pipeline.start()
        logger.info("🚀 GTI Router operando al 100% con soporte PTZ. (Ctrl+C para salir)")

        while pipeline.is_running:
            await asyncio.sleep(1)

    except asyncio.CancelledError:
        logger.info("Apagando sistema...")
    except Exception as e:
        logger.error(f"Error crítico en el sistema: {e}")
        sys.exit(3)
    finally:
        await pipeline.stop()
        upload_task.cancel()
        buffer_task.cancel()
        health_task.cancel()
        watchdog_task.cancel()

        # Apagamos también el receptor de comandos
        await command_receiver.stop()
        receiver_task.cancel()

        logger.info("Apagado seguro completado.")
        sys.exit(0)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Interrupción manual (Ctrl+C).")
