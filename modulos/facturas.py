import os
import re
import json
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import requests
from fpdf import FPDF
from database import get_next_factura_numero, save_factura
import whatsapp

logger = logging.getLogger(__name__)

def generar_factura_pdf(num_factura: int, emisor: dict, receptor: dict, concepto: str, base: float, iva_pct: int, total: float, filepath: str):
    """
    Genera un PDF formal para la factura utilizando fpdf2.
    """
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    
    # Título y número de factura
    pdf.set_font("Helvetica", style="B", size=16)
    pdf.cell(200, 10, txt=f"FACTURA Nº {num_factura:05d}", ln=True, align="R")
    pdf.ln(10)
    
    # Datos Emisor
    pdf.set_font("Helvetica", style="B", size=12)
    pdf.cell(100, 7, txt="EMISOR", ln=True)
    pdf.set_font("Helvetica", size=10)
    pdf.cell(100, 5, txt=f"Nombre: {emisor.get('nombre', '')}", ln=True)
    pdf.cell(100, 5, txt=f"CIF: {emisor.get('cif', '')}", ln=True)
    pdf.cell(100, 5, txt=f"Dirección: {emisor.get('direccion', '')}", ln=True)
    if emisor.get("iban"):
        pdf.cell(100, 5, txt=f"IBAN: {emisor.get('iban', '')}", ln=True)
    pdf.ln(10)
    
    # Datos Receptor
    pdf.set_font("Helvetica", style="B", size=12)
    pdf.cell(100, 7, txt="RECEPTOR", ln=True)
    pdf.set_font("Helvetica", size=10)
    pdf.cell(100, 5, txt=f"Nombre/Razón Social: {receptor.get('nombre', '')}", ln=True)
    pdf.cell(100, 5, txt=f"CIF/NIF: {receptor.get('cif', '')}", ln=True)
    if receptor.get("email"):
        pdf.cell(100, 5, txt=f"Email: {receptor.get('email', '')}", ln=True)
    pdf.ln(15)
    
    # Línea de Concepto y Precios (Tabla simple)
    pdf.set_font("Helvetica", style="B", size=10)
    pdf.cell(100, 8, txt="Concepto", border=1)
    pdf.cell(30, 8, txt="Base Imponible", border=1, align="R")
    pdf.cell(20, 8, txt="IVA", border=1, align="C")
    pdf.cell(40, 8, txt="Total", border=1, align="R")
    pdf.ln(8)
    
    pdf.set_font("Helvetica", size=10)
    pdf.cell(100, 8, txt=concepto, border=1)
    pdf.cell(30, 8, txt=f"{base:.2f} €", border=1, align="R")
    pdf.cell(20, 8, txt=f"{iva_pct}%", border=1, align="C")
    pdf.cell(40, 8, txt=f"{total:.2f} €", border=1, align="R")
    pdf.ln(15)
    
    # Resumen totalizadores
    pdf.set_font("Helvetica", style="B", size=10)
    pdf.cell(130, 8, txt="")
    pdf.cell(30, 8, txt="Total Base:", align="R")
    pdf.cell(30, 8, txt=f"{base:.2f} €", align="R")
    pdf.ln(6)
    
    iva_cuota = total - base
    pdf.cell(130, 8, txt="")
    pdf.cell(30, 8, txt=f"IVA ({iva_pct}%):", align="R")
    pdf.cell(30, 8, txt=f"{iva_cuota:.2f} €", align="R")
    pdf.ln(6)
    
    pdf.set_font("Helvetica", style="B", size=12)
    pdf.cell(130, 8, txt="")
    pdf.cell(30, 8, txt="TOTAL:", align="R")
    pdf.cell(30, 8, txt=f"{total:.2f} €", align="R")
    
    # Guardar PDF
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    pdf.output(filepath)
    logger.info(f"PDF de factura generado correctamente en: {filepath}")

def enviar_factura_email(email_destino: str, filepath: str, num_factura: int) -> bool:
    email_emisor = os.getenv("EMAIL_EMISOR")
    smtp_password = os.getenv("SMTP_PASSWORD")
    smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = os.getenv("SMTP_PORT", "587")
    
    if not email_emisor or not smtp_password:
        logger.warning("Falta configurar EMAIL_EMISOR o SMTP_PASSWORD. No se puede enviar email.")
        return False
        
    try:
        msg = MIMEMultipart()
        msg["From"] = email_emisor
        msg["To"] = email_destino
        msg["Subject"] = f"Factura Nº {num_factura:05d}"
        
        cuerpo = f"Hola,\n\nTe adjuntamos la factura correspondiente Nº {num_factura:05d}.\n\nSaludos."
        msg.attach(MIMEText(cuerpo, "plain"))
        
        # Adjuntar PDF
        with open(filepath, "rb") as attachment:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(attachment.read())
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition",
                f"attachment; filename=Factura_{num_factura:05d}.pdf",
            )
            msg.attach(part)
            
        server = smtplib.SMTP(smtp_server, int(smtp_port))
        server.starttls()
        server.login(email_emisor, smtp_password)
        server.sendmail(email_emisor, email_destino, msg.as_string())
        server.quit()
        logger.info(f"Email con factura enviado con éxito a {email_destino}")
        return True
    except Exception as e:
        logger.error(f"Error enviando factura por email: {e}")
        return False

def procesar_solicitud_factura(phone_number: str, message: str) -> str:
    """
    Parsea la petición del usuario, genera la factura y la envía.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return "Servicio de facturación no disponible temporalmente (Falta API Key)."
        
    # Usar Gemini para extraer los datos de la factura del texto libre
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    
    prompt = f"""
    Analiza la siguiente petición para generar una factura y extrae los datos fiscales:
    Petición: "{message}"

    Debes extraer:
    1. destinatario: Nombre o razón social del cliente receptor (string).
    2. cif: CIF o NIF del receptor (string).
    3. concepto: El trabajo o servicio prestado (string).
    4. base_imponible: Importe base en euros. Si no se especifica explícitamente y solo hay un total, calcula la base sabiendo que el IVA por defecto es 21%. (float).
    5. porcentaje_iva: Porcentaje de IVA a aplicar. Por defecto 21 si no se menciona otro (integer).
    6. email: Dirección de correo electrónico del destinatario si se menciona en el mensaje, o null.

    Devuelve ÚNICAMENTE un JSON válido con esta estructura:
    {{
        "destinatario": "string",
        "cif": "string",
        "concepto": "string",
        "base_imponible": float,
        "porcentaje_iva": int,
        "email": "string o null"
    }}
    """
    
    try:
        response = requests.post(url, json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.0}
        }, headers={'Content-Type': 'application/json'}, timeout=10)
        response.raise_for_status()
        
        datos = json.loads(response.json()["candidates"][0]["content"]["parts"][0]["text"].strip())
    except Exception as e:
        logger.error(f"Error parseando datos de factura con Gemini: {e}")
        return "No he podido interpretar correctamente los datos para la factura. Por favor, asegúrate de indicar el destinatario, CIF, concepto e importe."

    destinatario = datos.get("destinatario")
    cif = datos.get("cif")
    concepto = datos.get("concepto")
    base = datos.get("base_imponible", 0.0)
    iva_pct = datos.get("porcentaje_iva", 21)
    email_dest = datos.get("email")

    if not destinatario or not cif or not concepto or base <= 0:
        return "Por favor, especifica claramente: destinatario, CIF/NIF, concepto e importe para generar la factura."

    # Datos Emisor desde .env
    emisor = {
        "nombre": os.getenv("FACTURA_EMISOR_NOMBRE", "Mi Empresa S.L."),
        "cif": os.getenv("FACTURA_EMISOR_CIF", "B12345678"),
        "direccion": os.getenv("FACTURA_EMISOR_DIRECCION", "Calle Gran Via 1, Madrid"),
        "iban": os.getenv("FACTURA_EMISOR_IBAN", "")
    }

    # Calcular total e IVA
    total = base * (1 + (iva_pct / 100))

    # Obtener número de factura correlativo y guardar en SQLite
    num_factura = get_next_factura_numero()
    save_factura(destinatario, cif, concepto, total)

    # Ruta temporal para guardar PDF
    storage_ruta = os.getenv("STORAGE_RUTA", "./storage")
    pdf_filename = f"Factura_{num_factura:05d}.pdf"
    pdf_path = os.path.join(storage_ruta, "facturas_emitidas", pdf_filename)
    
    try:
        # Generar PDF
        generar_factura_pdf(num_factura, emisor, {
            "nombre": destinatario,
            "cif": cif,
            "email": email_dest
        }, concepto, base, iva_pct, total, pdf_path)
        
        # Subir media a WhatsApp
        media_id = whatsapp.upload_whatsapp_media(pdf_path, "application/pdf")
        
        if media_id:
            # Enviar por WhatsApp
            whatsapp.send_whatsapp_document(phone_number, media_id, pdf_filename)
            respuesta = f"¡Factura Nº {num_factura:05d} generada correctamente y enviada! 📄"
        else:
            respuesta = f"Se ha generado la factura física en el servidor, pero no se ha podido subir a WhatsApp. (Ruta: {pdf_path})"
            
        # Enviar copia por email opcional
        if email_dest:
            enviar_factura_email(email_dest, pdf_path, num_factura)
            respuesta += f" Además se ha enviado una copia por correo a {email_dest}."
            
        return respuesta
        
    except Exception as e:
        logger.error(f"Error durante el proceso de facturación: {e}")
        return "Ha ocurrido un error al generar la factura. Revisa los logs para más detalles."
