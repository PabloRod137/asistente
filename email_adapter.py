import os
import base64
import smtplib
import logging
import requests
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email.mime.image import MIMEImage
from email import encoders
import graph_auth

logger = logging.getLogger("asistente.email_adapter")

def enviar_email_smtp(destinatario: str, asunto: str, cuerpo_texto: str = None, cuerpo_html: str = None, adjuntos: list = None) -> bool:
    email_emisor = os.getenv("EMAIL_EMISOR")
    smtp_password = os.getenv("SMTP_PASSWORD")
    smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = os.getenv("SMTP_PORT", "587")
    
    if not email_emisor or not smtp_password:
        raise ValueError("Falta configurar EMAIL_EMISOR o SMTP_PASSWORD para SMTP.")
        
    msg = MIMEMultipart("mixed") if not cuerpo_html else MIMEMultipart("related")
    msg["From"] = email_emisor
    msg["To"] = destinatario
    msg["Subject"] = asunto
    
    if cuerpo_html:
        msg.attach(MIMEText(cuerpo_html, "html", "utf-8"))
    elif cuerpo_texto:
        msg.attach(MIMEText(cuerpo_texto, "plain", "utf-8"))
        
    if adjuntos:
        for adj in adjuntos:
            filepath = adj["filepath"]
            if not os.path.exists(filepath):
                logger.warning(f"Archivo adjunto no encontrado localmente para SMTP: {filepath}")
                continue
            is_inline = adj.get("is_inline", False)
            content_id = adj.get("content_id")
            filename = adj.get("filename") or os.path.basename(filepath)
            
            with open(filepath, "rb") as f:
                content_bytes = f.read()
                
            if is_inline and content_id:
                msg_image = MIMEImage(content_bytes)
                msg_image.add_header('Content-ID', f'<{content_id}>')
                msg_image.add_header('Content-Disposition', 'inline', filename=filename)
                msg.attach(msg_image)
            else:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(content_bytes)
                encoders.encode_base64(part)
                part.add_header(
                    "Content-Disposition",
                    f"attachment; filename={filename}",
                )
                msg.attach(part)
                
    server = smtplib.SMTP(smtp_server, int(smtp_port))
    server.starttls()
    server.login(email_emisor, smtp_password)
    server.sendmail(email_emisor, destinatario, msg.as_string())
    server.quit()
    logger.info(f"Email SMTP enviado con éxito a {destinatario}")
    return True

def enviar_email_graph(destinatario: str, asunto: str, cuerpo_texto: str = None, cuerpo_html: str = None, adjuntos: list = None) -> bool:
    email_emisor = os.getenv("EMAIL_EMISOR")
    if not email_emisor:
        raise ValueError("Falta configurar EMAIL_EMISOR para Graph Mail.")
        
    token = graph_auth.get_access_token()
    url = f"https://graph.microsoft.com/v1.0/users/{email_emisor}/sendMail"
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    body_content = cuerpo_html or cuerpo_texto or ""
    body_type = "HTML" if cuerpo_html else "Text"
    
    msg_attachments = []
    if adjuntos:
        for adj in adjuntos:
            filepath = adj["filepath"]
            if not os.path.exists(filepath):
                logger.warning(f"Archivo adjunto no encontrado localmente para Graph: {filepath}")
                continue
            filename = adj.get("filename") or os.path.basename(filepath)
            is_inline = adj.get("is_inline", False)
            content_id = adj.get("content_id")
            
            with open(filepath, "rb") as f:
                content_bytes = f.read()
            encoded_content = base64.b64encode(content_bytes).decode("utf-8")
            
            # Simple content type detection
            content_type = "application/octet-stream"
            if filename.lower().endswith(".pdf"):
                content_type = "application/pdf"
            elif filename.lower().endswith((".jpg", ".jpeg")):
                content_type = "image/jpeg"
            elif filename.lower().endswith(".png"):
                content_type = "image/png"
            
            attachment_dict = {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": filename,
                "contentType": content_type,
                "contentBytes": encoded_content
            }
            if is_inline:
                attachment_dict["isInline"] = True
                if content_id:
                    attachment_dict["contentId"] = content_id
            
            msg_attachments.append(attachment_dict)
            
    payload = {
        "message": {
            "subject": asunto,
            "body": {
                "contentType": body_type,
                "content": body_content
            },
            "toRecipients": [
                {
                    "emailAddress": {
                        "address": destinatario
                    }
                }
            ],
            "attachments": msg_attachments
        }
    }
    
    logger.info(f"Enviando correo vía Graph API desde {email_emisor} a {destinatario}...")
    res = requests.post(url, headers=headers, json=payload, timeout=30)
    res.raise_for_status()
    logger.info(f"Email Graph enviado con éxito a {destinatario}")
    return True

def enviar_email(destinatario: str, asunto: str, cuerpo_texto: str = None, cuerpo_html: str = None, adjuntos: list = None) -> bool:
    tipo = os.getenv("EMAIL_TIPO", "smtp").strip().lower()
    if tipo == "graph":
        try:
            return enviar_email_graph(destinatario, asunto, cuerpo_texto, cuerpo_html, adjuntos)
        except Exception as e:
            logger.warning(
                f"FALLBACK CORREO: Error enviando email a '{destinatario}' vía Graph: {e}. "
                f"Cayendo automáticamente a SMTP.", 
                exc_info=True
            )
    return enviar_email_smtp(destinatario, asunto, cuerpo_texto, cuerpo_html, adjuntos)
