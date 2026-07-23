import os
import json
import logging
import httpx
import asyncio
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import calendar_adapter
import database
from database import save_cita, get_active_cita, update_cita_estado, save_message
from whatsapp import send_whatsapp_message

logger = logging.getLogger(__name__)

# Inicializar APScheduler (instancia única AsyncIOScheduler compartida)
scheduler = AsyncIOScheduler()
scheduler.start()

def esta_en_oferta(phone_number: str) -> bool:
    return database.get_session(phone_number, "agenda_oferta") is not None

async def enviar_recordatorio_24h(phone: str, fecha_cita: str):
    mensaje = f"⏰ Recordatorio: Tienes una cita reservada para mañana: {fecha_cita}. ¡Te esperamos!"
    logger.info(f"Enviando recordatorio automático 24h antes a {phone}")
    await send_whatsapp_message(phone, mensaje)
    save_message(phone, "assistant", mensaje)

async def procesar_agenda(phone_number: str, message: str, history: list) -> str:
    """
    Gestiona el flujo conversacional de la agenda utilizando Gemini para extraer la intención específica de forma asíncrona,
    con persistencia SQLite de huecos ofrecidos.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return "Lo siento, la agenda no está disponible porque el servicio de IA no está configurado."

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
    
    contexto = []
    for msg in history[-4:]:
        contexto.append(f"{msg['role']}: {msg['content']}")
    contexto.append(f"user: {message}")
    contexto_str = "\n".join(contexto)
    
    ahora_fecha = datetime.now().strftime("%Y-%m-%d")
    
    prompt = f"""
    Eres un asistente de reservas. Analiza la conversación y determina la acción del usuario.
    Fecha actual de referencia: {ahora_fecha}

    Conversación:
    {contexto_str}

    Determina:
    1. accion: Una de estas: "consultar" (quiere ver disponibilidad), "reservar" (elige una opción o especifica hora/fecha exacta), "cancelar" (quiere cancelar su cita), o "conversar" (cualquier otra cosa).
    2. fecha: Fecha deseada en formato YYYY-MM-DD si se deduce. Si no se indica fecha, usa null.
    3. opcion: El número de la opción elegida (1, 2, 3, etc.) si el usuario está seleccionando un hueco de una lista ofrecida previamente. Si no, usa null.
    4. servicio: Concepto o servicio que desea reservar si se menciona, o null.

    Devuelve ÚNICAMENTE un JSON válido con esta estructura exacta:
    {{
        "accion": "consultar | reservar | cancelar | conversar",
        "fecha": "YYYY-MM-DD o null",
        "opcion": int_o_null,
        "servicio": "string o null"
    }}
    """
    
    from gemini_limiter import limiter
    try:
        async with limiter:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"responseMimeType": "application/json", "temperature": 0.0}
                }, headers={'Content-Type': 'application/json'})
                response.raise_for_status()
                analisis = response.json()
                datos = json.loads(analisis["candidates"][0]["content"]["parts"][0]["text"].strip())
    except Exception as e:
        logger.error(f"Error analizando agenda con Gemini: {e}")
        return "Lo siento, he tenido un problema técnico al procesar tu solicitud de cita. Por favor, ¿podrías repetírmela en un momento?"

    accion = datos.get("accion", "conversar")
    fecha_req = datos.get("fecha")
    opcion_req = datos.get("opcion")
    servicio_req = datos.get("servicio") or "Servicio Comercial"

    # --- ACCIÓN: CONSULTAR DISPONIBILIDAD ---
    if accion == "consultar":
        if not fecha_req:
            fecha_req = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
            
        duracion = int(os.getenv("CITA_DURACION_MINUTOS", "60"))
        slots = await calendar_adapter.get_free_slots(fecha_req, duracion)
        
        if not slots:
            return f"Lo siento, no me quedan huecos libres para el {fecha_req}. ¿Te viene bien otra fecha?"
            
        database.save_session(phone_number, "agenda_oferta", {"slots": slots})
        
        respuesta = f"Aquí tienes los huecos disponibles para el {fecha_req}:\n"
        for idx, slot in enumerate(slots, 1):
            hora_inicio = datetime.fromisoformat(slot["start"]).strftime("%H:%M")
            respuesta += f"{idx}. {hora_inicio}\n"
        respuesta += "\nDime el número de la opción que prefieras para reservarla."
        return respuesta

    # --- ACCIÓN: CONFIRMAR RESERVA ---
    elif accion == "reservar":
        session_oferta = database.get_session(phone_number, "agenda_oferta")
        slots_ofrecidos = session_oferta.get("slots") if session_oferta else None
        
        if opcion_req and slots_ofrecidos and 1 <= opcion_req <= len(slots_ofrecidos):
            slot_elegido = slots_ofrecidos[opcion_req - 1]
        elif slots_ofrecidos:
            slot_elegido = None
            for slot in slots_ofrecidos:
                hora_slot = datetime.fromisoformat(slot["start"]).strftime("%H:%M")
                if hora_slot in message:
                    slot_elegido = slot
                    break
            if not slot_elegido:
                slot_elegido = slots_ofrecidos[0]
        else:
            target_date = fecha_req or (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
            duracion = int(os.getenv("CITA_DURACION_MINUTOS", "60"))
            slots = await calendar_adapter.get_free_slots(target_date, duracion)
            if slots:
                slot_elegido = slots[0]
            else:
                return "No he podido encontrar huecos disponibles para reservar. Por favor, dime qué día te gustaría venir."

        start_dt = datetime.fromisoformat(slot_elegido["start"])
        end_dt = datetime.fromisoformat(slot_elegido["end"])
        
        titulo = f"Cita comercial: {phone_number} ({servicio_req})"
        resultado = await calendar_adapter.create_event(titulo, slot_elegido["start"], slot_elegido["end"])
        
        if resultado and resultado.get("status") == "success":
            event_id = resultado["id"]
            
            save_cita(phone_number, event_id, slot_elegido["start"], servicio_req, "confirmada")
            
            database.delete_session(phone_number, "agenda_oferta")
                
            try:
                run_time = start_dt - timedelta(hours=24)
                if run_time <= datetime.now():
                    run_time = datetime.now() + timedelta(seconds=10)
                    
                scheduler.add_job(
                    enviar_recordatorio_24h,
                    'date',
                    run_date=run_time,
                    args=[phone_number, start_dt.strftime("%Y-%m-%d a las %H:%M")]
                )
                logger.info(f"Recordatorio programado para {run_time}")
            except Exception as se:
                logger.error(f"Error programando recordatorio: {se}")

            hora_legible = start_dt.strftime("%H:%M")
            fecha_legible = start_dt.strftime("%Y-%m-%d")
            return f"¡Reserva confirmada! ✅ Te he agendado para el {fecha_legible} a las {hora_legible}. Te enviaré un recordatorio 24 horas antes."
        else:
            return "Lo siento, ha habido un problema técnico al guardar la cita en el calendario. Inténtalo de nuevo en unos minutos."

    # --- ACCIÓN: CANCELAR CITA ---
    elif accion == "cancelar":
        cita = get_active_cita(phone_number)
        if not cita:
            return "No he encontrado ninguna cita activa a tu nombre para cancelar."
            
        event_id = cita["event_id"]
        fecha_cita = datetime.fromisoformat(cita["fecha"]).strftime("%Y-%m-%d a las %H:%M")
        
        if await calendar_adapter.cancel_event(event_id):
            update_cita_estado(event_id, "cancelada")
            return f"Tu cita programada para el {fecha_cita} ha sido cancelada correctamente. ❌"
        else:
            return "Lo siento, no he podido cancelar la cita en el calendario. Por favor, inténtalo más tarde."

    else:
        return None
