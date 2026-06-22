import logging
import whatsapp

logger = logging.getLogger(__name__)

def lanzar_aviso_whatsapp(phone: str, mensaje: str) -> bool:
    """
    Envía un recordatorio de pago a un cliente a través de WhatsApp.
    Esta función es invocada por el orquestador externo o scripts programados.
    """
    logger.info(f"Enviando aviso de cobro a {phone}")
    if not phone or not mensaje:
        logger.error("Teléfono o mensaje inválido para lanzar_aviso_whatsapp")
        return False
        
    # Enviar mensaje por whatsapp
    ret = whatsapp.send_whatsapp_message(phone, mensaje)
    if ret:
        logger.info(f"Aviso de cobro enviado con éxito a {phone}")
    else:
        logger.error(f"Fallo al enviar aviso de cobro a {phone}")
    return ret
