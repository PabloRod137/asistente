import os
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

scheduler = agenda.scheduler
conversation_summary.set_scheduler(scheduler)
secretaria.set_scheduler(scheduler)

APP_NAME = os.getenv("APP_NAME", "SuperAsistente Comercial")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "pimia_secret_asistente_2026")

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
    
    intenciones_requieren_identificacion = ["AGENDA", "FACTURA", "TICKET", "TRIAJE"]
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
        
    elif intent == "COBRADOR":
        return await llm.generate_response(content, history, phone_number)
        
    else:  # CHAT
        return await llm.generate_response(content, history, phone_number)

@app.post("/webhook")
async def receive_message(request: Request):
    try:
        body = await request.json()
        
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
                                
                            if not content:
                                continue
                                
                            logger.info(f"Mensaje recibido de {phone_number} [Tipo: {msg_type}]")
                            
                            if phone_number == os.getenv("GESTOR_WHATSAPP"):
                                respuesta_gestor = await gestor_mode.procesar_comando(phone_number, content)
                                if respuesta_gestor is not None:
                                    await whatsapp.send_whatsapp_message(phone_number, respuesta_gestor)
                                    continue
                            
                            client_memory.registrar_visita(phone_number)
                            
                            if msg_type == "text":
                                database.save_message(phone_number, "user", content)
                            elif msg_type == "image":
                                database.save_message(phone_number, "user", "[Envía Imagen]")
                                
                            escalado_humano.resolver_ticket_si_despedida(phone_number, content)
                            conversation_summary.registrar_actividad(phone_number)
                            
                            ai_response = await procesar_flujo_mensaje(phone_number, content, msg_type)
                            
                            database.save_message(phone_number, "assistant", ai_response)
                            await whatsapp.send_whatsapp_message(phone_number, ai_response)
                            
                            if escalado_humano.detectar_necesidad_escalado(ai_response):
                                escalado_humano.crear_ticket_escalado(phone_number, content, ai_response)
                            
                            if conversation_summary.detectar_despedida(content):
                                await conversation_summary.generar_y_enviar_resumen(phone_number)
            
            return {"status": "success"}
        else:
            raise HTTPException(status_code=404, detail="No es un evento de WhatsApp")
            
    except Exception as e:
        logger.error(f"Error procesando webhook de WhatsApp: {e}")
        return {"status": "error"}

@app.post("/chat-web")
async def chat_web(data: dict):
    mensaje = data.get("mensaje")
    phone_number = data.get("phone_number", "web_user")
    
    if not mensaje:
        raise HTTPException(status_code=400, detail="Falta el mensaje")
        
    client_memory.registrar_visita(phone_number)
    database.save_message(phone_number, "user", mensaje)
    escalado_humano.resolver_ticket_si_despedida(phone_number, mensaje)
    conversation_summary.registrar_actividad(phone_number)
    
    ai_response = await procesar_flujo_mensaje(phone_number, mensaje, "text")
    database.save_message(phone_number, "assistant", ai_response)
    
    if escalado_humano.detectar_necesidad_escalado(ai_response):
        escalado_humano.crear_ticket_escalado(phone_number, mensaje, ai_response)
        
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
