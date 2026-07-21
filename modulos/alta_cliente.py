import os
import logging
from datetime import datetime, timedelta
import database

logger = logging.getLogger(__name__)

# Memoria temporal de la sesión de alta de cliente
# { phone_number: { "paso": "nombre", "nombre": None, "nif_cif": None, "motivo": None, "intencion_original": "...", "mensaje_original": "...", "timestamp": datetime } }
_alta_sesiones = {}
TIMEOUT_MINUTOS_ALTA = 15

def limpiar_sesiones_expiradas():
    """
    Limpia sesiones abandonadas que hayan superado el tiempo límite de inactividad.
    """
    ahora = datetime.now()
    expirados = []
    for phone, sesion in _alta_sesiones.items():
        if ahora - sesion.get("timestamp", ahora) > timedelta(minutes=TIMEOUT_MINUTOS_ALTA):
            expirados.append(phone)
            
    for phone in expirados:
        logger.info(f"Limpiando sesión expirada de alta de cliente para {phone}")
        _alta_sesiones.pop(phone, None)

def esta_en_alta(phone_number: str) -> bool:
    limpiar_sesiones_expiradas()
    return phone_number in _alta_sesiones

def iniciar_alta(phone_number: str, intencion_original: str, mensaje_original: str) -> str:
    """
    Inicia el flujo de registro/alta para un cliente nuevo que solicita una acción que requiere datos.
    """
    limpiar_sesiones_expiradas()
    _alta_sesiones[phone_number] = {
        "paso": "nombre",
        "nombre": None,
        "nif_cif": None,
        "motivo": None,
        "intencion_original": intencion_original,
        "mensaje_original": mensaje_original,
        "timestamp": datetime.now()
    }
    logger.info(f"Iniciado flujo de alta de cliente para {phone_number} (Intención original: {intencion_original})")
    
    return (
        "👋 ¡Hola! Bienvenido/a. Para poder atender tu solicitud correctamente, "
        "necesitamos tomar tus datos básicos de contacto.\n\n"
        "Por favor, indícame tu *nombre y apellidos completos*:"
    )

async def gestionar_alta(phone_number: str, content: str) -> str:
    """
    Procesa las respuestas del cliente dentro de la máquina de estados de alta de forma asíncrona.
    """
    limpiar_sesiones_expiradas()
    if phone_number not in _alta_sesiones:
        return "No hay ninguna sesión de registro activa. ¿En qué puedo ayudarte?"

    sesion = _alta_sesiones[phone_number]
    sesion["timestamp"] = datetime.now()
    paso = sesion["paso"]
    text_clean = content.strip()

    # PASO 1: Nombre completo
    if paso == "nombre":
        if len(text_clean) < 2:
            return "Por favor, introduce un nombre válido para continuar:"
            
        sesion["nombre"] = text_clean
        sesion["paso"] = "nif"
        return (
            f"Muchas gracias, *{text_clean}*.\n\n"
            "Para completar tu ficha, ¿podrías indicarme tu *NIF/CIF o DNI*? "
            "(Si prefieres no indicarlo ahora, puedes responder 'omitir')."
        )

    # PASO 2: NIF/CIF (Opcional)
    elif paso == "nif":
        if text_clean.lower() in ["omitir", "no", "saltar", "-"]:
            sesion["nif_cif"] = None
        else:
            sesion["nif_cif"] = text_clean.upper()
            
        sesion["paso"] = "motivo"
        return (
            "¡Perfecto! Por último, indícame brevemente el *motivo principal* "
            "de tu consulta o gestión:"
        )

    # PASO 3: Motivo y Guardado Final
    elif paso == "motivo":
        sesion["motivo"] = text_clean
        nombre = sesion["nombre"]
        nif_cif = sesion["nif_cif"]
        motivo = sesion["motivo"]
        intencion = sesion["intencion_original"]
        mensaje_orig = sesion["mensaje_original"]

        # Guardar en SQLite
        conn = database.get_connection()
        cursor = conn.cursor()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        fecha_alta = datetime.now().strftime("%Y-%m-%d")
        
        cursor.execute("SELECT phone_number FROM clientes WHERE phone_number = ?", (phone_number,))
        row = cursor.fetchone()
        
        if row is None:
            cursor.execute("""
                INSERT INTO clientes (phone_number, nombre, nif_cif, tipo_cliente, fecha_alta, primera_visita, ultima_visita, notas, total_conversaciones)
                VALUES (?, ?, ?, 'nuevo', ?, ?, ?, ?, 1)
            """, (phone_number, nombre, nif_cif, fecha_alta, now_str, now_str, f"Motivo alta: {motivo}"))
        else:
            cursor.execute("""
                UPDATE clientes
                SET nombre = ?, nif_cif = ?, tipo_cliente = 'nuevo', fecha_alta = ?, ultima_visita = ?, notas = ?
                WHERE phone_number = ?
            """, (nombre, nif_cif, fecha_alta, now_str, f"Motivo alta: {motivo}", phone_number))
            
        conn.commit()
        conn.close()
        logger.info(f"Completado registro de alta para {phone_number} ({nombre})")

        _alta_sesiones.pop(phone_number, None)

        res_bienvenida = f"✅ *Registro completado.* ¡Gracias {nombre}!\n\n"
        
        if intencion == "AGENDA":
            from modulos import agenda
            history = database.get_history(phone_number, limit=5)
            res_agenda = await agenda.procesar_agenda(phone_number, mensaje_orig, history)
            return res_bienvenida + (res_agenda or "")
            
        elif intencion == "FACTURA":
            from modulos import facturas
            res_factura = await facturas.procesar_solicitud_factura(phone_number, mensaje_orig)
            return res_bienvenida + res_factura
            
        elif intencion == "TICKET":
            return res_bienvenida + "Para registrar tu ticket de gasto, por favor envíame ahora la foto del ticket."
            
        elif intencion == "TRIAJE":
            from modulos import triaje
            res_triaje = await triaje.gestionar_triaje(phone_number, mensaje_orig, "text")
            return res_bienvenida + res_triaje
            
        else:
            return res_bienvenida + "¿En qué puedo ayudarte hoy?"

    return "Ocurrió un estado inesperado durante el registro. Por favor, intenta de nuevo."
