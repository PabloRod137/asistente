import os
import logging
from datetime import datetime, timedelta
import database
import client_matching

logger = logging.getLogger(__name__)

RESPUESTAS_SI = {"si", "sí", "s", "yes", "confirmo", "correcto", "exacto"}
RESPUESTAS_NO = {"no", "n", "nop", "negativo"}


async def _continuar_segun_intencion(phone_number: str, intencion: str, mensaje_orig: str) -> str:
    """
    Despacha la solicitud original del cliente (agenda, factura, ticket, triaje...) una vez ya
    identificado — reutilizado tanto por el alta manual completa como por la vinculación
    automática con un cliente de la lista de espera.
    """
    if intencion == "AGENDA":
        from modulos import agenda
        history = database.get_history(phone_number, limit=5)
        res_agenda = await agenda.procesar_agenda(phone_number, mensaje_orig, history)
        return res_agenda or ""

    elif intencion == "FACTURA":
        from modulos import facturas
        return await facturas.procesar_solicitud_factura(phone_number, mensaje_orig)

    elif intencion == "TICKET":
        return "Para registrar tu ticket de gasto, por favor envíame ahora la foto del ticket."

    elif intencion == "TRIAJE":
        from modulos import triaje
        return await triaje.gestionar_triaje(phone_number, mensaje_orig, "text")

    else:
        return "¿En qué puedo ayudarte hoy?"


def esta_en_alta(phone_number: str) -> bool:
    return database.get_session(phone_number, "alta_cliente") is not None

def iniciar_alta(phone_number: str, intencion_original: str, mensaje_original: str) -> str:
    """
    Inicia el flujo de registro/alta para un cliente nuevo persistiéndolo en SQLite de forma asíncrona.
    """
    sesion = {
        "paso": "nombre",
        "nombre": None,
        "nif_cif": None,
        "motivo": None,
        "intencion_original": intencion_original,
        "mensaje_original": mensaje_original
    }
    database.save_session(phone_number, "alta_cliente", sesion)
    logger.info(f"Iniciado flujo de alta de cliente para {phone_number} (Intención original: {intencion_original})")
    
    return (
        "👋 ¡Hola! Bienvenido/a. Para poder atender tu solicitud correctamente, "
        "necesitamos tomar tus datos básicos de contacto.\n\n"
        "Por favor, indícame tu *nombre y apellidos completos*:"
    )

async def gestionar_alta(phone_number: str, content: str) -> str:
    """
    Procesa las respuestas del cliente dentro de la máquina de estados de alta persistiéndolas en SQLite de forma asíncrona.
    """
    sesion = database.get_session(phone_number, "alta_cliente")
    if not sesion:
        return "No hay ninguna sesión de registro activa. ¿En qué puedo ayudarte?"

    paso = sesion["paso"]
    text_clean = content.strip()

    # PASO 1: Nombre completo
    if paso == "nombre":
        if len(text_clean) < 2:
            return "Por favor, introduce un nombre válido para continuar:"

        # ¿Coincide con algún cliente real de LexGuardian importado sin teléfono todavía?
        candidato = client_matching.buscar_coincidencia(text_clean)
        if candidato:
            sesion["nombre"] = text_clean
            sesion["paso"] = "confirmar_coincidencia"
            sesion["pendiente_id"] = candidato["id"]
            sesion["intentos_confirmacion"] = 0
            database.save_session(phone_number, "alta_cliente", sesion)
            exp_txt = f", expediente *{candidato['numero_expediente']}*" if candidato.get("numero_expediente") else ""
            return (
                f"¿Eres tú *{candidato['nombre']}*{exp_txt}? Ya tenemos tus datos registrados en el despacho.\n\n"
                "Responde *SÍ* para confirmarlo, o *NO* si no eres tú."
            )

        sesion["nombre"] = text_clean
        sesion["paso"] = "nif"
        database.save_session(phone_number, "alta_cliente", sesion)
        return (
            f"Muchas gracias, *{text_clean}*.\n\n"
            "Para completar tu ficha, ¿podrías indicarme tu *NIF/CIF o DNI*? "
            "(Si prefieres no indicarlo ahora, puedes responder 'omitir')."
        )

    # PASO 1.5: Confirmación de coincidencia con la lista de espera
    elif paso == "confirmar_coincidencia":
        respuesta = text_clean.lower()
        if respuesta in RESPUESTAS_SI:
            pendiente_id = sesion["pendiente_id"]
            cliente = database.promover_cliente_pendiente(pendiente_id, phone_number)
            database.delete_session(phone_number, "alta_cliente")

            if not cliente:
                logger.warning(f"Pendiente #{pendiente_id} ya no disponible al confirmar para {phone_number}.")
                sesion_nueva = {
                    "paso": "nif", "nombre": sesion["nombre"], "nif_cif": None, "motivo": None,
                    "intencion_original": sesion["intencion_original"], "mensaje_original": sesion["mensaje_original"]
                }
                database.save_session(phone_number, "alta_cliente", sesion_nueva)
                return (
                    "Vaya, esa ficha ya se vinculó a otro número justo antes. Vamos a darte de alta de todas formas: "
                    "¿podrías indicarme tu *NIF/CIF o DNI*? (o responde 'omitir')."
                )

            res_bienvenida = f"✅ *¡Perfecto, {cliente['nombre']}!* Ya tienes tu ficha vinculada"
            if cliente.get("numero_expediente"):
                res_bienvenida += f", expediente *{cliente['numero_expediente']}*"
            res_bienvenida += ".\n\n"

            logger.info(f"Cliente pendiente vinculado automáticamente con {phone_number} ({cliente['nombre']}).")
            res_continuacion = await _continuar_segun_intencion(
                phone_number, sesion["intencion_original"], sesion["mensaje_original"]
            )
            return res_bienvenida + res_continuacion

        elif respuesta in RESPUESTAS_NO:
            sesion["paso"] = "nif"
            sesion.pop("pendiente_id", None)
            database.save_session(phone_number, "alta_cliente", sesion)
            return (
                "De acuerdo, disculpa la confusión — sigamos con tu alta.\n\n"
                "¿Podrías indicarme tu *NIF/CIF o DNI*? (Si prefieres no indicarlo ahora, responde 'omitir')."
            )
        else:
            intentos = sesion.get("intentos_confirmacion", 0) + 1
            if intentos >= 3:
                # Tras varias respuestas que no son ni sí ni no, no dejamos al cliente atascado:
                # seguimos con el alta manual normal en vez de repetir la pregunta indefinidamente.
                sesion["paso"] = "nif"
                sesion.pop("pendiente_id", None)
                sesion.pop("intentos_confirmacion", None)
                database.save_session(phone_number, "alta_cliente", sesion)
                return (
                    "No he entendido tu respuesta, así que sigamos con el alta normal para no liarnos.\n\n"
                    "¿Podrías indicarme tu *NIF/CIF o DNI*? (Si prefieres no indicarlo ahora, responde 'omitir')."
                )
            sesion["intentos_confirmacion"] = intentos
            database.save_session(phone_number, "alta_cliente", sesion)
            return "Por favor, responde *SÍ* o *NO* para continuar."

    # PASO 2: NIF/CIF (Opcional)
    elif paso == "nif":
        if text_clean.lower() in ["omitir", "no", "saltar", "-"]:
            sesion["nif_cif"] = None
        else:
            sesion["nif_cif"] = text_clean.upper()
            
        sesion["paso"] = "motivo"
        database.save_session(phone_number, "alta_cliente", sesion)
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

        database.delete_session(phone_number, "alta_cliente")

        res_bienvenida = f"✅ *Registro completado.* ¡Gracias {nombre}!\n\n"
        res_continuacion = await _continuar_segun_intencion(phone_number, intencion, mensaje_orig)
        return res_bienvenida + res_continuacion

    return "Ocurrió un estado inesperado durante el registro. Por favor, intenta de nuevo."
