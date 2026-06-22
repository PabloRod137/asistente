import os
import re
import json
import shutil
import logging
from datetime import datetime
import openpyxl
from openpyxl import Workbook
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

# Memoria temporal en sesión para tickets pendientes de confirmación
# { "phone_number": { "temp_path": "...", "datos": {...} } }
_tickets_pendientes = {}

def sanitizar_nombre_archivo(texto):
    if not texto:
        return "desconocido"
    s = str(texto).strip().replace(" ", "_")
    s = re.sub(r'[^a-zA-Z0-9_\-]', '', s)
    return s if s else "desconocido"

def guardar_registro_excel(temp_image_path: str, datos: dict) -> tuple[str, str]:
    """
    Guarda la imagen de ticket y registra los datos en el excel correspondiente del cliente.
    """
    storage_ruta = os.getenv("STORAGE_RUTA", "./storage")
    cif_cliente = os.getenv("FACTURA_EMISOR_CIF", "general").strip().upper()
    cif_sanitizado = sanitizar_nombre_archivo(cif_cliente)
    
    # 1. Determinar subcarpeta YYYY-MM
    fecha_str = datos.get("fecha")
    if fecha_str and re.match(r'^\d{4}-\d{2}-\d{2}$', fecha_str):
        yyyy_mm = fecha_str[:7]
        fecha_archivo = fecha_str
    else:
        ahora = datetime.now()
        yyyy_mm = ahora.strftime("%Y-%m")
        fecha_archivo = ahora.strftime("%Y-%m-%d")
        
    dest_dir = os.path.join(storage_ruta, cif_sanitizado, yyyy_mm)
    os.makedirs(dest_dir, exist_ok=True)
    
    emisor_san = sanitizar_nombre_archivo(datos.get("emisor", "desconocido"))
    total = datos.get("total", 0.0)
    total_str = f"{total:.2f}".replace(".", "-")
    nombre_imagen = f"{fecha_archivo}_{emisor_san}_{total_str}.jpg"
    
    dest_image_path = os.path.join(dest_dir, nombre_imagen)
    shutil.copy2(temp_image_path, dest_image_path)
    logger.info(f"Imagen del ticket copiada a: {dest_image_path}")
    
    # 2. Registrar en Excel
    excel_dir = os.path.join(storage_ruta, cif_sanitizado)
    os.makedirs(excel_dir, exist_ok=True)
    excel_path = os.path.join(excel_dir, f"gastos_{cif_sanitizado}.xlsx")
    
    headers = [
        "Fecha", "Emisor", "CIF Emisor", "Base Imponible", 
        "% IVA", "Cuota IVA", "Total", "Ruta Archivo", "Fecha Registro"
    ]
    
    if os.path.exists(excel_path):
        try:
            wb = openpyxl.load_workbook(excel_path)
            ws = wb.active
        except Exception as e:
            logger.error(f"Error cargando Excel {excel_path}: {e}. Creando nuevo.")
            wb = Workbook()
            ws = wb.active
            ws.append(headers)
    else:
        wb = Workbook()
        ws = wb.active
        ws.append(headers)
        
    fecha = datos.get("fecha") or ""
    emisor = datos.get("emisor") or ""
    cif_emisor = datos.get("cif_emisor") or ""
    base = datos.get("base_imponible", 0.0)
    porcentaje_iva = datos.get("porcentaje_iva", 0)
    cuota = datos.get("cuota_iva", 0.0)
    total = datos.get("total", 0.0)
    fecha_registro = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    row_data = [
        fecha, emisor, cif_emisor, base, 
        porcentaje_iva, cuota, total, dest_image_path, fecha_registro
    ]
    
    ws.append(row_data)
    wb.save(excel_path)
    logger.info(f"Registro añadido correctamente en Excel: {excel_path}")
    
    return dest_image_path, excel_path

def procesar_mensaje_imagen(phone_number: str, temp_image_path: str) -> str:
    """
    Cuando se recibe una imagen por WhatsApp, se procesa con Gemini Vision para OCR,
    y se le pide confirmación al usuario de los datos fiscales extraídos.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return "No se ha podido procesar la imagen porque falta GEMINI_API_KEY en el .env."
        
    if not os.path.exists(temp_image_path):
        return "Error interno: El archivo de imagen temporal no se ha encontrado."
        
    logger.info(f"Procesando ticket en {temp_image_path} para {phone_number}")
    
    try:
        # Usar SDK google-genai para procesar con Gemini Vision
        client = genai.Client(api_key=api_key)
        
        with open(temp_image_path, 'rb') as f:
            file_bytes = f.read()
            
        part = types.Part.from_bytes(data=file_bytes, mime_type='image/jpeg')
        
        prompt = """
        Analiza esta imagen de ticket de gasto o factura simplificada y extrae la información fiscal de forma precisa.
        Debes extraer los siguientes campos obligatoriamente:
        1. emisor: Nombre del establecimiento o empresa emisora (string).
        2. cif_emisor: CIF o NIF del emisor si aparece, o null (string).
        3. fecha: Fecha del ticket en formato YYYY-MM-DD, o null (string).
        4. base_imponible: Importe base sin IVA (float).
        5. porcentaje_iva: Porcentaje de IVA aplicado, por ejemplo 4, 10 o 21 (integer).
        6. cuota_iva: Importe del IVA (float).
        7. total: Importe total del ticket (float).

        Reglas críticas:
        - Devuelve ÚNICAMENTE un JSON válido con las claves mencionadas.
        - No inventes ningún valor. Si no aparece o no estás seguro, asigna null.
        - Asegúrate de que los importes sean numéricos.
        """
        
        respuesta = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[part, prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json"
            )
        )
        
        datos = json.loads(respuesta.text.strip())
        
        # Formatear e interpretar tipos
        emisor = str(datos.get("emisor", "Desconocido")).strip()
        cif_emisor = str(datos.get("cif_emisor", "")).strip().upper() if datos.get("cif_emisor") else None
        fecha = str(datos.get("fecha", "")).strip() if datos.get("fecha") else None
        
        def safe_float(val):
            try: return float(val) if val is not None else 0.0
            except: return 0.0
            
        def safe_int(val):
            try: return int(val) if val is not None else 0
            except: return 0
            
        base = safe_float(datos.get("base_imponible"))
        porcentaje_iva = safe_int(datos.get("porcentaje_iva"))
        cuota = safe_float(datos.get("cuota_iva"))
        total = safe_float(datos.get("total"))
        
        # Validar cuadre (tolerancia 0.02€)
        advertencia = None
        if abs(total - (base + cuota)) > 0.02:
            advertencia = "Total no cuadra (Base + Cuota IVA != Total), revisar manualmente"
            
        datos_procesados = {
            "emisor": emisor,
            "cif_emisor": cif_emisor,
            "fecha": fecha,
            "base_imponible": base,
            "porcentaje_iva": porcentaje_iva,
            "cuota_iva": cuota,
            "total": total
        }
        
        if advertencia:
            datos_procesados["advertencia"] = advertencia

        # Guardar en sesión
        _tickets_pendientes[phone_number] = {
            "temp_path": temp_image_path,
            "datos": datos_procesados
        }
        
        # Devolver mensaje interactivo numerado en texto plano
        msg = (
            "🔍 *Datos extraídos de tu ticket:*\n\n"
            f"🏢 *Emisor:* {emisor}\n"
            f"🆔 *CIF Emisor:* {cif_emisor or 'No indicado'}\n"
            f"📅 *Fecha:* {fecha or 'No indicada'}\n"
            f"💵 *Base Imponible:* {base:.2f}€\n"
            f"📊 *IVA:* {porcentaje_iva}%\n"
            f"💸 *Cuota IVA:* {cuota:.2f}€\n"
            f"💰 *Total:* {total:.2f}€\n"
        )
        if advertencia:
            msg += f"\n⚠️ *Advertencia:* {advertencia}\n"
            
        msg += (
            "\n¿Confirmas que estos datos son correctos?\n"
            "1. Sí, confirmar y guardar en el Excel\n"
            "2. No, descartar"
        )
        return msg
        
    except Exception as e:
        logger.error(f"Error procesando ticket: {e}")
        # Limpiar
        if os.path.exists(temp_image_path):
            os.remove(temp_image_path)
        return "Lo siento, ha ocurrido un error al analizar la imagen del ticket con la IA. Por favor, vuelve a enviarla."

def gestionar_confirmacion_ticket(phone_number: str, message: str) -> str:
    """
    Comprueba si el usuario tiene un ticket pendiente y responde a las opciones.
    """
    ticket_session = _tickets_pendientes.get(phone_number)
    if not ticket_session:
        return None
        
    msg_clean = message.strip()
    
    if msg_clean == "1" or "si" in msg_clean.lower() or "sí" in msg_clean.lower() or "correcto" in msg_clean.lower():
        # Confirmar y guardar
        temp_path = ticket_session["temp_path"]
        datos = ticket_session["datos"]
        
        try:
            guardar_registro_excel(temp_path, datos)
            respuesta = "¡Ticket guardado y registrado con éxito en tu Excel de gastos! ✅"
        except Exception as e:
            logger.error(f"Error guardando ticket en Excel: {e}")
            respuesta = f"Ha ocurrido un error al guardar el registro en Excel: {e}"
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            del _tickets_pendientes[phone_number]
            
        return respuesta
        
    elif msg_clean == "2" or "no" in msg_clean.lower() or "descartar" in msg_clean.lower():
        # Descartar
        temp_path = ticket_session["temp_path"]
        if os.path.exists(temp_path):
            os.remove(temp_path)
        del _tickets_pendientes[phone_number]
        return "Ticket descartado. ❌ Si quieres puedes enviarme otra foto."
        
    # Si no es ninguna opción, recordar qué hacer
    return "Tengo un ticket pendiente de confirmación. Por favor responde:\n1. Si es correcto\n2. Si deseas descartarlo"
