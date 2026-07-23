import os
import re
import json
import logging
import asyncio
from datetime import datetime, timedelta
from google import genai
from google.genai import types
import whatsapp
import database

logger = logging.getLogger(__name__)

def esta_en_triaje(phone_number: str) -> bool:
    return database.get_session(phone_number, "triaje") is not None

async def enviar_email_profesional(datos: dict, datos_ia: dict, foto_path: str) -> bool:
    import email_adapter
    
    email_profesional = os.getenv("PROFESIONAL_EMAIL")
    if not email_profesional:
        logger.warning("Falta configuración de PROFESIONAL_EMAIL para notificar al profesional.")
        return False
        
    try:
        urgencia = datos.get("urgencia", "Normal")
        categoria = datos_ia.get("categoria", "otro").capitalize()
        resumen = datos_ia.get("resumen", "")
        complejidad = datos_ia.get("complejidad", "medio").capitalize()
        justificacion = datos_ia.get("justificacion_complejidad", "")
        
        asunto = f"Nueva Solicitud [{urgencia}] — [{categoria}] — CP {datos.get('cp')}"
        
        html_body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6;">
            <h2 style="color: #007bff; border-bottom: 2px solid #007bff; padding-bottom: 8px;">🔧 Nueva Solicitud de Trabajo (Triaje)</h2>
            <p>Se ha recibido una nueva solicitud del cliente por WhatsApp:</p>
            <table style="width: 100%; border-collapse: collapse; margin-top: 15px;">
                <tr>
                    <td style="padding: 8px; font-weight: bold; width: 150px; background-color: #f9f9f9; border: 1px solid #ddd;">Teléfono Cliente:</td>
                    <td style="padding: 8px; border: 1px solid #ddd;">{datos.get('phone_number')}</td>
                </tr>
                <tr>
                    <td style="padding: 8px; font-weight: bold; background-color: #f9f9f9; border: 1px solid #ddd;">Código Postal:</td>
                    <td style="padding: 8px; border: 1px solid #ddd;">{datos.get('cp')}</td>
                </tr>
                <tr>
                    <td style="padding: 8px; font-weight: bold; background-color: #f9f9f9; border: 1px solid #ddd;">Urgencia:</td>
                    <td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">{urgencia}</td>
                </tr>
                <tr>
                    <td style="padding: 8px; font-weight: bold; background-color: #f9f9f9; border: 1px solid #ddd;">Categoría IA:</td>
                    <td style="padding: 8px; border: 1px solid #ddd;">{categoria}</td>
                </tr>
                <tr>
                    <td style="padding: 8px; font-weight: bold; background-color: #f9f9f9; border: 1px solid #ddd;">Resumen Técnico:</td>
                    <td style="padding: 8px; border: 1px solid #ddd;">{resumen}</td>
                </tr>
                <tr>
                    <td style="padding: 8px; font-weight: bold; background-color: #f9f9f9; border: 1px solid #ddd;">Complejidad IA:</td>
                    <td style="padding: 8px; border: 1px solid #ddd;"><strong>{complejidad}</strong> — {justificacion}</td>
                </tr>
            </table>
        """
        
        adjuntos = []
        if foto_path and os.path.exists(foto_path):
            html_body += """
            <div style="margin-top: 20px;">
                <h3>Imagen adjunta por el cliente:</h3>
                <img src="cid:foto_triaje" style="max-width: 100%; height: auto; border: 1px solid #ddd; border-radius: 4px;" />
            </div>
            """
            adjuntos.append({
                "filepath": foto_path,
                "filename": os.path.basename(foto_path),
                "content_id": "foto_triaje",
                "is_inline": True
            })
            
        html_body += """
        </body>
        </html>
        """
        
        return await email_adapter.enviar_email(
            destinatario=email_profesional,
            asunto=asunto,
            cuerpo_html=html_body,
            adjuntos=adjuntos
        )
    except Exception as e:
        logger.error(f"Error enviando email al profesional: {e}")
        return False

async def analizar_solicitud_con_ia(datos: dict) -> dict:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return {
            "categoria": "otro",
            "resumen": datos.get("descripcion", ""),
            "complejidad": "medio",
            "justificacion_complejidad": "Sin API Key para análisis."
        }
        
    try:
        def _call_gemini_vision_triaje():
            client = genai.Client(api_key=api_key)
            prompt = f"""
            Analiza la siguiente solicitud de presupuesto para un servicio comercial:
            - Descripción: "{datos.get('descripcion')}"
            - Código Postal: {datos.get('cp')}
            - Urgencia: {datos.get('urgencia')}

            Determina:
            1. categoria: Clasifica en una de estas exactamente: fontanería, electricidad, carpintería, pintura, reformas generales, limpieza, jardinería, otro.
            2. resumen: Resumen ejecutivo claro y técnico de 2-3 líneas para el profesional.
            3. complejidad: bajo, medio o alto.
            4. justificacion_complejidad: Una línea justificando el nivel asignado.

            Devuelve ÚNICAMENTE un JSON válido con esta estructura:
            {{
                "categoria": "fontanería | electricidad | carpintería | pintura | reformas generales | limpieza | jardinería | otro",
                "resumen": "Resumen...",
                "complejidad": "bajo | medio | alto",
                "justificacion_complejidad": "Justificación..."
            }}
            """
            
            contents = []
            foto_path = datos.get("foto_path")
            if foto_path and os.path.exists(foto_path):
                with open(foto_path, 'rb') as f:
                    file_bytes = f.read()
                part = types.Part.from_bytes(data=file_bytes, mime_type='image/jpeg')
                contents.append(part)
                
            contents.append(prompt)
            
            respuesta = client.models.generate_content(
                model='gemini-2.0-flash',
                contents=contents,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json"
                )
            )
            return json.loads(respuesta.text.strip())

        from gemini_limiter import limiter
        async with limiter:
            return await asyncio.to_thread(_call_gemini_vision_triaje)
    except Exception as e:
        logger.error(f"Error analizando triaje con Gemini: {e}")
        return {
            "categoria": "otro",
            "resumen": datos.get("descripcion"),
            "complejidad": "medio",
            "justificacion_complejidad": "Fallo al conectar con Gemini."
        }

async def gestionar_triaje(phone_number: str, message: str, msg_type: str = "text") -> str:
    """
    Máquina de estados conversacional para el triaje con persistencia SQLite.
    """
    session = database.get_session(phone_number, "triaje")
    
    if not session:
        session = {
            "phone_number": phone_number,
            "descripcion": "",
            "cp": "",
            "urgencia": "",
            "foto_path": None,
            "estado": "esperando_descripcion"
        }
        database.save_session(phone_number, "triaje", session)
        return (
            "🛠️ *Formulario de Solicitud de Presupuesto*\n\n"
            "Por favor, describe en detalle qué avería o trabajo necesitas que realicemos (mínimo 20 caracteres):"
        )

    if msg_type == "image":
        session["foto_path"] = message
        database.save_session(phone_number, "triaje", session)
        logger.info(f"Foto de triaje guardada para {phone_number} en {message}")
        
        if session["estado"] == "esperando_descripcion":
            return "📸 ¡Foto recibida! Por favor, continúa describiendo detalladamente el trabajo que necesitas (mínimo 20 caracteres):"
        elif session["estado"] == "esperando_cp":
            return "📸 ¡Foto recibida! Por favor, facilítame ahora tu Código Postal (5 dígitos):"
        elif session["estado"] == "esperando_urgencia":
            return (
                "📸 ¡Foto recibida! Por favor, indícame la urgencia seleccionando una opción:\n"
                "1. Urgente\n"
                "2. Normal\n"
                "3. No urgente"
            )

    if session["estado"] == "esperando_descripcion":
        if len(message.strip()) < 20:
            return "La descripción debe tener al menos 20 caracteres para que el profesional pueda entenderla. Cuéntame un poco más:"
        session["descripcion"] = message.strip()
        session["estado"] = "esperando_cp"
        database.save_session(phone_number, "triaje", session)
        return "Guardado. 📍 Facilítame ahora tu Código Postal (5 dígitos) de España:"

    elif session["estado"] == "esperando_cp":
        cp_clean = message.strip()
        if not re.match(r'^\d{5}$', cp_clean):
            return "El código postal debe constar de exactamente 5 números. Por favor, indícalo de nuevo:"
        session["cp"] = cp_clean
        session["estado"] = "esperando_urgencia"
        database.save_session(phone_number, "triaje", session)
        return (
            "Entendido. ¿Cuál es el nivel de urgencia para este trabajo?\n"
            "1. Urgente (requiere atención rápida)\n"
            "2. Normal (en los próximos días)\n"
            "3. No urgente (puedo esperar)"
        )

    elif session["estado"] == "esperando_urgencia":
        urg_choice = message.strip()
        urgencia_map = {
            "1": "Urgente",
            "2": "Normal",
            "3": "No urgente"
        }
        
        urgencia_text = None
        if urg_choice in urgencia_map:
            urgencia_text = urgencia_map[urg_choice]
        elif "urgente" in urg_choice.lower():
            if "no" in urg_choice.lower():
                urgencia_text = "No urgente"
            else:
                urgencia_text = "Urgente"
        elif "normal" in urg_choice.lower():
            urgencia_text = "Normal"
            
        if not urgencia_text:
            return "Por favor, introduce 1, 2 o 3 para indicar la urgencia."
            
        session["urgencia"] = urgencia_text
        
        logger.info(f"Triaje completado para {phone_number}. Iniciando análisis...")
        datos_ia = await analizar_solicitud_con_ia(session)
        
        email_enviado = await enviar_email_profesional(session, datos_ia, session["foto_path"])
        
        prof_phone = os.getenv("PROFESIONAL_WHATSAPP")
        whatsapp_enviado = False
        if prof_phone:
            mensaje_prof = (
                "🔧 *NUEVA SOLICITUD DE TRIAJE*\n\n"
                f"👤 *Cliente:* {phone_number}\n"
                f"📍 *CP:* {session['cp']}\n"
                f"⏰ *Urgencia:* {session['urgencia']}\n"
                f"🛠️ *Resumen:* {datos_ia.get('resumen')}\n"
                f"📊 *Complejidad:* {datos_ia.get('complejidad')} - {datos_ia.get('justificacion_complejidad')}"
            )
            whatsapp_enviado = await whatsapp.send_whatsapp_message(prof_phone, mensaje_prof)
            
        foto_path = session.get("foto_path")
        if foto_path and os.path.exists(foto_path):
            try:
                os.remove(foto_path)
                logger.info(f"Foto temporal de triaje eliminada tras procesar: {foto_path}")
            except Exception as fe:
                logger.error(f"Error al eliminar foto temporal de triaje finalizado: {fe}")
        
        database.delete_session(phone_number, "triaje")
        return "¡Perfecto! Tu solicitud ha sido registrada y enviada al profesional correspondiente. Se pondrán en contacto contigo lo antes posible. ¡Gracias! 👍"

async def limpiar_archivos_temporales_antiguos():
    """
    Escanea la carpeta de temporales 'storage/temp/' y borra archivos con más de 2 horas de antigüedad.
    """
    storage_ruta = os.getenv("STORAGE_RUTA", "./storage")
    temp_dir = os.path.join(storage_ruta, "temp")
    if not os.path.exists(temp_dir):
        return
        
    ahora = datetime.now()
    limite = ahora - timedelta(hours=2)
    
    logger.info("Iniciando escaneo y limpieza de archivos temporales antiguos en storage/temp...")
    try:
        def _cleanup():
            count = 0
            for filename in os.listdir(temp_dir):
                filepath = os.path.join(temp_dir, filename)
                if os.path.isfile(filepath):
                    if filename.startswith('.'):
                        continue
                    mtime = datetime.fromtimestamp(os.path.getmtime(filepath))
                    if mtime < limite:
                        os.remove(filepath)
                        logger.info(f"Archivo temporal antiguo eliminado: {filepath}")
                        count += 1
            if count > 0:
                logger.info(f"Limpieza completada. Se eliminaron {count} archivo(s) temporal(es) antiguo(s).")
                
        await asyncio.to_thread(_cleanup)
    except Exception as e:
        logger.error(f"Error durante la limpieza de temporales de triaje: {e}")
