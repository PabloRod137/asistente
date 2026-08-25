import os
import logging
from datetime import datetime, timedelta

import email_adapter

logger = logging.getLogger("asistente.alertas_desarrollador")

# Cooldown por clave de problema, para no inundar el correo si el mismo fallo se repite en
# cada petición durante una caída prolongada (ej. credenciales de Graph rotas durante horas).
_ultima_alerta_por_clave = {}


async def enviar_alerta_desarrollador(clave: str, asunto: str, mensaje: str, cooldown_horas: int = 12) -> None:
    """
    Notifica por email al desarrollador (DEV_ALERT_EMAIL) de un problema operativo: credenciales
    que fallan, secretos a punto de caducar, etc. Pensado para problemas técnicos que no debe
    recibir el gestor del despacho (GESTOR_EMAIL/GESTOR_WHATSAPP) -- ese canal es para el cliente,
    este es para quien mantiene el código.
    """
    dev_email = os.getenv("DEV_ALERT_EMAIL")
    if not dev_email:
        return

    ahora = datetime.now()
    ultima = _ultima_alerta_por_clave.get(clave)
    if ultima and (ahora - ultima) < timedelta(hours=cooldown_horas):
        return

    try:
        await email_adapter.enviar_email(
            destinatario=dev_email,
            asunto=f"[Maira - Alerta técnica] {asunto}",
            cuerpo_texto=mensaje
        )
        _ultima_alerta_por_clave[clave] = ahora
        logger.info(f"Alerta de desarrollador enviada: {clave}")
    except Exception as e:
        # Si el propio envío de email falla (ej. SMTP roto), no hay más canal de aviso que el
        # log -- limitación conocida: este mecanismo depende del mismo canal de correo.
        logger.error(f"Error enviando alerta de desarrollador ({clave}): {e}")


async def verificar_caducidades() -> None:
    """
    Job diario: revisa credenciales con fecha de caducidad conocida (por ahora, el secreto de
    Microsoft Graph) y avisa con antelación antes de que dejen de funcionar.
    """
    secreto_expira_str = os.getenv("MS_CLIENT_SECRET_EXPIRA")
    if not secreto_expira_str:
        return

    try:
        fecha_expira = datetime.strptime(secreto_expira_str, "%Y-%m-%d").date()
    except ValueError:
        logger.error(f"MS_CLIENT_SECRET_EXPIRA con formato inválido (se espera YYYY-MM-DD): {secreto_expira_str}")
        return

    dias_restantes = (fecha_expira - datetime.now().date()).days

    if dias_restantes < 0:
        await enviar_alerta_desarrollador(
            clave="ms_client_secret_caducado",
            asunto="El secreto de Microsoft Graph YA HA CADUCADO",
            mensaje=(
                f"MS_CLIENT_SECRET caducó el {fecha_expira.isoformat()}. Microsoft Graph "
                "(SharePoint, correo, calendario) puede estar fallando ahora mismo.\n\n"
                "Genera uno nuevo en Azure Portal > Entra ID > App registrations > Maira > "
                "Certificates & secrets > New client secret, y actualiza MS_CLIENT_SECRET y "
                "MS_CLIENT_SECRET_EXPIRA en el .env."
            ),
            cooldown_horas=24
        )
    elif dias_restantes <= 30:
        await enviar_alerta_desarrollador(
            clave="ms_client_secret_expira",
            asunto=f"El secreto de Microsoft Graph caduca en {dias_restantes} días",
            mensaje=(
                f"MS_CLIENT_SECRET caduca el {fecha_expira.isoformat()} ({dias_restantes} días).\n\n"
                "Genera uno nuevo en Azure Portal > Entra ID > App registrations > Maira > "
                "Certificates & secrets > New client secret, y actualiza MS_CLIENT_SECRET y "
                "MS_CLIENT_SECRET_EXPIRA en el .env."
            ),
            cooldown_horas=24
        )
