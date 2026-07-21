import os
import logging
from datetime import datetime
import database
import client_memory
import whatsapp

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("modulos.recordatorios")

async def procesar_recordatorios_documentos() -> int:
    """
    Consulta los documentos pendientes con fecha límite cercana (días configurables)
    y envía un WhatsApp directo al cliente recordando su entrega de forma asíncrona.
    Si la fecha límite ya pasó, cancela el envío automático.
    Incrementa 'veces_recordado' y actualiza 'ultimo_recordatorio_fecha'.
    """
    try:
        dias_antes_str = os.getenv("RECORDATORIO_DOCUMENTOS_DIAS_ANTES", "3").strip()
        dias_antes = int(dias_antes_str)
    except ValueError:
        dias_antes = 3

    docs = database.get_documentos_pendientes_a_recordar(dias_antes)
    logger.info(f"Encontrados {len(docs)} documentos pendientes para recordar (margen {dias_antes} días).")
    
    enviados = 0
    for doc in docs:
        phone = doc["phone_number"]
        cliente = client_memory.get_cliente(phone)
        nombre = (cliente.get("nombre") if cliente else None) or "cliente"
        descripcion = doc["descripcion"]
        fecha_limite = doc["fecha_limite"]
        
        mensaje = (
            f"👋 Hola *{nombre}*, te recordamos que tenemos pendiente de recibir el siguiente documento:\n\n"
            f"📄 *{descripcion}*\n"
            f"📅 *Fecha límite:* {fecha_limite}\n\n"
            f"Por favor, envíanoslo por este mismo chat en cuanto te sea posible. ¡Muchas gracias!"
        )
        
        try:
            await whatsapp.send_whatsapp_message(phone, mensaje)
            database.incrementar_recordatorio_documento(doc["id"])
            enviados += 1
            logger.info(f"Enviado recordatorio de documento #{doc['id']} a {phone} ({nombre}).")
        except Exception as e:
            logger.error(f"Error enviando recordatorio de documento #{doc['id']} a {phone}: {e}")
            
    return enviados

async def procesar_recordatorios_plazos_fiscales() -> int:
    """
    Consulta los plazos fiscales con teléfono de cliente asignado y fecha límite cercana de forma asíncrona.
    Envía un WhatsApp directo notificando la fecha límite.
    Marca 'recordatorio_enviado = 1' para no repetir.
    """
    try:
        dias_antes_str = os.getenv("RECORDATORIO_FISCAL_DIAS_ANTES", "7").strip()
        dias_antes = int(dias_antes_str)
    except ValueError:
        dias_antes = 7

    plazos = database.get_plazos_fiscales_a_recordar_cliente(dias_antes)
    logger.info(f"Encontrados {len(plazos)} plazos fiscales para recordar directamente al cliente (margen {dias_antes} días).")
    
    enviados = 0
    for plazo in plazos:
        phone = plazo["phone_number"]
        cliente = client_memory.get_cliente(phone)
        nombre = (cliente.get("nombre") if cliente else None) or plazo.get("cliente") or "cliente"
        modelo = plazo["modelo"]
        desc = plazo["descripcion"]
        fecha_limite = plazo["fecha_limite"]
        
        mensaje = (
            f"👋 Hola *{nombre}*, te recordamos un próximo plazo fiscal relevante para tus gestiones:\n\n"
            f"📌 *Modelo/Gestión:* {modelo}\n"
            f"📝 *Detalles:* {desc}\n"
            f"📅 *Fecha límite de presentación:* {fecha_limite}\n\n"
            f"Si necesitas que revisemos algo antes del cierre, escríbenos por aquí. ¡Un saludo!"
        )
        
        try:
            await whatsapp.send_whatsapp_message(phone, mensaje)
            database.marcar_plazo_fiscal_recordado(plazo["id"])
            enviados += 1
            logger.info(f"Enviado recordatorio de plazo fiscal #{plazo['id']} a {phone} ({nombre}).")
        except Exception as e:
            logger.error(f"Error enviando recordatorio de plazo fiscal #{plazo['id']} a {phone}: {e}")
            
    return enviados

async def procesar_todos_los_recordatorios() -> dict:
    """
    Ejecuta el ciclo completo de recordatorios automáticos (documentos y plazos fiscales) de forma asíncrona.
    """
    logger.info("--- Iniciando ciclo de recordatorios automáticos ---")
    docs_count = await procesar_recordatorios_documentos()
    plazos_count = await procesar_recordatorios_plazos_fiscales()
    summary = {
        "recordatorios_documentos_enviados": docs_count,
        "recordatorios_fiscales_enviados": plazos_count
    }
    logger.info(f"--- Ciclo de recordatorios finalizado: {summary} ---")
    return summary
