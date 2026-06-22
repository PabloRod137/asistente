import os
import sqlite3
import logging
from datetime import datetime
import pymsteams

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

def crear_ticket_escalado(phone_number: str, mensaje_cliente: str, respuesta_maira: str) -> int | None:
    """
    Crea un ticket de escalado en SQLite y envía la notificación correspondiente a Teams.
    """
    if os.getenv("MODULO_ESCALADO", "true").strip().lower() == "false":
        return None

    db_path = os.getenv("DB_PATH", "chatbot.db")
    conn = sqlite3.connect(db_path)
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
    
    # Enviar notificación a Teams
    enviar_notificacion_teams(ticket_id, phone_number, mensaje_cliente, respuesta_maira)
    return ticket_id

def enviar_notificacion_teams(ticket_id: int, phone_number: str, mensaje_cliente: str, respuesta_maira: str):
    """
    Formatea y envía la alerta de ticket a Teams.
    """
    teams_webhook_url = os.getenv("TEAMS_WEBHOOK_URL")
    if not teams_webhook_url or not teams_webhook_url.strip():
        logger.info("TEAMS_WEBHOOK_URL no configurado. Omitiendo notificación de escalado a Teams.")
        return
        
    try:
        myTeamsMessage = pymsteams.connectorcard(teams_webhook_url)
        myTeamsMessage.title(f"🚨 ESCALADO A HUMANO — Ticket #{ticket_id}")
        
        texto = (
            f"**📞 Cliente:** {phone_number}\n\n"
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
    db_path = os.getenv("DB_PATH", "chatbot.db")
    conn = sqlite3.connect(db_path)
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
        db_path = os.getenv("DB_PATH", "chatbot.db")
        conn = sqlite3.connect(db_path)
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
