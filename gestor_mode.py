import os
import sqlite3
import logging
import requests
from datetime import datetime, timedelta
import whatsapp
import database

logger = logging.getLogger(__name__)

# Estado de la sesión del gestor para actualización de la base de conocimiento
_esperando_actualizacion = False

def procesar_comando(phone_number: str, message: str) -> str:
    """
    Procesa los comandos del gestor. Retorna la respuesta de texto correspondiente.
    """
    global _esperando_actualizacion
    
    msg_strip = message.strip()
    
    # 1. Comprobar si estamos esperando la actualización de la base de conocimiento
    if _esperando_actualizacion:
        _esperando_actualizacion = False
        try:
            dir_path = os.path.dirname(os.path.abspath(__file__))
            txt_path = os.path.join(dir_path, "knowledge.txt")
            
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            # Si el archivo no existe, se creará.
            with open(txt_path, "a", encoding="utf-8") as f:
                f.write(f"\n\n=== ACTUALIZACIÓN GESTOR ({now_str}) ===\n{msg_strip}\n")
                
            logger.info("Base de conocimiento actualizada con comando /actualizar.")
            return "Base de conocimiento actualizada ✅"
        except Exception as e:
            logger.error(f"Error escribiendo en knowledge.txt: {e}")
            return "Error al actualizar la base de conocimiento ❌"
            
    # Interceptar lenguaje natural para la agenda interna
    try:
        import secretaria
        datos_accion = secretaria.interpretar_mensaje_interno(message)
        if datos_accion is not None:
            return secretaria.ejecutar_accion_interno(datos_accion)
    except Exception as se:
        logger.error(f"Error procesando lenguaje natural con modulo secretaria: {se}")

    # 2. Si no empieza con /, se asume que no es un comando y se procesará como chat normal (devolviendo None)
    if not msg_strip.startswith("/"):
        return None
        
    cmd_parts = msg_strip.split(maxsplit=1)
    cmd = cmd_parts[0].lower()
    args = cmd_parts[1] if len(cmd_parts) > 1 else ""
    
    # --- COMANDO: /ayuda ---
    if cmd == "/ayuda":
        return (
            "🛠️ *Comandos del Gestor Disponibles:*\n\n"
            "• `/clientes_hoy` - Ver clientes activos hoy y motivo.\n"
            "• `/resumen_semana` - Genera y envía resumen semanal por email.\n"
            "• `/pendientes` - Lista clientes con pendientes para el gestor.\n"
            "• `/actualizar` - Añadir nueva información a la base de conocimiento.\n"
            "• `/stats` - Estadísticas del negocio este mes.\n"
            "• `/responder_{id} {mensaje}` - Responder a un ticket de escalado.\n\n"
            "💼 *Comandos de Agenda Interna (Secretaria):*\n"
            "• `/agenda` - Tareas, citas y recordatorios de hoy y mañana.\n"
            "• `/agenda_semana` - Agenda de los próximos 7 días.\n"
            "• `/plazos` - Próximos plazos fiscales (30 días).\n"
            "• `/completar {id}` - Completar tarea/cita de la agenda.\n"
            "• `/plazo_fiscal \"{modelo}\" \"{cliente}\" {fecha}` - Añadir plazo fiscal."
        )
        
    # --- COMANDO: /clientes_hoy ---
    elif cmd == "/clientes_hoy":
        db_path = os.getenv("DB_PATH", "chatbot.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Obtener conversaciones iniciadas hoy
        cursor.execute("""
            SELECT phone_number, inicio 
            FROM conversaciones 
            WHERE date(inicio) = date('now')
            ORDER BY inicio DESC
        """)
        rows = cursor.fetchall()
        
        if not rows:
            conn.close()
            return "No se ha registrado actividad de clientes hoy."
            
        respuesta = "👥 *Clientes activos hoy:*\n"
        for phone, inicio in rows:
            # Obtener el primer mensaje enviado por el usuario en esta sesión
            cursor.execute("""
                SELECT content FROM messages 
                WHERE phone_number = ? AND role = 'user' AND timestamp >= ?
                ORDER BY timestamp ASC LIMIT 1
            """, (phone, inicio))
            msg_row = cursor.fetchone()
            primer_msg = msg_row[0][:50] + "..." if msg_row else "Sin mensajes"
            
            respuesta += f"\n• *{phone}* (Inició: {inicio})\n  💬 _\"{primer_msg}\"_\n"
            
        conn.close()
        return respuesta
        
    # --- COMANDO: /resumen_semana ---
    elif cmd == "/resumen_semana":
        db_path = os.getenv("DB_PATH", "chatbot.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Obtener resúmenes de conversaciones de los últimos 7 días
        cursor.execute("""
            SELECT phone_number, resumen_texto, inicio
            FROM conversaciones
            WHERE inicio >= datetime('now', '-7 days') AND resumen_texto IS NOT NULL
        """)
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return "No hay conversaciones resumidas en los últimos 7 días."
            
        comb_text = ""
        for phone, res, inicio in rows:
            comb_text += f"\n--- Cliente: {phone} (Inicio: {inicio}) ---\n{res}\n"
            
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return "Error: GEMINI_API_KEY no configurado."
            
        prompt = f"""Genera un resumen ejecutivo semanal para el equipo de una gestoría avanzada en base a los siguientes resúmenes individuales de conversaciones de los últimos 7 días:

{comb_text}

El resumen semanal debe incluir:
1. Cantidad total de clientes únicos que contactaron.
2. Temas de consulta y motivos más frecuentes.
3. Listado de documentos/facturas o tickets recibidos.
4. Pendientes críticos para el equipo humano de gestores.

Por favor, sé conciso y estructurado, usa viñetas."""

        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}]
        }
        
        try:
            response = requests.post(url, json=payload, headers={'Content-Type': 'application/json'}, timeout=30)
            response.raise_for_status()
            summary_weekly = response.json()["candidates"][0]["content"]["parts"][0]["text"]
            
            # Enviar por email al gestor
            from conversation_summary import enviar_email
            enviar_email("Semanal", f"<h3>Resumen Ejecutivo Semanal</h3><hr/>{summary_weekly}", comb_text)
            
            return f"📊 *Resumen Semanal Generado y Enviado por Correo:*\n\n{summary_weekly}"
        except Exception as e:
            logger.error(f"Error generando resumen semanal: {e}")
            return f"Error al generar o enviar el resumen semanal: {e}"
            
    # --- COMANDO: /pendientes ---
    elif cmd == "/pendientes":
        db_path = os.getenv("DB_PATH", "chatbot.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Buscar resúmenes que puedan contener pendientes
        cursor.execute("""
            SELECT phone_number, resumen_texto 
            FROM conversaciones 
            WHERE resumen_texto IS NOT NULL
        """)
        rows = cursor.fetchall()
        conn.close()
        
        pendientes = []
        for phone, res in rows:
            res_lower = res.lower()
            # Si el resumen contiene la palabra pendientes y hay algo no vacío en esa sección
            if "pendiente" in res_lower:
                pendientes.append(f"• *Cliente: {phone}*\n{res}\n")
                
        if not pendientes:
            return "No se encontraron conversaciones con pendientes para el gestor."
            
        return "📋 *Pendientes actuales detectados en conversaciones:*\n\n" + "\n".join(pendientes)
        
    # --- COMANDO: /actualizar ---
    elif cmd == "/actualizar":
        _esperando_actualizacion = True
        return "Manda el nuevo contenido y lo añado a mi base de conocimiento."
        
    # --- COMANDO: /stats ---
    elif cmd == "/stats":
        db_path = os.getenv("DB_PATH", "chatbot.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Citas agendadas
        cursor.execute("SELECT COUNT(*) FROM citas WHERE estado = 'confirmada'")
        citas_count = cursor.fetchone()[0]
        
        # Facturas generadas
        cursor.execute("SELECT COUNT(*) FROM facturas")
        facturas_count = cursor.fetchone()[0]
        
        # Conversaciones este mes
        cursor.execute("SELECT COUNT(*) FROM conversaciones WHERE inicio >= date('now', 'start of month')")
        convs_month = cursor.fetchone()[0]
        
        # Tickets escalados pendientes
        cursor.execute("SELECT COUNT(*) FROM tickets_escalados WHERE estado = 'pendiente'")
        tickets_pend = cursor.fetchone()[0]
        
        conn.close()
        
        return (
            f"📊 *Estadísticas de Lex Guardian:*\n\n"
            f"• *Conversaciones este mes:* {convs_month}\n"
            f"• *Citas activas agendadas:* {citas_count}\n"
            f"• *Facturas comerciales emitidas:* {facturas_count}\n"
            f"• *Tickets de escalado pendientes:* {tickets_pend}"
        )

    # --- COMANDO: /agenda ---
    elif cmd == "/agenda":
        db_path = os.getenv("DB_PATH", "chatbot.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        hoy = datetime.now().strftime("%Y-%m-%d")
        manana = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        
        cursor.execute("""
            SELECT id, tipo, titulo, hora, fecha 
            FROM agenda_interna 
            WHERE fecha IN (?, ?) AND completado = 0
            ORDER BY fecha ASC, hora ASC
        """, (hoy, manana))
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return "📅 No tienes citas, tareas ni recordatorios pendientes para hoy ni mañana."
            
        respuesta = "📅 *Tu Agenda (Hoy y Mañana):*\n"
        for r_id, tipo, title, h, f in rows:
            day_label = "Hoy" if f == hoy else "Mañana"
            icon = "🤝" if tipo == "cita" else "📝" if tipo == "tarea" else "🔔"
            hora_str = f" a las {h}" if h else ""
            respuesta += f"\n• [{day_label}] {icon} *{title}*{hora_str} (ID: {r_id})"
        return respuesta
        
    # --- COMANDO: /agenda_semana ---
    elif cmd == "/agenda_semana":
        db_path = os.getenv("DB_PATH", "chatbot.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        hoy = datetime.now().strftime("%Y-%m-%d")
        en_7_dias = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
        
        cursor.execute("""
            SELECT id, tipo, titulo, hora, fecha 
            FROM agenda_interna 
            WHERE fecha BETWEEN ? AND ? AND completado = 0
            ORDER BY fecha ASC, hora ASC
        """, (hoy, en_7_dias))
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return "📅 No tienes pendientes programados para los próximos 7 días."
            
        respuesta = "📅 *Agenda de los próximos 7 días:*\n"
        current_date = None
        for r_id, tipo, title, h, f in rows:
            if f != current_date:
                current_date = f
                f_dt = datetime.strptime(f, "%Y-%m-%d")
                respuesta += f"\n*📅 {f_dt.strftime('%d/%m (%A)')}:*\n"
            icon = "🤝" if tipo == "cita" else "📝" if tipo == "tarea" else "🔔"
            hora_str = f" [{h}]" if h else ""
            respuesta += f"  {icon} {title}{hora_str} (ID: {r_id})\n"
        return respuesta
        
    # --- COMANDO: /plazos ---
    elif cmd == "/plazos":
        db_path = os.getenv("DB_PATH", "chatbot.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        hoy = datetime.now().strftime("%Y-%m-%d")
        en_30_dias = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
        
        cursor.execute("""
            SELECT id, modelo, cliente, fecha_limite, completado 
            FROM plazos_fiscales 
            WHERE fecha_limite BETWEEN ? AND ?
            ORDER BY fecha_limite ASC
        """, (hoy, en_30_dias))
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return "📅 No hay plazos fiscales programados en los próximos 30 días."
            
        respuesta = "📅 *Próximos Plazos Fiscales (30 días):*\n"
        for r_id, modelo, cliente, f_limite, comp in rows:
            estado_icon = "✅" if comp == 1 else "⏳"
            respuesta += f"\n{estado_icon} *{modelo}* ({cliente}) - Límite: {f_limite} (ID: {r_id})"
        return respuesta
        
    # --- COMANDO: /completar ---
    elif cmd == "/completar":
        if not args:
            return "Por favor, especifica el ID del elemento a completar. Ejemplo: `/completar 12`."
            
        try:
            item_id = int(args.strip())
        except ValueError:
            return "ID inválido. Escribe un número."
            
        db_path = os.getenv("DB_PATH", "chatbot.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT titulo, tipo FROM agenda_interna WHERE id = ?", (item_id,))
        row = cursor.fetchone()
        
        if not row:
            conn.close()
            return f"No se encontró ningún elemento en la agenda con ID {item_id}."
            
        cursor.execute("UPDATE agenda_interna SET completado = 1 WHERE id = ?", (item_id,))
        conn.commit()
        conn.close()
        
        return f"✅ Completado: Se ha marcado como realizado '{row[0]}' ({row[1]})."
        
    # --- COMANDO: /plazo_fiscal ---
    elif cmd == "/plazo_fiscal":
        if not args:
            return "Uso: `/plazo_fiscal \"{modelo}\" \"{cliente}\" {fecha}`"
            
        import shlex
        try:
            parts = shlex.split(args)
            if len(parts) < 3:
                return "Faltan argumentos. Uso: `/plazo_fiscal \"{modelo}\" \"{cliente}\" {fecha}`"
            modelo = parts[0]
            cliente = parts[1]
            fecha_limite = parts[2]
            
            datetime.strptime(fecha_limite, "%Y-%m-%d")
        except Exception as err:
            return f"Error en los parámetros: {err}. Asegúrate de usar comillas si contienen espacios y la fecha en formato YYYY-MM-DD."
            
        db_path = os.getenv("DB_PATH", "chatbot.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO plazos_fiscales (modelo, cliente, fecha_limite, completado)
            VALUES (?, ?, ?, 0)
        """, (modelo, cliente, fecha_limite))
        conn.commit()
        conn.close()
        
        return f"📅 Plazo fiscal añadido: {modelo} para el cliente '{cliente}' con fecha límite {fecha_limite}."
        
    # --- COMANDO: /responder_{id} {mensaje} ---
    elif cmd.startswith("/responder_"):
        try:
            # Extraer ID del comando tipo /responder_123
            ticket_id_str = cmd.replace("/responder_", "")
            ticket_id = int(ticket_id_str)
        except ValueError:
            return "Formato inválido. Usa `/responder_{id} {tu_mensaje}`."
            
        if not args:
            return "Por favor, escribe un mensaje para enviarle al cliente."
            
        db_path = os.getenv("DB_PATH", "chatbot.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Obtener el teléfono del cliente del ticket
        cursor.execute("SELECT phone_number FROM tickets_escalados WHERE id = ?", (ticket_id,))
        row = cursor.fetchone()
        
        if not row:
            conn.close()
            return f"No se encontró ningún ticket de escalado con ID {ticket_id}."
            
        client_phone = row[0]
        conn.close()
        
        # Enviar WhatsApp al cliente
        enviado = whatsapp.send_whatsapp_message(client_phone, args)
        if enviado:
            # Guardar el mensaje del gestor en el historial del cliente
            database.save_message(client_phone, "assistant", f"[Gestor]: {args}")
            # Cambiar estado del ticket a en_gestion
            from escalado_humano import actualizar_estado_ticket
            actualizar_estado_ticket(ticket_id, "en_gestion")
            return f"Mensaje enviado con éxito al cliente {client_phone} ✅"
        else:
            return f"No se pudo enviar el mensaje por WhatsApp al cliente {client_phone} ❌"
            
    else:
        return f"Comando no reconocido. Escribe `/ayuda` para ver la lista de comandos."
