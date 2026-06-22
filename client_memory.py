import os
import sqlite3
import logging
import requests
import json
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

def get_cliente(phone_number: str) -> dict | None:
    """
    Busca el cliente en SQLite y devuelve un diccionario con sus datos o None si no existe.
    """
    if os.getenv("MODULO_MEMORIA", "true").strip().lower() == "false":
        return None

    db_path = os.getenv("DB_PATH", "chatbot.db")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT phone_number, nombre, empresa, email, notas, primera_visita, ultima_visita, total_conversaciones
        FROM clientes WHERE phone_number = ?
    """, (phone_number,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return {
            "phone_number": row[0],
            "nombre": row[1],
            "empresa": row[2],
            "email": row[3],
            "notas": row[4],
            "primera_visita": row[5],
            "ultima_visita": row[6],
            "total_conversaciones": row[7]
        }
    return None

def registrar_visita(phone_number: str):
    """
    Registra la visita del cliente en base de datos.
    Si es nuevo lo crea, si ya existe actualiza su última visita e incrementa 
    el número total de conversaciones si ha pasado el tiempo límite de inactividad.
    """
    if os.getenv("MODULO_MEMORIA", "true").strip().lower() == "false":
        return

    db_path = os.getenv("DB_PATH", "chatbot.db")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute("SELECT ultima_visita, total_conversaciones FROM clientes WHERE phone_number = ?", (phone_number,))
    row = cursor.fetchone()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    if row is None:
        cursor.execute("""
            INSERT INTO clientes (phone_number, primera_visita, ultima_visita, total_conversaciones)
            VALUES (?, ?, ?, 1)
        """, (phone_number, now_str, now_str))
        logger.info(f"Creado nuevo registro de cliente en memoria para {phone_number}")
    else:
        ultima_visita_str = row[0]
        total_conv = row[1]
        
        timeout_mins = int(os.getenv("CONVERSACION_TIMEOUT_MINUTOS", "30"))
        nueva_visita = True
        if ultima_visita_str:
            try:
                uv_dt = datetime.strptime(ultima_visita_str, "%Y-%m-%d %H:%M:%S")
                if datetime.now() - uv_dt < timedelta(minutes=timeout_mins):
                    nueva_visita = False
            except Exception:
                pass
                
        nuevo_total = total_conv + 1 if nueva_visita else total_conv
        
        cursor.execute("""
            UPDATE clientes
            SET ultima_visita = ?, total_conversaciones = ?
            WHERE phone_number = ?
        """, (now_str, nuevo_total, phone_number))
        
    conn.commit()
    conn.close()

def upsert_cliente(phone_number: str, datos: dict):
    """
    Inserta o actualiza el cliente. Combina los datos de nombre, empresa y email
    sin sobreescribir con None si ya existían anteriormente.
    """
    if os.getenv("MODULO_MEMORIA", "true").strip().lower() == "false":
        return

    db_path = os.getenv("DB_PATH", "chatbot.db")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute("SELECT nombre, empresa, email, total_conversaciones FROM clientes WHERE phone_number = ?", (phone_number,))
    row = cursor.fetchone()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    if row is None:
        cursor.execute("""
            INSERT INTO clientes (phone_number, nombre, empresa, email, primera_visita, ultima_visita, total_conversaciones)
            VALUES (?, ?, ?, ?, ?, ?, 1)
        """, (phone_number, datos.get("nombre"), datos.get("empresa"), datos.get("email"), now_str, now_str))
    else:
        current_nombre, current_empresa, current_email, total_conv = row
        
        nuevo_nombre = datos.get("nombre") if datos.get("nombre") is not None else current_nombre
        nuevo_empresa = datos.get("empresa") if datos.get("empresa") is not None else current_empresa
        nuevo_email = datos.get("email") if datos.get("email") is not None else current_email
        
        cursor.execute("""
            UPDATE clientes
            SET nombre = ?, empresa = ?, email = ?, ultima_visita = ?
            WHERE phone_number = ?
        """, (nuevo_nombre, nuevo_empresa, nuevo_email, now_str, phone_number))
        
    conn.commit()
    conn.close()

def extraer_datos_cliente(phone_number: str, history: list) -> dict:
    """
    Llama a Gemini analizando el historial completo de la conversación para
    extraer nombre, empresa y correo del cliente. Retorna None en las claves no detectadas.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return {"nombre": None, "empresa": None, "email": None}
        
    historial_str = ""
    for msg in history:
        sender = "Maira" if msg["role"] == "assistant" else "Cliente"
        historial_str += f"{sender}: {msg['content']}\n"
        
    prompt = f"""Analiza la siguiente conversación de WhatsApp y extrae los datos de perfil del Cliente si han sido explícitamente mencionados.
Si no se menciona alguno de ellos, devuelve null para ese campo. No inventes ningún dato.

Datos a extraer:
- nombre (nombre personal del cliente)
- empresa (nombre de su empresa, negocio o SL)
- email (dirección de correo electrónico)

Devuelve ÚNICAMENTE un objeto JSON con las claves: "nombre", "empresa", "email".

CONVERSACIÓN:
{historial_str}"""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    payload = {
        "contents": [{
            "parts": [{"text": prompt}]
        }],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.0
        }
    }
    
    try:
        response = requests.post(url, json=payload, headers={'Content-Type': 'application/json'}, timeout=15)
        response.raise_for_status()
        data = response.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        extracted = json.loads(text)
        return {
            "nombre": extracted.get("nombre"),
            "empresa": extracted.get("empresa"),
            "email": extracted.get("email")
        }
    except Exception as e:
        logger.error(f"Error al extraer datos del cliente con Gemini: {e}")
        return {"nombre": None, "empresa": None, "email": None}
