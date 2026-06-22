import os
import requests
import logging

logger = logging.getLogger(__name__)

API_VERSION = "v18.0"

def send_whatsapp_message(to_phone: str, message: str) -> bool:
    WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
    WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID")

    if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_ID:
        logger.error("Faltan las credenciales de WhatsApp en el .env")
        return False
        
    url = f"https://graph.facebook.com/{API_VERSION}/{WHATSAPP_PHONE_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "messaging_product": "whatsapp",
        "to": to_phone,
        "type": "text",
        "text": {
            "body": message
        }
    }
    
    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        logger.info(f"Mensaje enviado con éxito a {to_phone}")
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Error enviando mensaje a WhatsApp: {e}")
        if e.response is not None:
            logger.error(f"Detalles: {e.response.text}")
        return False

def download_whatsapp_media(media_id: str, dest_path: str) -> bool:
    WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
    if not WHATSAPP_TOKEN:
        logger.error("Falta WHATSAPP_TOKEN en el .env")
        return False
        
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}"
    }
    
    try:
        # 1. Obtener URL de descarga del media
        url = f"https://graph.facebook.com/{API_VERSION}/{media_id}"
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        media_data = response.json()
        download_url = media_data.get("url")
        
        if not download_url:
            logger.error("No se pudo obtener la URL de descarga del media")
            return False
            
        # 2. Descargar el archivo binario
        media_response = requests.get(download_url, headers=headers)
        media_response.raise_for_status()
        
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        with open(dest_path, "wb") as f:
            f.write(media_response.content)
            
        logger.info(f"Media {media_id} descargado correctamente en {dest_path}")
        return True
    except Exception as e:
        logger.error(f"Error descargando media {media_id}: {e}")
        return False

def upload_whatsapp_media(filepath: str, mime_type: str) -> str:
    """
    Sube un archivo local a WhatsApp y retorna su media_id.
    """
    WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
    WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID")

    if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_ID:
        logger.error("Faltan las credenciales de WhatsApp para subir archivos")
        return None
        
    url = f"https://graph.facebook.com/{API_VERSION}/{WHATSAPP_PHONE_ID}/media"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}"
    }
    
    if not os.path.exists(filepath):
        logger.error(f"Archivo a subir no existe: {filepath}")
        return None
        
    try:
        with open(filepath, "rb") as f:
            files = {
                "file": (os.path.basename(filepath), f, mime_type)
            }
            data = {
                "messaging_product": "whatsapp",
                "type": mime_type
            }
            response = requests.post(url, headers=headers, data=data, files=files)
            response.raise_for_status()
            res_data = response.json()
            media_id = res_data.get("id")
            logger.info(f"Archivo subido con éxito a WhatsApp. Media ID: {media_id}")
            return media_id
    except Exception as e:
        logger.error(f"Error subiendo archivo a WhatsApp: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"Detalles: {e.response.text}")
        return None

def send_whatsapp_document(to_phone: str, media_id: str, filename: str) -> bool:
    WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
    WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID")

    if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_ID:
        logger.error("Faltan las credenciales de WhatsApp en el .env")
        return False
        
    url = f"https://graph.facebook.com/{API_VERSION}/{WHATSAPP_PHONE_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "messaging_product": "whatsapp",
        "to": to_phone,
        "type": "document",
        "document": {
            "id": media_id,
            "filename": filename
        }
    }
    
    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        logger.info(f"Documento {filename} enviado con éxito a {to_phone}")
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Error enviando documento a WhatsApp: {e}")
        return False
