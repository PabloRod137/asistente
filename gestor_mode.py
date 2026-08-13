import os
import sqlite3
import logging
import httpx
import asyncio
from datetime import datetime, timedelta
import whatsapp
import database

logger = logging.getLogger(__name__)

_esperando_actualizacion = False

async def procesar_comando(phone_number: str, message: str) -> str:
    """
    Procesa los comandos del gestor de forma asíncrona. Retorna la respuesta de texto correspondiente.
    """
    global _esperando_actualizacion
    
    msg_strip = message.strip()
    
    if _esperando_actualizacion:
        _esperando_actualizacion = False
        try:
            dir_path = os.path.dirname(os.path.abspath(__file__))
            txt_path = os.path.join(dir_path, "knowledge.txt")
            
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(txt_path, "a", encoding="utf-8") as f:
                f.write(f"\n\n=== ACTUALIZACIÓN GESTOR ({now_str}) ===\n{msg_strip}\n")
                
            logger.info("Base de conocimiento actualizada con comando /actualizar.")
            return "Base de conocimiento actualizada ✅"
        except Exception as e:
            logger.error(f"Error escribiendo en knowledge.txt: {e}")
            return "Error al actualizar la base de conocimiento ❌"
            
    if not msg_strip.startswith("/"):
        try:
            import secretaria
            datos_accion = await secretaria.interpretar_mensaje_interno(message)
            if datos_accion is not None:
                return secretaria.ejecutar_accion_interno(datos_accion)
        except Exception as se:
            logger.error(f"Error procesando lenguaje natural con modulo secretaria: {se}")
        return None
        
    cmd_parts = msg_strip.split(maxsplit=1)
    cmd = cmd_parts[0].lower()
    args = cmd_parts[1] if len(cmd_parts) > 1 else ""
    
    if cmd == "/ayuda":
        return (
            "🛠️ *Comandos del Gestor Disponibles:*\n\n"
            "• `/clientes_hoy` - Ver clientes activos hoy y motivo.\n"
            "• `/clientes_nuevos` - Listar clientes pendientes de revisión CRM.\n"
            "• `/alta_cliente {tel} \"{exp}\" \"{nom}\"` - Activar cliente y asignar expediente.\n"
            "• `/cliente_info {tel}` - Consulta ficha completa de un cliente.\n"
            "• `/resumen_semana` - Genera y envía resumen semanal por email.\n"
            "• `/pendientes` - Lista clientes con pendientes para el gestor.\n"
            "• `/actualizar` - Añadir nueva información a la base de conocimiento.\n"
            "• `/stats` - Estadísticas del negocio este mes.\n"
            "• `/exportar_gastos {cif}` - Exportar gastos de un CIF a Excel en SharePoint.\n"
            "• `/responder_{id} {mensaje}` - Responder a un ticket de escalado.\n\n"
            "📂 *Comandos de Expedientes (Fase 7):*\n"
            "• `/expediente_nuevo {tel} \"{tipo}\" \"{titulo}\"` - Crear un expediente.\n"
            "• `/expediente_estado {id} {estado}` - Cambiar estado (recibido, en_gestion, resuelto).\n"
            "• `/expedientes_abiertos` - Listar todos los expedientes abiertos por gestor.\n"
            "• `/mis_expedientes {gestor}` - Filtrar expedientes por gestor.\n\n"
            "💼 *Comandos de Agenda Interna y Recordatorios:*\n"
            "• `/agenda` - Tareas, citas y recordatorios de hoy y mañana.\n"
            "• `/agenda_semana` - Agenda de los próximos 7 días.\n"
            "• `/plazos` - Próximos plazos fiscales (30 días).\n"
            "• `/completar {id}` - Completar tarea/cita de la agenda.\n"
            "• `/plazo_fiscal \"{modelo}\" \"{cliente}\" {fecha} {tel_opcional}` - Añadir plazo fiscal.\n"
            "• `/documento_pendiente {tel} \"{desc}\" {fecha_limite}` - Dar de alta documento pendiente.\n"
            "• `/documento_recibido {id}` - Marcar documento pendiente como recibido.\n"
            "• `/pendientes_documentos` - Listar documentos pendientes de entrega por clientes.\n\n"
            "🎙️ *Captura Estructurada (Fase 8):*\n"
            "• `/capturas_pendientes` - Listar las últimas capturas estructuradas sin revisar.\n"
            "• `/captura_revisada {id}` - Marcar una captura estructurada como revisada."
        )
        
    elif cmd == "/clientes_hoy":
        conn = database.get_connection()
        cursor = conn.cursor()
        
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
        
    elif cmd == "/capturas_pendientes":
        capturas = database.get_capturas_pendientes(limit=10)
        if not capturas:
            return "No hay capturas estructuradas pendientes de revisión."

        respuesta = "🎙️ *Capturas estructuradas pendientes:*\n"
        for c in capturas:
            confianza_str = f"{c['confianza']}%" if c['confianza'] is not None else "?"
            respuesta += (
                f"\n#{c['id']} — *{c['phone_number']}* ({c['canal']}, confianza {confianza_str})\n"
                f"  👤 Cliente: {c['cliente_probable'] or '—'} | 📂 Área: {c['area_probable'] or '—'}\n"
                f"  📝 Asunto: {c['asunto'] or '—'}\n"
                f"  ⏰ Urgencia: {c['urgencia'] or '—'} | 🛠️ Servicio: {c['servicio_sugerido'] or '—'}\n"
                f"  📄 Docs mencionados: {c['documentos_mencionados'] or '—'} | 📁 Expediente probable: {c['expediente_probable'] or '—'}\n"
                f"  💬 Solicitud: {c['solicitud'] or '—'}\n"
            )
        respuesta += "\nUsa `/captura_revisada {id}` para marcar una como revisada."
        return respuesta

    elif cmd == "/captura_revisada":
        captura_id_str = args.strip()
        if not captura_id_str.isdigit():
            return "Formato incorrecto. Usa: /captura_revisada {id}"
        ok = database.marcar_captura_revisada(int(captura_id_str))
        if ok:
            return f"Captura #{captura_id_str} marcada como revisada ✅"
        return f"No se encontró ninguna captura pendiente con id #{captura_id_str}."

    elif cmd == "/resumen_semana":
        conn = database.get_connection()
        cursor = conn.cursor()
        
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

        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent?key={api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}]
        }
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, json=payload, headers={'Content-Type': 'application/json'})
                response.raise_for_status()
                summary_weekly = response.json()["candidates"][0]["content"]["parts"][0]["text"]
                
                from conversation_summary import enviar_email
                await enviar_email("Semanal", f"<h3>Resumen Ejecutivo Semanal</h3><hr/>{summary_weekly}", comb_text)
                
                return f"📊 *Resumen Semanal Generado y Enviado por Correo:*\n\n{summary_weekly}"
        except Exception as e:
            logger.error(f"Error generando resumen semanal: {e}")
            return f"Error al generar o enviar el resumen semanal: {e}"
            
    elif cmd == "/pendientes":
        conn = database.get_connection()
        cursor = conn.cursor()
        
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
            if "pendiente" in res_lower:
                pendientes.append(f"• *Cliente: {phone}*\n{res}\n")
                
        if not pendientes:
            return "No se encontraron conversaciones con pendientes para el gestor."
            
        return "📋 *Pendientes actuales detectados en conversaciones:*\n\n" + "\n".join(pendientes)
        
    elif cmd == "/actualizar":
        _esperando_actualizacion = True
        return "Manda el nuevo contenido y lo añado a mi base de conocimiento."
        
    elif cmd == "/stats":
        conn = database.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM citas WHERE estado = 'confirmada'")
        citas_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM facturas")
        facturas_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM conversaciones WHERE inicio >= date('now', 'start of month')")
        convs_month = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM gastos_tickets")
        gastos_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM tickets_escalados WHERE estado = 'pendiente'")
        tickets_pend = cursor.fetchone()[0]
        
        conn.close()
        
        return (
            f"📊 *Estadísticas de Lex Guardian:*\n\n"
            f"• *Conversaciones este mes:* {convs_month}\n"
            f"• *Citas activas agendadas:* {citas_count}\n"
            f"• *Facturas comerciales emitidas:* {facturas_count}\n"
            f"• *Tickets de gastos registrados:* {gastos_count}\n"
            f"• *Tickets de escalado pendientes:* {tickets_pend}"
        )

    elif cmd == "/exportar_gastos":
        cif = args.strip().upper()
        if not cif:
            return "Uso: `/exportar_gastos {cif}`. Ejemplo: `/exportar_gastos B12345678`"
            
        gastos = database.get_gastos_by_cif(cif)
        if not gastos:
            return f"No se encontraron gastos registrados para el CIF: {cif}."
            
        import openpyxl
        from openpyxl import Workbook
        import io
        import storage_adapter
        
        def _build_excel():
            wb = Workbook()
            ws = wb.active
            ws.title = "Gastos"
            headers = [
                "Fecha", "Emisor", "CIF Emisor", "Base Imponible", 
                "% IVA", "Cuota IVA", "Total", "Ruta Archivo", "Fecha Registro"
            ]
            ws.append(headers)
            for g in gastos:
                ws.append([
                    g["fecha"], g["emisor"], g["cif_emisor"], g["base_imponible"],
                    g["porcentaje_iva"], g["cuota_iva"], g["total"], g["ruta_imagen"], g["creado_en"]
                ])
            excel_buffer = io.BytesIO()
            wb.save(excel_buffer)
            return excel_buffer.getvalue()
            
        excel_bytes = await asyncio.to_thread(_build_excel)
        
        carpeta_tickets = os.getenv("SHAREPOINT_CARPETA_TICKETS", "gastos_clientes").strip("/")
        fecha_exp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"gastos_{cif}_{fecha_exp}.xlsx"
        logical_path = f"{carpeta_tickets}/{cif}/{filename}"
        
        try:
            await storage_adapter.guardar_archivo(logical_path, excel_bytes)
            return f"Excel de gastos para el CIF {cif} exportado con éxito en: {logical_path} ✅"
        except Exception as e:
            logger.error(f"Error al subir Excel de gastos a SharePoint: {e}")
            return f"Error al subir el Excel de gastos a SharePoint: {e} ❌"

    elif cmd == "/clientes_nuevos":
        nuevos = database.get_clientes_nuevos()
        if not nuevos:
            return "📋 No hay clientes nuevos pendientes de revisión."
            
        res = f"📋 *Clientes Nuevos Pendientes de Revisión ({len(nuevos)}):*\n\n"
        for c in nuevos:
            tel = c["phone_number"]
            nom = c["nombre"] or "Sin nombre"
            nif = c["nif_cif"] or "Sin NIF/CIF"
            fecha = c["fecha_alta"] or c["primera_visita"] or "N/A"
            res += f"• *{nom}* (`{tel}`)\n  - NIF/CIF: `{nif}`\n  - Fecha Alta: {fecha}\n"
            
        res += "\nPara activar un cliente use:\n`/alta_cliente {telefono} \"{expediente}\" \"{nombre}\"`"
        return res

    elif cmd == "/alta_cliente":
        if not args:
            return "Uso: `/alta_cliente {telefono} \"{expediente}\" \"{nombre_opcional}\"`"
            
        import shlex
        try:
            tokens = shlex.split(args)
        except Exception:
            tokens = args.split()
            
        if len(tokens) < 2:
            return "Uso: `/alta_cliente {telefono} \"{expediente}\" \"{nombre_opcional}\"`"
            
        phone_target = tokens[0].strip()
        expediente = tokens[1].strip()
        nombre_opt = tokens[2].strip() if len(tokens) > 2 else None
        
        ok = database.activar_cliente(phone_target, expediente, nombre_opcional=nombre_opt)
        if ok:
            cli = database.get_cliente_by_phone(phone_target)
            nombre_final = cli.get("nombre") if cli else (nombre_opt or phone_target)
            return f"✅ Cliente `{phone_target}` (*{nombre_final}*) activado con éxito con expediente `{expediente}`."
        else:
            return f"❌ No se encontró ningún cliente registrado con el teléfono `{phone_target}`."

    elif cmd == "/cliente_info":
        phone_target = args.strip()
        if not phone_target:
            return "Uso: `/cliente_info {telefono}`"
            
        cli = database.get_cliente_by_phone(phone_target)
        if not cli:
            return f"❌ No existe ningún cliente con el teléfono `{phone_target}`."
            
        return (
            f"👤 *Ficha del Cliente:* `{phone_target}`\n"
            f"• *Nombre:* {cli.get('nombre') or 'Sin nombre'}\n"
            f"• *Estado CRM:* `{cli.get('tipo_cliente') or 'nuevo'}`\n"
            f"• *Expediente:* `{cli.get('numero_expediente') or 'Sin expediente'}`\n"
            f"• *NIF/CIF:* `{cli.get('nif_cif') or 'Sin NIF/CIF'}`\n"
            f"• *Empresa:* {cli.get('empresa') or 'No indicada'}\n"
            f"• *Email:* {cli.get('email') or 'No indicado'}\n"
            f"• *Gestor Asignado:* {cli.get('gestor_asignado') or 'No asignado'}\n"
            f"• *Notas:* {cli.get('notas') or 'Sin notas'}\n"
            f"• *Primera Visita:* {cli.get('primera_visita') or 'N/A'}\n"
            f"• *Última Visita:* {cli.get('ultima_visita') or 'N/A'}\n"
            f"• *Total Conversaciones:* {cli.get('total_conversaciones') or 1}"
        )

    elif cmd == "/agenda":
        conn = database.get_connection()
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
        
    elif cmd == "/agenda_semana":
        conn = database.get_connection()
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
        
    elif cmd == "/plazos":
        conn = database.get_connection()
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
        
    elif cmd == "/completar":
        if not args:
            return "Por favor, especifica el ID del elemento a completar. Ejemplo: `/completar 12`."
            
        try:
            item_id = int(args.strip())
        except ValueError:
            return "ID inválido. Escribe un número."
            
        conn = database.get_connection()
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
        
    elif cmd == "/plazo_fiscal":
        if not args:
            return "Uso: `/plazo_fiscal \"{modelo}\" \"{cliente}\" {fecha} {telefono_opcional}`"
            
        import shlex
        try:
            parts = shlex.split(args)
            if len(parts) < 3:
                return "Faltan argumentos. Uso: `/plazo_fiscal \"{modelo}\" \"{cliente}\" {fecha} {telefono_opcional}`"
            modelo = parts[0]
            cliente = parts[1]
            fecha_limite = parts[2]
            tel_opt = parts[3] if len(parts) > 3 else None
            
            datetime.strptime(fecha_limite, "%Y-%m-%d")
        except Exception as err:
            return f"Error en los parámetros: {err}. Asegúrate de usar comillas si contienen espacios y la fecha en formato YYYY-MM-DD."
            
        tel_norm = database.normalizar_telefono(tel_opt) if tel_opt else None
        conn = database.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO plazos_fiscales (modelo, cliente, fecha_limite, completado, phone_number, recordatorio_enviado)
            VALUES (?, ?, ?, 0, ?, 0)
        """, (modelo, cliente, fecha_limite, tel_norm))
        conn.commit()
        conn.close()
        
        info_tel = f" (Asociado a cliente `{tel_norm}`)" if tel_norm else ""
        return f"📅 Plazo fiscal añadido: {modelo} para el cliente '{cliente}' con fecha límite {fecha_limite}.{info_tel}"

    elif cmd == "/documento_pendiente":
        if not args:
            return "Uso: `/documento_pendiente {telefono} \"{descripcion}\" {fecha_limite}`"
        import shlex
        try:
            parts = shlex.split(args)
            if len(parts) < 3:
                return "Faltan argumentos. Uso: `/documento_pendiente {telefono} \"{descripcion}\" {fecha_limite}`"
            tel = parts[0]
            desc = parts[1]
            fecha_lim = parts[2]
            datetime.strptime(fecha_lim, "%Y-%m-%d")
        except Exception as err:
            return f"Error en los parámetros: {err}. Ejemplo: `/documento_pendiente 34611223344 \"Declaración IRPF 2025\" 2026-07-25`"
            
        doc_id = database.save_documento_pendiente(tel, desc, fecha_lim)
        tel_norm = database.normalizar_telefono(tel)
        return f"📄 Documento pendiente registrado con éxito (ID: `{doc_id}`) para el cliente `{tel_norm}` con fecha límite {fecha_lim}."

    elif cmd == "/documento_recibido":
        if not args:
            return "Uso: `/documento_recibido {id}`"
        try:
            doc_id = int(args.strip())
        except ValueError:
            return "ID inválido. Debe ser un número."
            
        ok = database.marcar_documento_recibido(doc_id)
        if ok:
            return f"✅ Documento #{doc_id} marcado como RECIBIDO correctamente."
        else:
            return f"❌ No se encontró ningún documento pendiente con ID {doc_id}."

    elif cmd == "/pendientes_documentos":
        docs = database.get_todos_documentos_pendientes()
        if not docs:
            return "📄 No hay documentos pendientes de entregar por clientes."
            
        res = f"📄 *Documentos Pendientes de Clientes ({len(docs)}):*\n\n"
        for d in docs:
            status_tag = "⚠️ VENCIDO" if d["vencido"] else "⏳ Pendiente"
            nom = d["cliente_nombre"]
            tel = d["phone_number"]
            res += (
                f"• [{status_tag}] *ID {d['id']}*: {d['descripcion']}\n"
                f"  - Cliente: *{nom}* (`{tel}`)\n"
                f"  - Límite: {d['fecha_limite']} (Recordado: {d['veces_recordado']} veces)\n"
            )
        return res
        
    elif cmd.startswith("/responder_"):
        try:
            ticket_id_str = cmd.replace("/responder_", "")
            ticket_id = int(ticket_id_str)
        except ValueError:
            return "Formato inválido. Usa `/responder_{id} {tu_mensaje}`."
            
        if not args:
            return "Por favor, escribe un mensaje para enviarle al cliente."
            
        conn = database.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT phone_number FROM tickets_escalados WHERE id = ?", (ticket_id,))
        row = cursor.fetchone()
        
        if not row:
            conn.close()
            return f"No se encontró ningún ticket de escalado con ID {ticket_id}."
            
        client_phone = row[0]
        conn.close()
        
        enviado = await whatsapp.send_whatsapp_message(client_phone, args)
        if enviado:
            database.save_message(client_phone, "assistant", f"[Gestor]: {args}")
            from escalado_humano import actualizar_estado_ticket
            actualizar_estado_ticket(ticket_id, "en_gestion")
            return f"Mensaje enviado con éxito al cliente {client_phone} ✅"
        else:
            return f"No se pudo enviar el mensaje por WhatsApp al cliente {client_phone} ❌"
    elif cmd == "/expediente_nuevo":
        import re
        match = re.match(r'^(\d+)\s+["\']?([^"\']+)["\']?\s+["\']?([^"\']+)["\']?$', args.strip())
        if not match:
            return "Formato inválido. Usa `/expediente_nuevo {tel} \"{tipo}\" \"{titulo}\"`."
        
        tel = match.group(1).strip()
        tipo = match.group(2).strip().lower()
        titulo = match.group(3).strip()
        
        valid_tipos = {"fiscal", "laboral", "mercantil", "civil", "compliance", "general"}
        if tipo not in valid_tipos:
            return f"❌ Tipo de expediente inválido. Debe ser uno de: {', '.join(valid_tipos)}."
            
        cli = database.get_cliente_by_phone(tel)
        if not cli:
            return f"❌ El cliente con teléfono {tel} no existe en el CRM. Por favor, regístralo primero."
            
        gestor = cli.get("gestor_asignado")
        sp_path = cli.get("carpeta_sharepoint")
        
        new_id = database.crear_expediente(tel, tipo, titulo, gestor_asignado=gestor, ruta_sharepoint=sp_path)
        return f"✅ Expediente #{new_id} ({titulo}) creado con éxito para el cliente {tel} (Gestor asignado: {gestor or 'Sin asignar'})."

    elif cmd == "/expediente_estado":
        import re
        match = re.match(r'^(\d+)\s+(\w+)$', args.strip())
        if not match:
            return "Formato inválido. Usa `/expediente_estado {id} {estado}`."
            
        exp_id = int(match.group(1))
        estado = match.group(2).strip().lower()
        
        valid_estados = {"recibido", "en_gestion", "resuelto"}
        if estado not in valid_estados:
            return f"❌ Estado inválido. Debe ser uno de: {', '.join(valid_estados)}."
            
        if database.actualizar_estado_expediente(exp_id, estado):
            return f"✅ Estado del expediente #{exp_id} actualizado a '{estado}' con éxito."
        else:
            return f"❌ No se encontró ningún expediente con ID {exp_id}."

    elif cmd == "/expedientes_abiertos":
        conn = database.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, phone_number, tipo, titulo, estado, gestor_asignado
            FROM expedientes WHERE estado != 'resuelto'
            ORDER BY COALESCE(gestor_asignado, ''), creado_en DESC
        ''')
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return "📂 No hay expedientes abiertos en el sistema."
            
        por_gestor = {}
        for r in rows:
            gestor = r[5] or "Sin asignar"
            if gestor not in por_gestor:
                por_gestor[gestor] = []
            por_gestor[gestor].append(r)
            
        res = "📂 *Listado de Expedientes Abiertos:*\n"
        for gestor, exps in por_gestor.items():
            res += f"\n*Gestor: {gestor}*\n"
            for e in exps:
                res += f"  - *ID {e[0]}* [{e[2].capitalize()}]: {e[3]} (Cliente: `{e[1]}`, Estado: *{e[4]}*)\n"
        return res

    elif cmd == "/mis_expedientes":
        gestor_name = args.strip()
        if not gestor_name:
            return "Por favor, especifica el nombre del gestor: `/mis_expedientes {gestor}`."
            
        conn = database.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, phone_number, tipo, titulo, estado, creado_en
            FROM expedientes
            WHERE gestor_asignado LIKE ?
            ORDER BY creado_en DESC
        ''', (f"%{gestor_name}%",))
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return f"📂 No hay expedientes asignados al gestor '{gestor_name}'."
            
        res = f"📂 *Expedientes asignados a {gestor_name} ({len(rows)}):*\n\n"
        for e in rows:
            res += f"• *ID {e[0]}* [{e[2].capitalize()}]: {e[3]} (Cliente: `{e[1]}`, Estado: *{e[4]}*)\n"
        return res

    else:
        return f"Comando no reconocido. Escribe `/ayuda` para ver la lista de comandos."
