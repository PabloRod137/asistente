import os
import logging
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

# Cargar variables de entorno
load_dotenv()

import database
import llm
import whatsapp
import router
from modulos import agenda, tickets, facturas, triaje, cobrador
import conversation_summary
import knowledge_base
import gestor_mode
import client_memory
import escalado_humano
import secretaria
scheduler = agenda.scheduler
conversation_summary.set_scheduler(scheduler)
secretaria.set_scheduler(scheduler)

# Configurar FastAPI
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
def on_startup():
    logger.info("Iniciando la base de datos de Asistente...")
    database.init_db()
    
    # Programar briefing diario recurrente si está habilitado
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

def procesar_flujo_mensaje(phone_number: str, content: str, msg_type: str) -> str:
    """
    Orquesta la respuesta del bot decidiendo a qué módulo derivar el mensaje
    según las sesiones activas o el router de intenciones.
    """
    # 1. Obtener historial para contexto
    history = database.get_history(phone_number, limit=5)
    
    # 2. Interceptar flujos conversacionales de sesiones activas (Triage o Tickets o Reserva)
    
    # Flujo de TRIAJE activo
    if phone_number in triaje._triaje_sesiones:
        logger.info(f"Derivando mensaje de {phone_number} a sesión activa de TRIAJE.")
        return triaje.gestionar_triaje(phone_number, content, msg_type)
        
    # Flujo de TICKETS activo (esperando confirmación de datos extraídos)
    if phone_number in tickets._tickets_pendientes:
        logger.info(f"Derivando mensaje de {phone_number} a sesión activa de TICKETS.")
        return tickets.gestionar_confirmacion_ticket(phone_number, content)
        
    # Flujo de AGENDA activo (esperando elección de opción)
    if phone_number in agenda._ofrecidos_temp:
        logger.info(f"Derivando mensaje de {phone_number} a sesión activa de AGENDA.")
        res = agenda.procesar_agenda(phone_number, content, history)
        if res is not None:
            return res

    # 3. Procesar nuevos mensajes según tipo o intención
    
    # Si es una IMAGEN nueva
    if msg_type == "image":
        if os.getenv("MODULO_TICKETS", "true").strip().lower() == "false":
            return "Lo siento, el módulo de registro de tickets no está habilitado."
            
        media_id = content # En webhook, pasamos el media_id como content
        storage_ruta = os.getenv("STORAGE_RUTA", "./storage")
        temp_filepath = os.path.join(storage_ruta, "temp", f"ticket_{phone_number}_{int(datetime.now().timestamp())}.jpg")
        
        logger.info(f"Descargando imagen de WhatsApp Media ID: {media_id}...")
        if whatsapp.download_whatsapp_media(media_id, temp_filepath):
            return tickets.procesar_mensaje_imagen(phone_number, temp_filepath)
        else:
            return "No he podido descargar la imagen que has enviado. Inténtalo de nuevo."

    # Si es TEXTO, clasificar intención
    intent = router.detectar_intencion(content)
    
    if intent == "AGENDA":
        return agenda.procesar_agenda(phone_number, content, history)
        
    elif intent == "TICKET":
        return "Para registrar un ticket de gasto, por favor envíame directamente la foto del ticket."
        
    elif intent == "FACTURA":
        return facturas.procesar_solicitud_factura(phone_number, content)
        
    elif intent == "TRIAJE":
        return triaje.gestionar_triaje(phone_number, content, msg_type)
        
    elif intent == "COBRADOR":
        # Conversacionalmente derivamos a chat general
        return llm.generate_response(content, history, phone_number)
        
    else:  # CHAT
        return llm.generate_response(content, history, phone_number)

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
                            
                            # Interceptar gestor antes de procesar el flujo normal
                            if phone_number == os.getenv("GESTOR_WHATSAPP"):
                                respuesta_gestor = gestor_mode.procesar_comando(phone_number, content)
                                if respuesta_gestor is not None:
                                    whatsapp.send_whatsapp_message(phone_number, respuesta_gestor)
                                    continue
                            
                            # Registrar visita del cliente
                            client_memory.registrar_visita(phone_number)
                            
                            # Si es texto normal, guardar el mensaje del usuario
                            if msg_type == "text":
                                database.save_message(phone_number, "user", content)
                            elif msg_type == "image":
                                database.save_message(phone_number, "user", "[Envía Imagen]")
                                
                            # Si hay despedida de cliente, cerrar tickets en gestion si los hubiera
                            escalado_humano.resolver_ticket_si_despedida(phone_number, content)
                            
                            # Registrar actividad (iniciar conversación / resetear inactividad)
                            conversation_summary.registrar_actividad(phone_number)
                            
                            # Procesar flujo
                            ai_response = procesar_flujo_mensaje(phone_number, content, msg_type)
                            
                            # Guardar y enviar respuesta del bot
                            database.save_message(phone_number, "assistant", ai_response)
                            whatsapp.send_whatsapp_message(phone_number, ai_response)
                            
                            # Detectar si requiere escalado a humanos
                            if escalado_humano.detectar_necesidad_escalado(ai_response):
                                escalado_humano.crear_ticket_escalado(phone_number, content, ai_response)
                            
                            # Verificar despedida en el mensaje del usuario
                            if conversation_summary.detectar_despedida(content):
                                conversation_summary.generar_y_enviar_resumen(phone_number)
            
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
        
    # Registrar visita del cliente
    client_memory.registrar_visita(phone_number)
    
    database.save_message(phone_number, "user", mensaje)
    
    # Si hay despedida, resolver tickets
    escalado_humano.resolver_ticket_si_despedida(phone_number, mensaje)
    
    # Registrar actividad
    conversation_summary.registrar_actividad(phone_number)
    
    # Procesamos el flujo igual que WhatsApp (tipo texto)
    ai_response = procesar_flujo_mensaje(phone_number, mensaje, "text")
    
    database.save_message(phone_number, "assistant", ai_response)
    
    # Detectar si requiere escalado a humanos
    if escalado_humano.detectar_necesidad_escalado(ai_response):
        escalado_humano.crear_ticket_escalado(phone_number, mensaje, ai_response)
        
    # Verificar despedida en el mensaje del usuario
    if conversation_summary.detectar_despedida(mensaje):
        conversation_summary.generar_y_enviar_resumen(phone_number)
    
    return {"respuesta": ai_response}

# Endpoint para notificaciones de impago (módulo Cobrador)
@app.post("/cobrar")
async def lanzar_cobro(data: dict):
    telefono = data.get("telefono")
    mensaje = data.get("mensaje")
    
    if not telefono or not mensaje:
        raise HTTPException(status_code=400, detail="Falta telefono o mensaje")
        
    success = cobrador.lanzar_aviso_whatsapp(telefono, mensaje)
    return {"status": "success" if success else "error"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8050, reload=True)
