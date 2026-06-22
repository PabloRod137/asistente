import os
import sqlite3
import requests
import logging
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import pymsteams
from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)

_scheduler = None

def set_scheduler(s):
    global _scheduler
    _scheduler = s

def detectar_despedida(message: str) -> bool:
    """
    Devuelve True si el mensaje contiene alguna palabra de despedida.
    """
    if not message:
        return False
    msg_lower = message.lower().strip()
    despedidas = [
        "gracias", "hasta luego", "adiós", "adios", 
        "hasta pronto", "ok gracias", "perfecto gracias", 
        "nada más", "eso es todo"
    ]
    for d in despedidas:
        if d in msg_lower:
            return True
    return False

def registrar_actividad(phone_number: str):
    """
    Registra la actividad en la base de datos (inicia nueva conversación si
    la anterior fue resumida/enviada) y reprograma el timeout de inactividad.
    """
    if _scheduler is None:
        logger.warning("Scheduler no configurado en conversation_summary. Omitiendo timeout.")
        return

    if os.getenv("MODULO_RESUMEN", "true").strip().lower() == "false":
        return

    db_path = os.getenv("DB_PATH", "chatbot.db")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Comprobar si hay una conversación activa
    cursor.execute('''
        SELECT resumen_enviado FROM conversaciones WHERE phone_number = ?
    ''', (phone_number,))
    row = cursor.fetchone()
    
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    if row is None or row[0] == 1:
        # Si no existe conversación o ya se envió el resumen, iniciamos una nueva
        cursor.execute('''
            INSERT OR REPLACE INTO conversaciones (phone_number, inicio, ultimo_mensaje, resumen_enviado)
            VALUES (?, ?, ?, 0)
        ''', (phone_number, now_str, now_str))
        logger.info(f"Nueva conversación iniciada en DB para {phone_number}")
    else:
        # Si está activa (resumen_enviado = 0), actualizamos el último mensaje
        cursor.execute('''
            UPDATE conversaciones
            SET ultimo_mensaje = ?
            WHERE phone_number = ?
        ''', (now_str, phone_number))
        
    conn.commit()
    conn.close()
    
    # Programar/Reprogramar el job de inactividad
    timeout_mins = int(os.getenv("CONVERSACION_TIMEOUT_MINUTOS", "30"))
    job_id = f"summary_timeout_{phone_number}"
    
    # Cancelar el job anterior si existe
    if _scheduler.get_job(job_id):
        try:
            _scheduler.remove_job(job_id)
        except Exception as e:
            logger.debug(f"Error al remover job {job_id}: {e}")
            
    # Configurar el nuevo job de inactividad
    run_time = datetime.now() + timedelta(minutes=timeout_mins)
    _scheduler.add_job(
        func=generar_y_enviar_resumen,
        trigger='date',
        run_date=run_time,
        args=[phone_number],
        id=job_id
    )
    logger.info(f"Programado timeout de inactividad para {phone_number} en {timeout_mins} minutos.")

def generar_resumen(phone_number: str) -> str:
    """
    Obtiene el historial completo de la conversación activa y genera un resumen usando Gemini 2.0 Flash.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return "No API key configured for Gemini."
        
    db_path = os.getenv("DB_PATH", "chatbot.db")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Obtener el inicio de la conversación activa
    cursor.execute('''
        SELECT inicio FROM conversaciones WHERE phone_number = ?
    ''', (phone_number,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return "No hay conversación registrada para este número."
        
    inicio_timestamp = row[0]
    
    # Obtener todos los mensajes desde que inició la conversación
    cursor.execute('''
        SELECT role, content, timestamp FROM messages
        WHERE phone_number = ? AND timestamp >= ?
        ORDER BY timestamp ASC
    ''', (phone_number, inicio_timestamp))
    messages = cursor.fetchall()
    conn.close()
    
    if not messages:
        return "No hay mensajes en la conversación activa para resumir."
        
    historial = ""
    for r, c, t in messages:
        sender = "Maira" if r == "assistant" else "Cliente"
        historial += f"[{t}] {sender}: {c}\n"
        
    prompt = f"""Eres un asistente de gestoría. Analiza esta conversación de WhatsApp entre Maira (asistente virtual) y un cliente, y genera un resumen ejecutivo para el equipo gestor humano.

Incluye:
1. DATOS DEL CLIENTE: número de teléfono y cualquier nombre o dato mencionado
2. MOTIVO DE CONTACTO: por qué escribió el cliente
3. ACCIONES REALIZADAS: qué hizo Maira (respondió dudas, recogió ticket, gestionó cita, generó factura, derivó a gestor...)
4. PENDIENTE PARA EL GESTOR: si hay algo que requiere atención humana
5. DOCUMENTOS RECIBIDOS: si se enviaron fotos o archivos

Sé conciso. Máximo 15 líneas. Usa viñetas.

CONVERSACIÓN:
{historial}"""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
    payload = {
        "contents": [{
            "parts": [{"text": prompt}]
        }]
    }
    
    try:
        response = requests.post(url, json=payload, headers={'Content-Type': 'application/json'}, timeout=20)
        response.raise_for_status()
        data = response.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        logger.error(f"Error llamando a Gemini para resumen: {e}")
        return f"No se pudo generar el resumen automáticamente debido a un error: {e}"

def enviar_email(phone_number: str, resumen: str, historial_text: str):
    """
    Envía el resumen generado por correo electrónico al gestor configurado.
    """
    email_emisor = os.getenv("EMAIL_EMISOR")
    smtp_password = os.getenv("SMTP_PASSWORD")
    gestor_email = os.getenv("GESTOR_EMAIL") or os.getenv("PROFESIONAL_EMAIL")
    smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    smtp_port_str = os.getenv("SMTP_PORT", "587")
    
    if not email_emisor or not smtp_password or not gestor_email:
        logger.warning("Configuración de correo electrónico incompleta en .env. Omitiendo envío de email.")
        return
        
    try:
        smtp_port = int(smtp_port_str)
    except ValueError:
        smtp_port = 587
        
    fecha_hora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    asunto = f"[Lex Guardian] Resumen conversación — {phone_number} — {fecha_hora}"
    
    resumen_html = resumen.replace("\n", "<br>")
    historial_html = historial_text.replace("\n", "<br>")
    
    cuerpo = f"""
    <html>
        <body style="font-family: Arial, sans-serif; color: #333;">
            <h2 style="color: #0056b3;">Resumen de conversación</h2>
            <p><strong>Cliente:</strong> {phone_number}</p>
            <p><strong>Fecha/Hora:</strong> {fecha_hora}</p>
            <hr/>
            <div style="background-color: #f9f9f9; padding: 15px; border-left: 5px solid #0056b3; margin-bottom: 20px; font-size: 14px; line-height: 1.6;">
                {resumen_html}
            </div>
            <h3 style="color: #666;">Historial de Referencia:</h3>
            <div style="background-color: #f1f1f1; padding: 10px; font-family: monospace; white-space: pre-wrap; font-size: 12px; border-radius: 4px;">
                {historial_html}
            </div>
        </body>
    </html>
    """
    
    msg = MIMEMultipart("alternative")
    msg["Subject"] = asunto
    msg["From"] = email_emisor
    msg["To"] = gestor_email
    msg.attach(MIMEText(cuerpo, "html"))
    
    try:
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(email_emisor, smtp_password)
        server.sendmail(email_emisor, gestor_email, msg.as_string())
        server.quit()
        logger.info(f"Email de resumen enviado correctamente a {gestor_email}")
    except Exception as e:
        logger.error(f"Error enviando email de resumen: {e}")

def enviar_teams(phone_number: str, resumen: str):
    """
    Envía el resumen del cliente al webhook del canal de Microsoft Teams.
    """
    teams_webhook_url = os.getenv("TEAMS_WEBHOOK_URL")
    if not teams_webhook_url or not teams_webhook_url.strip():
        logger.info("TEAMS_WEBHOOK_URL no configurado. Omitiendo envío a Teams.")
        return
        
    fecha_hora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    try:
        myTeamsMessage = pymsteams.connectorcard(teams_webhook_url)
        myTeamsMessage.title(f"Resumen de Conversación — {phone_number}")
        
        texto_mensaje = f"**Cliente:** {phone_number}\n**Fecha/Hora:** {fecha_hora}\n\n{resumen}"
        myTeamsMessage.text(texto_mensaje)
        
        myTeamsMessage.send()
        logger.info("Resumen de conversación enviado correctamente a Microsoft Teams.")
    except Exception as e:
        logger.error(f"Error enviando notificación a Teams: {e}")

def generar_y_enviar_resumen(phone_number: str):
    """
    Función que orquesta la generación del resumen y envío a los canales correspondientes
    siempre y cuando no se haya enviado ya el resumen de la conversación activa.
    """
    if _scheduler is None:
        logger.warning("Scheduler no configurado en conversation_summary. Omitiendo timeout.")
        return

    if os.getenv("MODULO_RESUMEN", "true").strip().lower() == "false":
        return

    db_path = os.getenv("DB_PATH", "chatbot.db")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT resumen_enviado, inicio FROM conversaciones WHERE phone_number = ?
    ''', (phone_number,))
    row = cursor.fetchone()
    
    if not row or row[0] == 1:
        conn.close()
        logger.info(f"El resumen para {phone_number} ya fue enviado o la conversación no existe.")
        return
        
    # Marcar como enviado inmediatamente para evitar reentradas
    cursor.execute('''
        UPDATE conversaciones SET resumen_enviado = 1 WHERE phone_number = ?
    ''', (phone_number,))
    conn.commit()
    
    inicio_timestamp = row[1]
    
    # Obtener historial para el correo antes de cerrar
    cursor.execute('''
        SELECT role, content, timestamp FROM messages
        WHERE phone_number = ? AND timestamp >= ?
        ORDER BY timestamp ASC
    ''', (phone_number, inicio_timestamp))
    messages = cursor.fetchall()
    conn.close()
    
    # Cancelar el job de timeout si aún estaba pendiente en el programador
    job_id = f"summary_timeout_{phone_number}"
    if _scheduler.get_job(job_id):
        try:
            _scheduler.remove_job(job_id)
            logger.info(f"Cancelado timeout pendiente para {phone_number} al disparar resumen.")
        except Exception as e:
            logger.debug(f"Error cancelando job {job_id}: {e}")
            
    logger.info(f"Generando resumen de conversación para {phone_number}...")
    resumen = generar_resumen(phone_number)
    
    # Guardar el resumen generado en la columna resumen_texto de conversaciones
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE conversaciones SET resumen_texto = ? WHERE phone_number = ?
        ''', (resumen, phone_number))
        conn.commit()
        conn.close()
    except Exception as dbe:
        logger.error(f"Error guardando resumen_texto en DB: {dbe}")

    # Extraer y guardar datos de memoria del cliente si está habilitado
    if os.getenv("MODULO_MEMORIA", "true").strip().lower() != "false":
        try:
            import client_memory
            # Convertir la lista de mensajes en formato de historial con 'role' y 'content'
            history_list = [{"role": r, "content": c} for r, c, t in messages]
            datos_extraidos = client_memory.extraer_datos_cliente(phone_number, history_list)
            client_memory.upsert_cliente(phone_number, datos_extraidos)
            logger.info(f"Perfil de cliente enriquecido y guardado para {phone_number}: {datos_extraidos}")
        except Exception as e:
            logger.error(f"Error actualizando la memoria de cliente al resumir: {e}")
    
    historial_text = ""
    for r, c, t in messages:
        sender = "Maira" if r == "assistant" else "Cliente"
        historial_text += f"[{t}] {sender}: {c}\n"
        
    # Enviar notificaciones
    enviar_email(phone_number, resumen, historial_text)
    enviar_teams(phone_number, resumen)
