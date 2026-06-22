import os
import re
import json
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from google import genai
from google.genai import types
import whatsapp

logger = logging.getLogger(__name__)

# Memoria temporal de la sesión de triaje
# { phone_number: { "descripcion": "...", "cp": "...", "urgencia": "...", "foto_path": "...", "estado": "..." } }
_triaje_sesiones = {}

def enviar_email_profesional(datos: dict, datos_ia: dict, foto_path: str) -> bool:
    email_emisor = os.getenv("EMAIL_EMISOR")
    email_profesional = os.getenv("PROFESIONAL_EMAIL")
    smtp_password = os.getenv("SMTP_PASSWORD")
    smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = os.getenv("SMTP_PORT", "587")
    
    if not email_emisor or not email_profesional or not smtp_password:
        logger.warning("Falta configuración de Email para notificar al profesional.")
        return False
        
    try:
        urgencia = datos.get("urgencia", "Normal")
        categoria = datos_ia.get("categoria", "otro").capitalize()
        resumen = datos_ia.get("resumen", "")
        complejidad = datos_ia.get("complejidad", "medio").capitalize()
        justificacion = datos_ia.get("justificacion_complejidad", "")
        
        asunto = f"Nueva Solicitud [{urgencia}] — [{categoria}] — CP {datos.get('cp')}"
        
        msg = MIMEMultipart("related")
        msg["Subject"] = asunto
        msg["From"] = email_emisor
        msg["To"] = email_profesional
        
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
        
        if foto_path and os.path.exists(foto_path):
            html_body += """
            <div style="margin-top: 20px;">
                <h3>Imagen adjunta por el cliente:</h3>
                <img src="cid:foto_triaje" style="max-width: 100%; height: auto; border: 1px solid #ddd; border-radius: 4px;" />
            </div>
            """
            
        html_body += """
        </body>
        </html>
        """
        
        msg.attach(MIMEText(html_body, "html", "utf-8"))
        
        if foto_path and os.path.exists(foto_path):
            with open(foto_path, 'rb') as img_file:
                msg_image = MIMEImage(img_file.read())
                msg_image.add_header('Content-ID', '<foto_triaje>')
                msg_image.add_header('Content-Disposition', 'inline', filename=os.path.basename(foto_path))
                msg.attach(msg_image)
                
        server = smtplib.SMTP(smtp_server, int(smtp_port))
        server.starttls()
        server.login(email_emisor, smtp_password)
        server.sendmail(email_emisor, email_profesional, msg.as_string())
        server.quit()
        logger.info(f"Notificación de Email enviada correctamente a {email_profesional}")
        return True
    except Exception as e:
        logger.error(f"Error enviando email al profesional: {e}")
        return False

def analizar_solicitud_con_ia(datos: dict) -> dict:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return {
            "categoria": "otro",
            "resumen": datos.get("descripcion", ""),
            "complejidad": "medio",
            "justificacion_complejidad": "Sin API Key para análisis."
        }
        
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
    
    try:
        respuesta = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=contents,
            config=types.GenerateContentConfig(
                response_mime_type="application/json"
            )
        )
        return json.loads(respuesta.text.strip())
    except Exception as e:
        logger.error(f"Error analizando triaje con Gemini: {e}")
        return {
            "categoria": "otro",
            "resumen": datos.get("descripcion"),
            "complejidad": "medio",
            "justificacion_complejidad": "Fallo al conectar con Gemini."
        }

def gestionar_triaje(phone_number: str, message: str, msg_type: str = "text") -> str:
    """
    Máquina de estados conversacional para el triaje.
    """
    session = _triaje_sesiones.get(phone_number)
    
    # 0. Inicialización
    if not session:
        _triaje_sesiones[phone_number] = {
            "phone_number": phone_number,
            "descripcion": "",
            "cp": "",
            "urgencia": "",
            "foto_path": None,
            "estado": "esperando_descripcion"
        }
        return (
            "🛠️ *Formulario de Solicitud de Presupuesto*\n\n"
            "Por favor, describe en detalle qué avería o trabajo necesitas que realicemos (mínimo 20 caracteres):"
        )

    # Si se recibe una foto en cualquier momento del triaje, guardarla y continuar
    if msg_type == "image":
        # Nota: el archivo ya se descargó en main.py y se pasó como ruta en `message`
        session["foto_path"] = message
        logger.info(f"Foto de triaje guardada para {phone_number} en {message}")
        
        # Le pedimos que continúe con el estado actual
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

    # 1. Esperando descripción
    if session["estado"] == "esperando_descripcion":
        if len(message.strip()) < 20:
            return "La descripción debe tener al menos 20 caracteres para que el profesional pueda entenderla. Cuéntame un poco más:"
        session["descripcion"] = message.strip()
        session["estado"] = "esperando_cp"
        return "Guardado. 📍 Facilítame ahora tu Código Postal (5 dígitos) de España:"

    # 2. Esperando Código Postal
    elif session["estado"] == "esperando_cp":
        cp_clean = message.strip()
        if not re.match(r'^\d{5}$', cp_clean):
            return "El código postal debe constar de exactamente 5 números. Por favor, indícalo de nuevo:"
        session["cp"] = cp_clean
        session["estado"] = "esperando_urgencia"
        return (
            "Entendido. ¿Cuál es el nivel de urgencia para este trabajo?\n"
            "1. Urgente (requiere atención rápida)\n"
            "2. Normal (en los próximos días)\n"
            "3. No urgente (puedo esperar)"
        )

    # 3. Esperando Urgencia (Paso Final)
    elif session["estado"] == "esperando_urgencia":
        urg_choice = message.strip()
        urgencia_map = {
            "1": "Urgente",
            "2": "Normal",
            "3": "No urgente"
        }
        
        # Mapear respuesta
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
        
        # Finalizar y analizar
        logger.info(f"Triaje completado para {phone_number}. Iniciando análisis...")
        datos_ia = analizar_solicitud_con_ia(session)
        
        # Notificar al profesional por Email
        email_enviado = enviar_email_profesional(session, datos_ia, session["foto_path"])
        
        # Notificar al profesional por WhatsApp (si está configurado)
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
            whatsapp_enviado = whatsapp.send_whatsapp_message(prof_phone, mensaje_prof)
            
        # Limpiar sesión y archivos temporales
        foto_path = session.get("foto_path")
        # Nota: no borramos la foto si queremos que permanezca registrada en storage, pero en este caso,
        # como la enviamos por email, podemos eliminarla del temporal si lo deseamos, o mantenerla.
        # Por ahora limpiamos la sesión de memoria.
        del _triaje_sesiones[phone_number]
        
        return "¡Perfecto! Tu solicitud ha sido registrada y enviada al profesional correspondiente. Se pondrán en contacto contigo lo antes posible. ¡Gracias! 👍"
