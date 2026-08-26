import os
import re
import logging
import unicodedata
from datetime import datetime

import storage_adapter
import database
import whatsapp

logger = logging.getLogger("asistente.puente_claudia")

_MIME_POR_EXTENSION = {
    "pdf": "application/pdf",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "ppt": "application/vnd.ms-powerpoint",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
}


def _carpeta_raiz() -> str:
    return os.getenv("SHAREPOINT_CARPETA_PUENTE", "puente_claudia").strip().strip("/")


def _slug(texto: str) -> str:
    """Normaliza un nombre de archivo/carpeta: sin acentos ni caracteres que puedan romper una ruta."""
    if not texto:
        return ""
    nfkd = unicodedata.normalize("NFD", texto)
    sin_acentos = "".join(c for c in nfkd if unicodedata.category(c) != "Mn")
    limpio = re.sub(r"[^a-zA-Z0-9._-]+", "_", sin_acentos).strip("_")
    return limpio[:100]


def _detectar_mime(nombre_archivo: str) -> str:
    ext = nombre_archivo.lower().rsplit(".", 1)[-1] if "." in nombre_archivo else ""
    return _MIME_POR_EXTENSION.get(ext, "application/octet-stream")


def _verificar_modo_seguro():
    """
    Salvaguarda: este módulo implementa el diseño previo a la negociación de contrato con
    Claudia (teléfono como clave, sin manifiesto/hash/inmutabilidad). No coincide con
    docs/CONTRATO_MAIRA_CLAUDIA_V4_APROBADO.md, cuyo estado explícito es "IMPLEMENTACIÓN NO
    AUTORIZADA / DATOS REALES NO AUTORIZADOS". Si alguien activa STORAGE_TIPO=sharepoint sin
    haber migrado este módulo al formato del contrato V4, esto lo bloquea en vez de dejar que
    Maira escriba en SharePoint real con un formato no aprobado.
    """
    if os.getenv("STORAGE_TIPO", "local").strip().lower() == "sharepoint":
        raise RuntimeError(
            "puente_claudia.py usa el diseño anterior al contrato aprobado con Claudia (ver "
            "docs/CONTRATO_MAIRA_CLAUDIA_V4_APROBADO.md) y no está autorizado a escribir en "
            "SharePoint real. Hay que migrar este módulo al contrato V4 antes de activar "
            "STORAGE_TIPO=sharepoint."
        )


async def enviar_a_carpeta_puente(phone_number: str, contenido_bytes: bytes, nombre_archivo: str, mime_type: str = None) -> str:
    """
    Sube un documento recibido de un cliente a la carpeta puente local de pruebas. NO es el
    contrato aprobado con Claudia (ver _verificar_modo_seguro) -- mientras STORAGE_TIPO=local
    esto es solo un mecanismo de pruebas internas, sin relación con la carpeta puente real.
    Ruta resultante: {carpeta_puente}/{telefono}/entrada/{timestamp}_{nombre_archivo}
    """
    _verificar_modo_seguro()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    nombre_seguro = _slug(nombre_archivo) or "documento"
    ruta_logica = f"{_carpeta_raiz()}/{phone_number}/entrada/{timestamp}_{nombre_seguro}"

    await storage_adapter.guardar_archivo(ruta_logica, contenido_bytes)
    database.registrar_documento_puente(phone_number, "entrada", ruta_logica, nombre_archivo, mime_type)
    logger.info(f"Documento de {phone_number} subido a la carpeta puente: {ruta_logica}")
    return ruta_logica


async def _enviar_documento_a_cliente(phone_number: str, ruta_logica: str, nombre_archivo: str) -> bool:
    storage_ruta = os.getenv("STORAGE_RUTA", "./storage")
    temp_filepath = os.path.join(
        storage_ruta, "temp",
        f"puente_salida_{phone_number}_{int(datetime.now().timestamp())}_{_slug(nombre_archivo)}"
    )

    try:
        contenido = await storage_adapter.leer_archivo(ruta_logica)
        os.makedirs(os.path.dirname(temp_filepath), exist_ok=True)
        with open(temp_filepath, "wb") as f:
            f.write(contenido)

        media_id = await whatsapp.upload_whatsapp_media(temp_filepath, _detectar_mime(nombre_archivo))
        if not media_id:
            return False

        await whatsapp.send_whatsapp_message(
            phone_number,
            "Ya tenemos preparado un documento para ti, te lo enviamos a continuación:"
        )
        enviado = await whatsapp.send_whatsapp_document(phone_number, media_id, nombre_archivo)
        if enviado:
            database.save_message(phone_number, "assistant", f"[Documento enviado: {nombre_archivo}]")
        return enviado
    finally:
        try:
            if os.path.exists(temp_filepath):
                os.remove(temp_filepath)
        except Exception as e:
            logger.error(f"Error eliminando temporal de carpeta puente {temp_filepath}: {e}")


async def revisar_carpeta_salida() -> int:
    """
    Job periódico: recorre las subcarpetas de clientes de la carpeta puente buscando archivos
    nuevos en su 'salida' (lo que Claudia ha dejado listo), y los envía por WhatsApp. Idempotente:
    cada archivo se registra en documentos_puente por su ruta_logica completa (UNIQUE), así que
    si el job se ejecuta de nuevo no reenvía lo que ya mandó.
    """
    _verificar_modo_seguro()
    raiz = _carpeta_raiz()
    try:
        carpetas_clientes = await storage_adapter.listar_archivos(raiz)
    except Exception as e:
        logger.error(f"Error listando la carpeta puente raíz '{raiz}': {e}")
        return 0

    enviados = 0
    for telefono in carpetas_clientes:
        carpeta_salida = f"{raiz}/{telefono}/salida"
        try:
            archivos = await storage_adapter.listar_archivos(carpeta_salida)
        except Exception as e:
            logger.warning(f"Error listando la salida de {telefono} en la carpeta puente: {e}")
            continue

        for nombre_archivo in archivos:
            ruta_logica = f"{carpeta_salida}/{nombre_archivo}"
            nuevo_id = database.registrar_documento_puente(telefono, "salida", ruta_logica, nombre_archivo)
            if nuevo_id is None:
                continue  # ya se detectó y se envió en una pasada anterior

            if await _enviar_documento_a_cliente(telefono, ruta_logica, nombre_archivo):
                enviados += 1
            else:
                logger.error(f"No se pudo entregar a {telefono} el documento de la carpeta puente: {ruta_logica}")

    if enviados:
        logger.info(f"Carpeta puente: {enviados} documento(s) nuevo(s) de Claudia enviados a clientes.")
    return enviados
