import os
import sys
import asyncio
import logging
from unittest.mock import patch, AsyncMock, MagicMock

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("test_telegram_handler")

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

os.environ.setdefault("GEMINI_API_KEY", "mock_key_para_no_llamar_a_gemini_en_este_test")

import database
import telegram_handler

CHAT_ID_TEST = "999888777"
CHAT_ID_GESTOR_TEST = "111222333"


def _limpiar():
    conn = database.get_connection()
    c = conn.cursor()
    for chat_id in (CHAT_ID_TEST, CHAT_ID_GESTOR_TEST):
        c.execute("DELETE FROM messages WHERE phone_number = ?", (chat_id,))
        c.execute("DELETE FROM clientes WHERE phone_number = ?", (chat_id,))
        c.execute("DELETE FROM sesiones_activas WHERE phone_number = ?", (chat_id,))
    conn.commit()
    conn.close()


def _fake_update(texto=None, chat_id=CHAT_ID_TEST, con_foto=False):
    update = MagicMock()
    update.effective_chat.id = int(chat_id)
    update.message.reply_text = AsyncMock(return_value=True)
    if texto is not None:
        update.message.text = texto
    else:
        update.message.text = None
    update.message.photo = ["fake_photo"] if con_foto else None
    return update


async def run_tests():
    logger.info("================================================================================")
    logger.info("   PRUEBAS: BOT DE TELEGRAM PARA MAIRA")
    logger.info("================================================================================")

    database.init_db()
    _limpiar()
    os.environ["GESTOR_TELEGRAM_CHAT_ID"] = CHAT_ID_GESTOR_TEST

    # -------------------------------------------------------------------------
    # 1. Mensaje de texto normal -> pasa por el MISMO orquestador que WhatsApp texto
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 1: mensaje de texto normal ---")
    update = _fake_update(texto="Hola, quiero pedir cita")

    with patch("main.procesar_flujo_mensaje", new=AsyncMock(return_value="Claro, ¿qué día te viene bien?")) as mock_procesar, \
         patch("captura_estructurada.generar_captura_estructurada", new=AsyncMock(return_value={})) as mock_captura:

        await telegram_handler._handle_message(update, MagicMock())

        mock_procesar.assert_called_once_with(CHAT_ID_TEST, "Hola, quiero pedir cita", "text")
        update.message.reply_text.assert_called_once_with("Claro, ¿qué día te viene bien?")

        await asyncio.sleep(0.05)
        mock_captura.assert_called_once()
        assert mock_captura.call_args[0][2] == "telegram_texto"

    historial = database.get_history(CHAT_ID_TEST, limit=5)
    roles = [h["role"] for h in historial]
    assert "user" in roles and "assistant" in roles, "El mensaje y la respuesta deben quedar en el historial"

    logger.info("✅ TEST 1 superado: texto de Telegram enrutado por procesar_flujo_mensaje y guardado en historial.")

    # -------------------------------------------------------------------------
    # 2. Adjunto no soportado (foto) -> aviso, sin llamar al orquestador
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 2: adjunto no soportado (foto) ---")
    update_foto = _fake_update(texto=None, con_foto=True)

    with patch("main.procesar_flujo_mensaje", new=AsyncMock()) as mock_procesar_foto:
        await telegram_handler._handle_message(update_foto, MagicMock())
        mock_procesar_foto.assert_not_called()
        update_foto.message.reply_text.assert_called_once_with(telegram_handler.MSG_SOLO_TEXTO)

    logger.info("✅ TEST 2 superado: adjunto no soportado responde con aviso, sin tocar el orquestador.")

    # -------------------------------------------------------------------------
    # 3. Mensaje desde el chat_id del gestor -> se enruta a gestor_mode, no al flujo normal
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 3: comando de gestor por Telegram ---")
    update_gestor = _fake_update(texto="/capturas_pendientes", chat_id=CHAT_ID_GESTOR_TEST)

    with patch("gestor_mode.procesar_comando", new=AsyncMock(return_value="No hay capturas estructuradas pendientes de revisión.")) as mock_gestor, \
         patch("main.procesar_flujo_mensaje", new=AsyncMock()) as mock_procesar_gestor:

        await telegram_handler._handle_message(update_gestor, MagicMock())

        mock_gestor.assert_called_once_with(CHAT_ID_GESTOR_TEST, "/capturas_pendientes")
        mock_procesar_gestor.assert_not_called()
        update_gestor.message.reply_text.assert_called_once_with("No hay capturas estructuradas pendientes de revisión.")

    logger.info("✅ TEST 3 superado: comandos de gestor por Telegram se enrutan aparte del flujo normal de cliente.")

    logger.info("\n================================================================================")
    logger.info("   ✅ TODAS LAS PRUEBAS DEL BOT DE TELEGRAM PASARON CORRECTAMENTE")
    logger.info("================================================================================")

    _limpiar()


if __name__ == "__main__":
    asyncio.run(run_tests())
