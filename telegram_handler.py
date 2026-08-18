import os
import logging

from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

import database
import client_memory
import escalado_humano
import conversation_summary
import captura_estructurada
import gestor_mode

logger = logging.getLogger("asistente.telegram_handler")

# Instancia única del bot (Maira es de un solo cliente/tenant, a diferencia del proyecto
# Chatbot genérico, que gestiona un diccionario de bots por client_id).
_app = None

MSG_SOLO_TEXTO = "Por ahora, por Telegram solo puedo leer mensajes de texto. ¿Puedes escribírmelo, por favor?"


async def _handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    if not update.message.text:
        await update.message.reply_text(MSG_SOLO_TEXTO)
        return

    # Se usa el chat_id de Telegram como identificador, en el mismo campo phone_number que
    # usa WhatsApp. Importante: esto es una identidad DISTINTA de la del mismo cliente por
    # WhatsApp (no hay fusión automática) -- ver limitación documentada en el README.
    chat_id = str(update.effective_chat.id)
    texto = update.message.text
    logger.info(f"[Telegram] Mensaje recibido de {chat_id}: {texto[:100]}")

    # Import diferido: main.py importa este módulo para arrancar el bot, así que un import
    # a nivel de módulo aquí crearía un ciclo (main <-> telegram_handler).
    import main

    gestor_chat_id = os.getenv("GESTOR_TELEGRAM_CHAT_ID")
    if gestor_chat_id and chat_id == gestor_chat_id:
        respuesta_gestor = await gestor_mode.procesar_comando(chat_id, texto)
        if respuesta_gestor is not None:
            await update.message.reply_text(respuesta_gestor)
            return

    client_memory.registrar_visita(chat_id)
    database.save_message(chat_id, "user", texto)
    escalado_humano.resolver_ticket_si_despedida(chat_id, texto)
    conversation_summary.registrar_actividad(chat_id)

    ai_response = await main.procesar_flujo_mensaje(chat_id, texto, "text")

    database.save_message(chat_id, "assistant", ai_response)
    await update.message.reply_text(ai_response)

    main.lanzar_tarea_segundo_plano(
        captura_estructurada.generar_captura_estructurada(chat_id, texto, "telegram_texto")
    )

    if escalado_humano.detectar_necesidad_escalado(ai_response):
        await escalado_humano.crear_ticket_escalado(chat_id, texto, ai_response)

    if conversation_summary.detectar_despedida(texto):
        await conversation_summary.generar_y_enviar_resumen(chat_id)


async def iniciar_bot_telegram():
    global _app
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.info("TELEGRAM_BOT_TOKEN no configurado. Bot de Telegram no iniciado.")
        return

    _app = ApplicationBuilder().token(token).build()
    _app.add_handler(MessageHandler(filters.ALL, _handle_message))
    await _app.initialize()
    await _app.start()
    await _app.updater.start_polling()
    logger.info("Bot de Telegram iniciado correctamente (modo polling).")


async def detener_bot_telegram():
    global _app
    if _app is None:
        return
    try:
        if _app.updater and _app.updater.running:
            await _app.updater.stop()
        await _app.stop()
        await _app.shutdown()
        logger.info("Bot de Telegram detenido correctamente.")
    except Exception as e:
        logger.error(f"Error deteniendo el bot de Telegram: {e}")
    finally:
        _app = None
