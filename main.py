import os
import hmac
import hashlib
import json
import logging
import asyncio
from datetime import datetime
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# Configurar logging antes de cargar los módulos
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("asistente.main")

load_dotenv()

import database
import llm
import whatsapp
import router
from modulos import agenda, tickets, facturas, triaje, cobrador, alta_cliente
import conversation_summary
import knowledge_base
import gestor_mode
import client_memory
import escalado_humano
import secretaria
import captura_estructurada
import rate_limiter
import puente_claudia
import telegram_handler

scheduler = agenda.scheduler
conversation_summary.set_scheduler(scheduler)
secretaria.set_scheduler(scheduler)

# Conjunto de tareas en segundo plano en curso (captura estructurada). Guardamos una referencia
# fuerte a cada una porque asyncio solo mantiene una referencia débil a las tareas creadas con
# create_task — sin esto, el recolector de basura podría liberarlas a mitad de ejecución. Se
# auto-eliminan del conjunto en cuanto terminan (add_done_callback).
_tareas_en_segundo_plano: set = set()

def lanzar_tarea_segundo_plano(coro):
    tarea = asyncio.create_task(coro)
    _tareas_en_segundo_plano.add(tarea)
    tarea.add_done_callback(_tareas_en_segundo_plano.discard)
    return tarea

APP_NAME = os.getenv("APP_NAME", "SuperAsistente Comercial")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "pimia_secret_asistente_2026")

# Secreto de la app de Meta para validar la firma HMAC de cada webhook entrante (ver auditoría:
# sin esto, cualquiera puede falsificar mensajes de WhatsApp, incluido el número del gestor).
APP_SECRET = os.getenv("META_APP_SECRET", "")

app = FastAPI(title=APP_NAME)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def on_startup():
    modo_test = os.getenv("MODO_TEST", "false").strip().lower() == "true"
    entorno = os.getenv("ENTORNO", os.getenv("ENV", "desarrollo")).strip().lower()
    
    if modo_test:
        if entorno in ["produccion", "production"]:
            critical_msg = (
                "FATAL: El servidor no puede arrancar porque MODO_TEST=true "
                "está activado en un entorno de PRODUCCIÓN. Abortando inicio por seguridad fiscal."
            )
            logger.critical(critical_msg)
            raise RuntimeError(critical_msg)
        else:
            logger.warning(
                "\n"
                "========================================================================\n"
                "⚠️  ATENCIÓN: MODO_TEST está ACTIVADO.\n"
                "Las facturas se generarán con datos simulados, NO con extracción real de Gemini.\n"
                "Esto NUNCA debe estar activo en producción.\n"
                "========================================================================"
            )

    logger.info("Iniciando la base de datos de Asistente...")
    database.init_db()
    
    if os.getenv("MODULO_SECRETARIA", "true").strip().lower() != "false":
        from apscheduler.triggers.cron import CronTrigger
        hora_briefing = os.getenv("BRIEFING_HORA", "09:00").split(":")
        try:
            scheduler.add_job(
                secretaria.generar_briefing_diario,
                trigger=CronTrigger(hour=int(hora_briefing[0]), minute=int(hora_briefing[1])),
                id="briefing_diario",
                replace_existing=True
            )
            logger.info(f"Programado briefing diario recurrente a las {hora_briefing[0]}:{hora_briefing[1]}.")
        except Exception as e:
            logger.error(f"Error programando briefing diario: {e}")

    try:
        from apscheduler.triggers.cron import CronTrigger
        from modulos import recordatorios
        hora_rec_str = os.getenv("RECORDATORIOS_HORA", os.getenv("BRIEFING_HORA", "09:00")).strip()
        hora_rec = hora_rec_str.split(":")
        scheduler.add_job(
            recordatorios.procesar_todos_los_recordatorios,
            trigger=CronTrigger(hour=int(hora_rec[0]), minute=int(hora_rec[1])),
            id="recordatorios_diarios",
            max_instances=1,
            misfire_grace_time=3600,
            replace_existing=True
        )
        logger.info(f"Programado job diario de recordatorios automáticos a las {hora_rec[0]}:{hora_rec[1]} (max_instances=1, misfire_grace_time=3600).")
    except Exception as e:
        logger.error(f"Error programando job diario de recordatorios automáticos: {e}")

    try:
        scheduler.add_job(
            triaje.limpiar_archivos_temporales_antiguos,
            trigger="interval",
            hours=12,
            id="limpieza_temporales_triaje",
            replace_existing=True
        )
        logger.info("Programada limpieza periódica de archivos temporales de triaje (cada 12 horas).")
        await triaje.limpiar_archivos_temporales_antiguos()
    except Exception as e:
        logger.error(f"Error programando limpieza periódica de temporales: {e}")

    # Programar purga periódica de sesiones expiradas en SQLite (cada 15 minutos)
    try:
        scheduler.add_job(
            database.clear_expired_sessions,
            trigger="interval",
            minutes=15,
            id="purga_sesiones_expiradas",
            replace_existing=True
        )
        logger.info("Programada purga periódica de sesiones expiradas en SQLite (cada 15 minutos).")
    except Exception as e:
        logger.error(f"Error programando purga periódica de sesiones expiradas: {e}")

    # Programar revisión periódica de la carpeta puente (lo que Claudia deja listo para enviar)
    try:
        intervalo_puente = int(os.getenv("PUENTE_CLAUDIA_INTERVALO_MINUTOS", "10"))
        scheduler.add_job(
            puente_claudia.revisar_carpeta_salida,
            trigger="interval",
            minutes=intervalo_puente,
            id="revisar_carpeta_puente_claudia",
            max_instances=1,
            replace_existing=True
        )
        logger.info(f"Programada revisión periódica de la carpeta puente cada {intervalo_puente} minutos.")
    except Exception as e:
        logger.error(f"Error programando la revisión de la carpeta puente: {e}")

    # Bot de Telegram (canal de pruebas, en paralelo a WhatsApp). No bloqueante: initialize/
    # start/start_polling se integran en el mismo bucle de eventos que usa uvicorn.
    try:
        await telegram_handler.iniciar_bot_telegram()
    except Exception as e:
        logger.error(f"Error iniciando el bot de Telegram: {e}")


@app.on_event("shutdown")
async def on_shutdown():
    await telegram_handler.detener_bot_telegram()


@app.get("/")
def read_root():
    return {"status": "online", "message": f"{APP_NAME} en marcha y operativo."}

@app.get("/webhook")
def verify_webhook(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        logger.info("✅ WEBHOOK VALIDADO POR META")
        return Response(content=str(challenge), media_type="text/plain")
    
    return Response(content="Error de validación", status_code=403)

async def procesar_flujo_mensaje(phone_number: str, content: str, msg_type: str) -> str:
    """
    Orquesta la respuesta del bot decidiendo a qué módulo derivar el mensaje de forma asíncrona.
    """
    # Nota de voz de WhatsApp (Fase 8.2): se descarga, se transcribe con Gemini y el texto
    # resultante se reprocesa como si el cliente lo hubiera escrito, para heredar automáticamente
    # todo el enrutado existente (alta de cliente, triaje, tickets, agenda, intención, captura
    # estructurada) sin duplicar lógica.
    if msg_type == "audio":
        media_id = content
        storage_ruta = os.getenv("STORAGE_RUTA", "./storage")
        temp_filepath = os.path.join(storage_ruta, "temp", f"audio_{phone_number}_{int(datetime.now().timestamp())}.ogg")

        logger.info(f"Descargando nota de voz de WhatsApp Media ID: {media_id}...")
        if not await whatsapp.download_whatsapp_media(media_id, temp_filepath):
            return "No he podido descargar el audio que has enviado. Inténtalo de nuevo."

        try:
            transcripcion = await captura_estructurada.transcribir_audio(temp_filepath, mime_type="audio/ogg")
        finally:
            # En un finally para que el archivo se borre también si la transcripción se
            # cancela o falla de una forma que un simple except Exception no cubriría.
            try:
                if os.path.exists(temp_filepath):
                    os.remove(temp_filepath)
            except Exception as e:
                logger.error(f"Error eliminando audio temporal {temp_filepath}: {e}")

        if not transcripcion:
            return "No he podido entender el audio que has enviado. ¿Puedes escribirlo o repetirlo, por favor?"

        logger.info(f"Audio de {phone_number} transcrito: {transcripcion[:100]}...")
        # Sustituye el placeholder '[Envía Nota de Voz]' guardado al llegar el audio por el
        # texto real, para que el historial conserve el contenido en turnos futuros.
        database.actualizar_ultimo_mensaje_usuario(phone_number, transcripcion)
        lanzar_tarea_segundo_plano(
            captura_estructurada.generar_captura_estructurada(phone_number, transcripcion, "whatsapp_audio")
        )
        return await procesar_flujo_mensaje(phone_number, transcripcion, "text")

    # Documento de WhatsApp (PDF, Word, Excel, etc.) — Maira no lo interpreta, lo sube a la
    # carpeta puente para que Claudia lo recoja y lo incorpore al expediente del cliente.
    if msg_type == "document":
        media_id = content.get("id")
        nombre_original = content.get("filename") or f"documento_{int(datetime.now().timestamp())}"
        mime_type = content.get("mime_type", "application/octet-stream")
        storage_ruta = os.getenv("STORAGE_RUTA", "./storage")
        temp_filepath = os.path.join(storage_ruta, "temp", f"puente_entrada_{phone_number}_{int(datetime.now().timestamp())}_{nombre_original}")

        logger.info(f"Descargando documento de WhatsApp Media ID: {media_id} ({nombre_original})...")
        if not await whatsapp.download_whatsapp_media(media_id, temp_filepath):
            return "No he podido descargar el documento que has enviado. Inténtalo de nuevo."

        try:
            with open(temp_filepath, "rb") as f:
                contenido_bytes = f.read()
        finally:
            try:
                if os.path.exists(temp_filepath):
                    os.remove(temp_filepath)
            except Exception as e:
                logger.error(f"Error eliminando temporal de documento entrante {temp_filepath}: {e}")

        await puente_claudia.enviar_a_carpeta_puente(phone_number, contenido_bytes, nombre_original, mime_type)
        lanzar_tarea_segundo_plano(
            captura_estructurada.generar_captura_estructurada(
                phone_number, f"[El cliente ha enviado un documento: {nombre_original}]", "whatsapp_documento"
            )
        )
        return f"He recibido tu documento '{nombre_original}'. Lo hemos enviado a nuestro equipo de gestión para que lo revise y lo incorpore a tu expediente. Te avisaremos en cuanto esté procesado."

    history = database.get_history(phone_number, limit=5)
    
    # Flujo de ALTA DE CLIENTE activo
    if alta_cliente.esta_en_alta(phone_number):
        logger.info(f"Derivando mensaje de {phone_number} a sesión activa de ALTA DE CLIENTE.")
        return await alta_cliente.gestionar_alta(phone_number, content)

    # Flujo de TRIAJE activo
    if triaje.esta_en_triaje(phone_number):
        logger.info(f"Derivando mensaje de {phone_number} a sesión activa de TRIAJE.")
        return await triaje.gestionar_triaje(phone_number, content, msg_type)
        
    # Flujo de TICKETS activo (esperando confirmación de datos extraídos)
    if tickets.esta_en_ticket(phone_number):
        logger.info(f"Derivando mensaje de {phone_number} a sesión activa de TICKETS.")
        return await tickets.gestionar_confirmacion_ticket(phone_number, content)
        
    # Flujo de AGENDA activo (esperando elección de opción)
    if agenda.esta_en_oferta(phone_number):
        logger.info(f"Derivando mensaje de {phone_number} a sesión activa de AGENDA.")
        res = await agenda.procesar_agenda(phone_number, content, history)
        if res is not None:
            return res

    if msg_type == "image":
        if os.getenv("MODULO_TICKETS", "true").strip().lower() != "false":
            media_id = content
            storage_ruta = os.getenv("STORAGE_RUTA", "./storage")
            temp_filepath = os.path.join(storage_ruta, "temp", f"ticket_{phone_number}_{int(datetime.now().timestamp())}.jpg")
            
            logger.info(f"Descargando imagen de WhatsApp Media ID: {media_id}...")
            if await whatsapp.download_whatsapp_media(media_id, temp_filepath):
                return await tickets.procesar_mensaje_imagen(phone_number, temp_filepath)
            else:
                return "No he podido descargar la imagen que has enviado. Inténtalo de nuevo."
        else:
            return "Lo siento, el módulo de registro de tickets no está habilitado."

    intent = await router.detectar_intencion(content)
    
    intenciones_requieren_identificacion = ["AGENDA", "FACTURA", "TICKET", "TRIAJE", "EXPEDIENTE"]
    if intent in intenciones_requieren_identificacion:
        cliente_info = client_memory.get_cliente(phone_number)
        if not cliente_info or not cliente_info.get("nombre"):
            logger.info(f"Cliente {phone_number} solicita {intent} sin estar registrado. Activando alta_cliente...")
            return alta_cliente.iniciar_alta(phone_number, intent, content)

    res_agenda = None
    if intent == "AGENDA":
        res_agenda = await agenda.procesar_agenda(phone_number, content, history)
        if res_agenda is not None:
            return res_agenda
        intent = "CHAT"
        
    if intent == "TICKET":
        return "Para registrar un ticket de gasto, por favor envíame directamente la foto del ticket."
        
    elif intent == "FACTURA":
        return await facturas.procesar_solicitud_factura(phone_number, content)
        
    elif intent == "TRIAJE":
        return await triaje.gestionar_triaje(phone_number, content, msg_type)
        
    elif intent == "EXPEDIENTE":
        expedientes = database.get_expedientes_by_phone(phone_number)
        if not expedientes:
            contexto_adicional = "El cliente ha solicitado el estado de sus trámites o expediente, pero la base de datos muestra que no tiene ningún expediente registrado a su nombre. Explícale esto de forma amable en tu tono comercial."
            try:
                return await llm.generate_response(content, history, phone_number, contexto_adicional=contexto_adicional, raise_on_error=True)
            except Exception as e:
                logger.error(f"Error generando respuesta de expediente vacío con Gemini: {e}")
                return "Actualmente no consta ningún trámite o expediente abierto a tu nombre en nuestro sistema. Si crees que se trata de un error, por favor ponte en contacto con nosotros."
        else:
            lista_str = "\n".join([f"• {exp['titulo']} — {exp['estado'].replace('_', ' ').capitalize()}" for exp in expedientes])
            contexto_adicional = f"""El cliente ha solicitado el estado de sus trámites o expedientes.
Aquí tienes la lista real de sus expedientes registrada en SQLite:
{lista_str}

Instrucción: Genera una respuesta amigable en tu tono comercial informándole detalladamente del estado de cada expediente listado.
"""
            try:
                return await llm.generate_response(content, history, phone_number, contexto_adicional=contexto_adicional, raise_on_error=True)
            except Exception as e:
                logger.error(f"Error generando respuesta de expediente con Gemini (activando fallback estructurado): {e}")
                return f"""Estos son los trámites que tenemos abiertos a tu nombre:

{lista_str}

(Disculpa, ahora mismo no puedo darte más detalle, pero estos son los datos que tenemos)"""

    elif intent == "COBRADOR":
        return await llm.generate_response(content, history, phone_number)
        
    else:  # CHAT
        return await llm.generate_response(content, history, phone_number)

@app.post("/webhook")
async def receive_message(request: Request):
    try:
        # Validación de firma HMAC de Meta (evita que cualquiera pueda falsificar mensajes
        # entrantes, incluida una suplantación del número del gestor con privilegios completos).
        signature_header = request.headers.get("X-Hub-Signature-256")
        raw_body = await request.body()

        if not APP_SECRET:
            logger.error("Falta definir META_APP_SECRET en el .env. No se puede validar el webhook.")
            raise HTTPException(status_code=500, detail="Error de configuración interna.")

        if not signature_header or not signature_header.startswith("sha256="):
            logger.warning("Webhook rechazado: firma de Meta faltante o malformada.")
            raise HTTPException(status_code=403, detail="Firma de webhook faltante o malformada")

        expected_signature = signature_header.split("sha256=")[1]
        computed_signature = hmac.new(
            APP_SECRET.encode('utf-8'), raw_body, hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(computed_signature, expected_signature):
            logger.warning("Webhook rechazado: la firma no coincide.")
            raise HTTPException(status_code=403, detail="Verificación de firma de Meta fallida")

        body = json.loads(raw_body.decode('utf-8'))

        if body.get("object") == "whatsapp_business_account":
            for entry in body.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    if "messages" in value:
                        for message in value["messages"]:
                            phone_number = message.get("from")
                            msg_type = message.get("type")
                            
                            content = ""
                            if msg_type == "text":
                                content = message.get("text", {}).get("body", "")
                            elif msg_type == "image":
                                content = message.get("image", {}).get("id", "")
                            elif msg_type == "audio":
                                content = message.get("audio", {}).get("id", "")
                            elif msg_type == "document":
                                content = message.get("document", {})

                            if not content:
                                continue

                            if not rate_limiter.permitido(f"webhook:{phone_number}", max_peticiones=20, ventana_segundos=60):
                                logger.warning(f"Mensaje de {phone_number} descartado por límite de tasa.")
                                continue

                            logger.info(f"Mensaje recibido de {phone_number} [Tipo: {msg_type}]")

                            if msg_type == "text" and phone_number == os.getenv("GESTOR_WHATSAPP"):
                                respuesta_gestor = await gestor_mode.procesar_comando(phone_number, content)
                                if respuesta_gestor is not None:
                                    await whatsapp.send_whatsapp_message(phone_number, respuesta_gestor)
                                    continue

                            client_memory.registrar_visita(phone_number)

                            # Representación siempre-string de lo recibido, para todo lo que espera texto
                            # (guardado en historial, detección de despedida/escalado). 'content' en sí puede
                            # ser un dict para msg_type == "document" (id, filename, mime_type de WhatsApp).
                            if msg_type == "text":
                                content_texto = content
                            elif msg_type == "image":
                                content_texto = "[Envía Imagen]"
                            elif msg_type == "audio":
                                content_texto = "[Envía Nota de Voz]"
                            elif msg_type == "document":
                                content_texto = f"[Documento: {content.get('filename', 'sin nombre')}]"
                            else:
                                content_texto = ""

                            database.save_message(phone_number, "user", content_texto)

                            escalado_humano.resolver_ticket_si_despedida(phone_number, content_texto)
                            conversation_summary.registrar_actividad(phone_number)

                            ai_response = await procesar_flujo_mensaje(phone_number, content, msg_type)

                            database.save_message(phone_number, "assistant", ai_response)
                            await whatsapp.send_whatsapp_message(phone_number, ai_response)

                            if msg_type == "text":
                                lanzar_tarea_segundo_plano(
                                    captura_estructurada.generar_captura_estructurada(phone_number, content, "whatsapp_texto")
                                )

                            if escalado_humano.detectar_necesidad_escalado(ai_response):
                                await escalado_humano.crear_ticket_escalado(phone_number, content_texto, ai_response)

                            if conversation_summary.detectar_despedida(content_texto):
                                await conversation_summary.generar_y_enviar_resumen(phone_number)
            
            return {"status": "success"}
        else:
            raise HTTPException(status_code=404, detail="No es un evento de WhatsApp")

    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Error procesando webhook de WhatsApp: {e}")
        return {"status": "error"}

@app.post("/chat-web")
async def chat_web(request: Request, data: dict):
    mensaje = data.get("mensaje")
    phone_number = data.get("phone_number", "web_user")

    if not mensaje:
        raise HTTPException(status_code=400, detail="Falta el mensaje")

    cliente_ip = request.client.host if request.client else "desconocido"
    if not rate_limiter.permitido(f"chat-web:{cliente_ip}", max_peticiones=20, ventana_segundos=60):
        raise HTTPException(status_code=429, detail="Demasiadas peticiones, inténtalo de nuevo en un momento.")

    client_memory.registrar_visita(phone_number)
    database.save_message(phone_number, "user", mensaje)
    escalado_humano.resolver_ticket_si_despedida(phone_number, mensaje)
    conversation_summary.registrar_actividad(phone_number)
    
    ai_response = await procesar_flujo_mensaje(phone_number, mensaje, "text")
    database.save_message(phone_number, "assistant", ai_response)

    lanzar_tarea_segundo_plano(
        captura_estructurada.generar_captura_estructurada(phone_number, mensaje, "chat_web")
    )

    if escalado_humano.detectar_necesidad_escalado(ai_response):
        await escalado_humano.crear_ticket_escalado(phone_number, mensaje, ai_response)
        
    if conversation_summary.detectar_despedida(mensaje):
        await conversation_summary.generar_y_enviar_resumen(phone_number)
    
    return {"respuesta": ai_response}

@app.post("/cobrar")
async def lanzar_cobro(data: dict):
    telefono = data.get("telefono")
    mensaje = data.get("mensaje")
    
    if not telefono or not mensaje:
        raise HTTPException(status_code=400, detail="Falta telefono o mensaje")
        
    success = await cobrador.lanzar_aviso_whatsapp(telefono, mensaje)
    return {"status": "success" if success else "error"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8050, reload=True)
