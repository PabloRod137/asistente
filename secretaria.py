import os
import sqlite3
import logging
import requests
import json
from datetime import datetime, timedelta
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import pymsteams
import whatsapp

logger = logging.getLogger(__name__)

_scheduler = None

def set_scheduler(s):
    global _scheduler
    _scheduler = s

def interpretar_mensaje_interno(message: str) -> dict | None:
    """
    Usa Gemini para determinar si un mensaje del gestor representa una acción de agenda/tareas.
    Si la acción es 'ninguna', devuelve None.
    """
    if os.getenv("MODULO_SECRETARIA", "true").strip().lower() == "false":
        return None
        
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None
        
    fecha_hoy = datetime.now().strftime("%Y-%m-%d (%A)")
    
    prompt = f"""Eres el asistente interno de un gestor. Analiza este mensaje y extrae la acción a realizar.

Devuelve SOLO un JSON válido con estos campos:
{{
  "accion": "crear_cita" | "crear_tarea" | "crear_recordatorio" | "consultar_agenda" | "completar" | "ninguna",
  "titulo": "texto del evento o tarea",
  "fecha": "YYYY-MM-DD o null",
  "hora": "HH:MM o null",
  "descripcion": "detalles adicionales o null"
}}

Ejemplos:
- "apunta reunión con Hacienda el jueves a las 11" -> accion: crear_cita
- "recuerdáme revisar el modelo 303 de García mañana" -> accion: crear_recordatorio
- "hay que llamar a Martínez esta semana" -> accion: crear_tarea
- "¿qué tengo mañana?" -> accion: consultar_agenda
- "la reunión del jueves ya está hecha" -> accion: completar

Mensaje: "{message}"
Fecha actual: "{fecha_hoy}"
"""
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.0}
    }
    
    try:
        response = requests.post(url, json=payload, headers={'Content-Type': 'application/json'}, timeout=15)
        response.raise_for_status()
        res_text = response.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        datos = json.loads(res_text)
        
        accion = datos.get("accion", "ninguna")
        if accion == "ninguna":
            return None
        return datos
    except Exception as e:
        logger.error(f"Error interpretando mensaje interno con Gemini: {e}")
        return None

def ejecutar_accion_interno(datos: dict) -> str:
    """
    Ejecuta en SQLite la acción de agenda/tarea extraída y devuelve una confirmación legible.
    """
    db_path = os.getenv("DB_PATH", "chatbot.db")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    accion = datos.get("accion")
    titulo = datos.get("titulo", "")
    fecha = datos.get("fecha")
    hora = datos.get("hora")
    desc = datos.get("descripcion", "")
    
    now_str = datetime.now().strftime("%Y-%m-%d")
    
    if accion == "crear_cita":
        tipo = "cita"
        fecha_real = fecha if fecha else now_str
        cursor.execute("""
            INSERT INTO agenda_interna (tipo, titulo, descripcion, fecha, hora)
            VALUES (?, ?, ?, ?, ?)
        """, (tipo, titulo, desc, fecha_real, hora))
        conn.commit()
        conn.close()
        hora_str = f" a las {hora}" if hora else ""
        return f"✅ Apuntado: Cita '{titulo}' el {fecha_real}{hora_str}."
        
    elif accion == "crear_tarea":
        tipo = "tarea"
        cursor.execute("""
            INSERT INTO agenda_interna (tipo, titulo, descripcion, fecha, hora)
            VALUES (?, ?, ?, ?, ?)
        """, (tipo, titulo, desc, fecha, hora))
        conn.commit()
        conn.close()
        fecha_str = f" para el {fecha}" if fecha else " (sin fecha específica)"
        return f"📝 Tarea añadida: '{titulo}'{fecha_str}."
        
    elif accion == "crear_recordatorio":
        tipo = "recordatorio"
        fecha_real = fecha if fecha else now_str
        cursor.execute("""
            INSERT INTO agenda_interna (tipo, titulo, descripcion, fecha, hora)
            VALUES (?, ?, ?, ?, ?)
        """, (tipo, titulo, desc, fecha_real, hora))
        conn.commit()
        conn.close()
        hora_str = f" a las {hora}" if hora else ""
        return f"🔔 Recordatorio creado: '{titulo}' para el {fecha_real}{hora_str}."
        
    elif accion == "consultar_agenda":
        target_date = fecha if fecha else now_str
        cursor.execute("""
            SELECT id, tipo, titulo, hora, completado 
            FROM agenda_interna 
            WHERE fecha = ? AND completado = 0
            ORDER BY hora ASC
        """, (target_date,))
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return f"📅 No tienes nada pendiente programado para el {target_date}."
            
        res = f"📅 *Pendientes para el {target_date}:*\n"
        for r_id, tipo, title, h, comp in rows:
            icon = "•"
            if tipo == "cita": icon = "🤝"
            elif tipo == "tarea": icon = "📝"
            elif tipo == "recordatorio": icon = "🔔"
            hora_str = f" [{h}]" if h else ""
            res += f"\n{icon} {title}{hora_str} (ID: {r_id})"
        return res
        
    elif accion == "completar":
        # Completar por coincidencia de título en tareas del día o generales
        cursor.execute("""
            UPDATE agenda_interna 
            SET completado = 1 
            WHERE titulo LIKE ? AND completado = 0
        """, (f"%{titulo}%",))
        rows_affected = cursor.rowcount
        conn.commit()
        conn.close()
        
        if rows_affected > 0:
            return f"✅ Completado: Se han marcado {rows_affected} elemento(s) que coinciden con '{titulo}'."
        else:
            return f"⚠️ No se encontró ningún elemento pendiente que coincida con '{titulo}'."
            
    conn.close()
    return "Acción no soportada."

def generar_briefing_diario():
    """
    Genera el briefing diario matutino y lo envía al gestor por WhatsApp, Teams y Email.
    """
    if os.getenv("MODULO_SECRETARIA", "true").strip().lower() == "false":
        return

    db_path = os.getenv("DB_PATH", "chatbot.db")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    hoy = datetime.now().strftime("%Y-%m-%d")
    
    # 1. Citas de hoy
    cursor.execute("""
        SELECT titulo, hora FROM agenda_interna 
        WHERE tipo = 'cita' AND fecha = ? AND completado = 0 
        ORDER BY hora ASC
    """, (hoy,))
    citas_rows = cursor.fetchall()
    citas = "\n".join([f"- {r[0]} ({r[1] or 'todo el día'})" for r in citas_rows]) if citas_rows else "Ninguna"
    
    # 2. Tareas/recordatorios de hoy
    cursor.execute("""
        SELECT titulo, tipo FROM agenda_interna 
        WHERE tipo IN ('tarea', 'recordatorio') AND (fecha = ? OR fecha IS NULL) AND completado = 0
    """, (hoy,))
    tareas_rows = cursor.fetchall()
    tareas = "\n".join([f"- [{r[1].upper()}] {r[0]}" for r in tareas_rows]) if tareas_rows else "Ninguna"
    
    # 3. Plazos fiscales próximos 7 días
    proximos_7 = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
    cursor.execute("""
        SELECT modelo, cliente, fecha_limite FROM plazos_fiscales 
        WHERE fecha_limite BETWEEN ? AND ? AND completado = 0
        ORDER BY fecha_limite ASC
    """, (hoy, proximos_7))
    plazos_rows = cursor.fetchall()
    plazos = "\n".join([f"- {r[0]} ({r[1]}) - Límite: {r[2]}" for r in plazos_rows]) if plazos_rows else "Ninguno"
    
    # 4. Tickets pendientes
    cursor.execute("SELECT id, phone_number, mensaje_cliente FROM tickets_escalados WHERE estado = 'pendiente'")
    tickets_rows = cursor.fetchall()
    tickets = "\n".join([f"- #{r[0]} de {r[1]}: \"{r[2][:40]}...\"" for r in tickets_rows]) if tickets_rows else "Ninguno"
    
    # 5. Conversaciones recibidas ayer
    ayer = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    cursor.execute("SELECT COUNT(*) FROM conversaciones WHERE date(inicio) = ?", (ayer,))
    num_conversaciones = cursor.fetchone()[0]
    
    conn.close()
    
    # Redacción con Gemini
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.error("No GEMINI_API_KEY en el briefing diario.")
        return
        
    prompt = f"""Eres la asistente MAIRA. Redacta el briefing de buenos días para el gestor de una gestoría.
Tono: profesional, directo, como una secretaria eficiente.
Formato: optimizado para WhatsApp (sin markdown, saltos de línea claros, emojis moderados).
Máximo 20 líneas.

DATA:
Fecha: {hoy}
Citas hoy: {citas}
Tareas hoy: {tareas}
Plazos próximos 7 días: {plazos}
Tickets pendientes de clientes: {tickets}
Conversaciones ayer: {num_conversaciones}"""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}]
    }
    
    try:
        response = requests.post(url, json=payload, headers={'Content-Type': 'application/json'}, timeout=30)
        response.raise_for_status()
        briefing = response.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        logger.error(f"Error generando texto del briefing con Gemini: {e}")
        briefing = f"Buenos días. Hubo un error al generar tu briefing dinámico de hoy ({hoy}), pero tienes pendientes en tu panel administrativo."
        
    # --- TRANSMISIÓN ---
    gestor_whatsapp = os.getenv("GESTOR_WHATSAPP")
    gestor_email = os.getenv("GESTOR_EMAIL") or os.getenv("PROFESIONAL_EMAIL")
    teams_webhook_url = os.getenv("TEAMS_WEBHOOK_URL")
    
    # WhatsApp
    if gestor_whatsapp:
        try:
            whatsapp.send_whatsapp_message(gestor_whatsapp, briefing)
            logger.info("Briefing enviado con éxito por WhatsApp.")
        except Exception as we:
            logger.error(f"Error enviando briefing por WhatsApp: {we}")
            
    # Teams
    if teams_webhook_url:
        try:
            myTeamsMessage = pymsteams.connectorcard(teams_webhook_url)
            myTeamsMessage.title(f"☀️ Briefing MAIRA — {hoy}")
            myTeamsMessage.text(briefing)
            myTeamsMessage.send()
            logger.info("Briefing enviado con éxito a Teams.")
        except Exception as te:
            logger.error(f"Error enviando briefing a Teams: {te}")
            
    # Email
    if gestor_email:
        email_emisor = os.getenv("EMAIL_EMISOR")
        smtp_password = os.getenv("SMTP_PASSWORD")
        smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
        smtp_port_str = os.getenv("SMTP_PORT", "587")
        
        if email_emisor and smtp_password:
            try:
                smtp_port = int(smtp_port_str)
            except ValueError:
                smtp_port = 587
                
            asunto = f"☀️ Briefing MAIRA — {hoy}"
            briefing_html = briefing.replace("\n", "<br>")
            
            # Tabla de citas para el correo
            citas_tabla_html = "<table border='1' cellpadding='5' style='border-collapse: collapse; width:100%;'>"
            citas_tabla_html += "<tr style='background-color:#f2f2f2;'><th>Cita / Reunión</th><th>Hora</th></tr>"
            if citas_rows:
                for r in citas_rows:
                    citas_tabla_html += f"<tr><td>{r[0]}</td><td>{r[1] or 'Todo el día'}</td></tr>"
            else:
                citas_tabla_html += "<tr><td colspan='2'>No tienes citas programadas hoy.</td></tr>"
            citas_tabla_html += "</table>"
            
            cuerpo = f"""
            <html>
                <body style="font-family: sans-serif; color: #333;">
                    <h2 style="color: #2e7d32;">☀️ Briefing Diario</h2>
                    <div style="background-color: #e8f5e9; padding: 15px; border-left: 5px solid #2e7d32; margin-bottom: 20px;">
                        {briefing_html}
                    </div>
                    <h3>🤝 Agenda de Reuniones de Hoy:</h3>
                    {citas_tabla_html}
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
                logger.info("Briefing enviado con éxito por Email.")
            except Exception as ee:
                logger.error(f"Error enviando briefing por Email: {ee}")

def parsear_y_guardar_plazos_txt(knowledge_text: str):
    """
    Busca la sección [PLAZOS FISCALES PRÓXIMOS] en el texto y parsea los modelos y fechas usando Gemini.
    """
    if "[PLAZOS FISCALES PRÓXIMOS]" not in knowledge_text:
        return
        
    idx = knowledge_text.find("[PLAZOS FISCALES PRÓXIMOS]")
    sub_text = knowledge_text[idx:idx+1000]
    
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return
        
    prompt = f"""Extrae los plazos fiscales del siguiente texto de referencia.
Convierte los nombres de meses o referencias temporales a una fecha exacta en el año actual (2026).

Devuelve SOLO un JSON con formato array de objetos con las claves: "modelo", "descripcion", "cliente", "fecha_limite" (en formato YYYY-MM-DD).
Si no se especifica cliente, usa "TODOS".

TEXTO:
{sub_text}"""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.0}
    }
    
    try:
        response = requests.post(url, json=payload, headers={'Content-Type': 'application/json'}, timeout=15)
        response.raise_for_status()
        res_text = response.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        plazos = json.loads(res_text)
        
        db_path = os.getenv("DB_PATH", "chatbot.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        for p in plazos:
            modelo = p.get("modelo")
            desc = p.get("descripcion", "")
            cliente = p.get("cliente", "TODOS")
            fecha_limite = p.get("fecha_limite")
            
            if not modelo or not fecha_limite:
                continue
                
            cursor.execute("""
                SELECT id FROM plazos_fiscales WHERE modelo = ? AND fecha_limite = ?
            """, (modelo, fecha_limite))
            if not cursor.fetchone():
                cursor.execute("""
                    INSERT INTO plazos_fiscales (modelo, descripcion, cliente, fecha_limite)
                    VALUES (?, ?, ?, ?)
                """, (modelo, desc, cliente, fecha_limite))
                logger.info(f"Plazo fiscal importado: {modelo} para {fecha_limite}")
                
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Error parseando plazos fiscales del knowledge: {e}")
