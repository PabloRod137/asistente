import os
import json
import httpx
import asyncio
import database
import logging
from datetime import datetime
import pymsteams
from gemini_limiter import limiter

logger = logging.getLogger(__name__)

def detectar_necesidad_escalado(respuesta_maira: str) -> bool:
    """
    Devuelve True si la respuesta contiene frases típicas de derivación o escalado.
    """
    if os.getenv("MODULO_ESCALADO", "true").strip().lower() == "false":
        return False
        
    if not respuesta_maira:
        return False
        
    indicadores = [
        "te derivo", 
        "un gestor se pondrá en contacto", 
        "consulta con nuestro equipo", 
        "nuestros profesionales", 
        "fuera de mi alcance"
    ]
    
    resp_lower = respuesta_maira.lower()
    for ind in indicadores:
        if ind in resp_lower:
            return True
    return False

async def clasificar_especialidad(mensaje_cliente: str, respuesta_maira: str) -> str:
    """
    Clasifica la consulta del cliente en una especialidad: 'fiscal', 'laboral', 'mercantil', 'civil', 'compliance', 'general'.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return "general"
        
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
    
    prompt = f"""
    Analiza la consulta del cliente y clasifícala en exactamente una de estas especialidades en minúsculas:
    - fiscal (relacionada con impuestos, IVA, IRPF, modelos fiscales, etc.)
    - laboral (nóminas, contratos de trabajo, despidos, seguridad social, etc.)
    - mercantil (constitución de sociedades, escrituras, fusiones, mercantil, etc.)
    - civil (herencias, contratos de alquiler, propiedad, disputas civiles, etc.)
    - compliance (cumplimiento normativo, prevención de blanqueo, políticas de empresa, etc.)
    - general (cualquier otro tema o si no queda claro)

    Consulta del cliente: "{mensaje_cliente}"
    Última respuesta de Maira: "{respuesta_maira}"

    Responde ÚNICAMENTE con la palabra de la especialidad en minúsculas (fiscal, laboral, mercantil, civil, compliance, general). Nada más.
    """
    
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": 10, "temperature": 0.0}
    }
    
    try:
        async with limiter:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=payload, headers={'Content-Type': 'application/json'})
                response.raise_for_status()
                data = response.json()
                texto = data["candidates"][0]["content"]["parts"][0]["text"].strip().lower()
                
                valid_especialidades = {"fiscal", "laboral", "mercantil", "civil", "compliance", "general"}
                for esp in valid_especialidades:
                    if esp in texto:
                        return esp
    except Exception as e:
        logger.error(f"Error clasificando especialidad con Gemini: {e}")
        
    return "general"

def obtener_gestor_whatsapp_por_especialidad(especialidad: str) -> str:
    """
    Retorna el número de WhatsApp correspondiente a la especialidad desde GESTORES_POR_ESPECIALIDAD en .env,
    o el GESTOR_WHATSAPP por defecto.
    """
    fallback_tel = os.getenv("GESTOR_WHATSAPP")
    
    gestores_json = os.getenv("GESTORES_POR_ESPECIALIDAD")
    if not gestores_json:
        return fallback_tel
        
    try:
        mapping = json.loads(gestores_json)
        tel = mapping.get(especialidad)
        if tel:
            return str(tel).strip()
    except Exception as e:
        logger.error(f"Error parseando GESTORES_POR_ESPECIALIDAD: {e}")
        
    return fallback_tel

async def crear_ticket_escalado(phone_number: str, mensaje_cliente: str, respuesta_maira: str) -> int | None:
    """
    Crea un ticket de escalado en SQLite, clasifica su especialidad y notifica a Teams y WhatsApp al gestor correcto.
    """
    if os.getenv("MODULO_ESCALADO", "true").strip().lower() == "false":
        return None

    conn = database.get_connection()
    cursor = conn.cursor()
    
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    cursor.execute("""
        INSERT INTO tickets_escalados (phone_number, mensaje_cliente, respuesta_maira, estado, fecha_creacion)
        VALUES (?, ?, ?, 'pendiente', ?)
    """, (phone_number, mensaje_cliente, respuesta_maira, now_str))
    ticket_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    logger.info(f"Creado ticket de escalado #{ticket_id} para {phone_number}")
    
    # 2. Clasificar especialidad
    especialidad = await clasificar_especialidad(mensaje_cliente, respuesta_maira)
    logger.info(f"Ticket #{ticket_id} clasificado en especialidad: {especialidad}")
    
    # 3. Obtener número de gestor adecuado
    gestor_tel = obtener_gestor_whatsapp_por_especialidad(especialidad)
    
    # 4. Enviar notificación a Teams
    enviar_notificacion_teams(ticket_id, phone_number, mensaje_cliente, respuesta_maira, especialidad)
    
    # 5. Enviar notificación por WhatsApp al gestor enrutado
    if gestor_tel:
        import whatsapp
        alerta = (
            f"🚨 *ESCALADO A HUMANO — Ticket #{ticket_id}*\n\n"
            f"📞 *Cliente:* {phone_number}\n"
            f"🏷️ *Área:* {especialidad.upper()}\n"
            f"💬 *Consulta:* {mensaje_cliente}\n"
            f"🤖 *MAIRA respondió:* {respuesta_maira}\n\n"
            f"Para responder, escribe al número directamente o usa `/responder_{ticket_id} {{mensaje}}`"
        )
        try:
            await whatsapp.send_whatsapp_message(gestor_tel, alerta)
            logger.info(f"Notificación de escalado para ticket #{ticket_id} enviada por WhatsApp a gestor {gestor_tel}.")
        except Exception as we:
            logger.error(f"Error enviando WhatsApp de escalado al gestor: {we}")
            
    return ticket_id

def enviar_notificacion_teams(ticket_id: int, phone_number: str, mensaje_cliente: str, respuesta_maira: str, especialidad: str = "general"):
    """
    Formatea y envía la alerta de ticket a Teams.
    """
    teams_webhook_url = os.getenv("TEAMS_WEBHOOK_URL")
    if not teams_webhook_url or not teams_webhook_url.strip():
        logger.info("TEAMS_WEBHOOK_URL no configurado. Omitiendo notificación de escalado a Teams.")
        return
        
    try:
        myTeamsMessage = pymsteams.connectorcard(teams_webhook_url)
        myTeamsMessage.title(f"🚨 ESCALADO A HUMANO ({especialidad.upper()}) — Ticket #{ticket_id}")
        
        texto = (
            f"**📞 Cliente:** {phone_number}\n\n"
            f"**🏷️ Área:** {especialidad.upper()}\n\n"
            f"**💬 Consulta:** {mensaje_cliente}\n\n"
            f"**🤖 MAIRA respondió:** {respuesta_maira}\n\n"
            f"✅ Para responder al cliente, escribe al número directamente o usa el comando `/responder_{ticket_id} {{tu_mensaje}}`"
        )
        myTeamsMessage.text(texto)
        myTeamsMessage.send()
        logger.info(f"Notificación de escalado para ticket #{ticket_id} enviada a Teams.")
    except Exception as e:
        logger.error(f"Error enviando notificación de escalado a Teams: {e}")

def actualizar_estado_ticket(ticket_id: int, nuevo_estado: str):
    """
    Actualiza el estado de un ticket y registra la fecha de resolución si se marca como resuelto.
    """
    conn = database.get_connection()
    cursor = conn.cursor()
    
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    if nuevo_estado == 'resuelto':
        cursor.execute("""
            UPDATE tickets_escalados
            SET estado = ?, fecha_resolucion = ?
            WHERE id = ?
        """, (nuevo_estado, now_str, ticket_id))
    else:
        cursor.execute("""
            UPDATE tickets_escalados
            SET estado = ?
            WHERE id = ?
        """, (nuevo_estado, ticket_id))
        
    conn.commit()
    conn.close()
    logger.info(f"Ticket #{ticket_id} actualizado a estado {nuevo_estado}")

def resolver_ticket_si_despedida(phone_number: str, message: str):
    """
    Si hay una despedida del cliente y un ticket asociado en estado 'en_gestion', lo marca como resuelto.
    """
    import conversation_summary
    if conversation_summary.detectar_despedida(message):
        conn = database.get_connection()
        cursor = conn.cursor()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        cursor.execute("""
            UPDATE tickets_escalados
            SET estado = 'resuelto', fecha_resolucion = ?
            WHERE phone_number = ? AND estado = 'en_gestion'
        """, (now_str, phone_number))
        if cursor.rowcount > 0:
            logger.info(f"Tickets en gestión de {phone_number} resueltos automáticamente debido a despedida.")
            
        conn.commit()
        conn.close()
