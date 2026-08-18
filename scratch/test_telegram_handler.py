import os
import sys
import shutil
import asyncio
import tempfile
import logging
from unittest.mock import patch, AsyncMock, MagicMock

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("test_telegram_handler")

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

os.environ.setdefault("GEMINI_API_KEY", "mock_key_para_no_llamar_a_gemini_en_este_test")

TEST_STORAGE_DIR = tempfile.mkdtemp(prefix="telegram_handler_test_")
os.environ["STORAGE_RUTA"] = TEST_STORAGE_DIR
os.environ["STORAGE_TIPO"] = "local"

import database
import telegram_handler

CHAT_ID_TEST = "999888777"
CHAT_ID_GESTOR_TEST = "111222333"


def _limpiar():
    conn = database.get_connection()
    c = conn.cursor()
    for chat_id in (CHAT_ID_TEST, CHAT_ID_GESTOR_TEST):
        c.execute("DELETE FROM messages WHERE phone_number = ?", (chat_id,))
        c.execute("DELETE FROM documentos_puente WHERE phone_number = ?", (chat_id,))
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
    update.message.document = None
    return update


def _fake_update_documento(chat_id=CHAT_ID_TEST, nombre_archivo="formulario.pdf", contenido=b"contenido simulado de un documento de telegram"):
    update = MagicMock()
    update.effective_chat.id = int(chat_id)
    update.message.reply_text = AsyncMock(return_value=True)
    update.message.text = None

    doc = MagicMock()
    doc.file_name = nombre_archivo
    doc.mime_type = "application/pdf"
    doc.file_id = "fake_file_id_telegram"

    archivo_telegram = MagicMock()
    archivo_telegram.download_as_bytearray = AsyncMock(return_value=bytearray(contenido))
    doc.get_file = AsyncMock(return_value=archivo_telegram)

    update.message.document = doc
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
        update_foto.message.reply_text.assert_called_once_with(telegram_handler.MSG_SOLO_TEXTO_O_DOCUMENTO)

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

    # -------------------------------------------------------------------------
    # 4. Documento de Telegram -> sube a la carpeta puente, igual que WhatsApp
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 4: documento recibido por Telegram ---")
    update_doc = _fake_update_documento(nombre_archivo="escritura_compraventa.pdf")

    with patch("captura_estructurada.generar_captura_estructurada", new=AsyncMock(return_value={})) as mock_captura_doc:
        await telegram_handler._handle_message(update_doc, MagicMock())

        update_doc.message.document.get_file.assert_called_once()
        update_doc.message.reply_text.assert_called_once()
        respuesta_doc = update_doc.message.reply_text.call_args[0][0]
        assert "escritura_compraventa.pdf" in respuesta_doc

        await asyncio.sleep(0.05)
        mock_captura_doc.assert_called_once()
        assert mock_captura_doc.call_args[0][2] == "telegram_documento"

    import storage_adapter
    documentos = database.get_documentos_puente_recientes(limit=5)
    entradas = [d for d in documentos if d["phone_number"] == CHAT_ID_TEST and d["direccion"] == "entrada"]
    assert len(entradas) == 1, f"Debe haber exactamente 1 documento de entrada registrado, hay {len(entradas)}"
    assert entradas[0]["ruta_logica"].startswith(f"puente_claudia/{CHAT_ID_TEST}/entrada/")

    contenido_guardado = await storage_adapter.leer_archivo(entradas[0]["ruta_logica"])
    assert contenido_guardado == b"contenido simulado de un documento de telegram"

    logger.info("✅ TEST 4 superado: documento de Telegram subido a la carpeta puente, igual que WhatsApp.")

    logger.info("\n================================================================================")
    logger.info("   ✅ TODAS LAS PRUEBAS DEL BOT DE TELEGRAM PASARON CORRECTAMENTE")
    logger.info("================================================================================")

    _limpiar()


if __name__ == "__main__":
    try:
        asyncio.run(run_tests())
    finally:
        shutil.rmtree(TEST_STORAGE_DIR, ignore_errors=True)
