import os
import sys
import asyncio
import logging
from unittest.mock import patch, AsyncMock

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("test_audio_whatsapp")

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

os.environ.setdefault("GEMINI_API_KEY", "mock_key_para_no_llamar_a_gemini_en_este_test")

import database
import main
import captura_estructurada

TEL_TEST = "34600005678"
MEDIA_ID_TEST = "fake_media_id_999"
TRANSCRIPCION_FAKE = "Hola, soy Marta, quería preguntar por vuestro horario de atención al público."


async def run_tests():
    logger.info("================================================================================")
    logger.info("       INICIANDO PRUEBAS: NOTAS DE VOZ DE WHATSAPP (FASE 8.2)")
    logger.info("================================================================================")

    database.init_db()

    # Registrar el cliente de prueba como activo para que el enrutado de intención
    # (AGENDA) llegue directamente al flujo normal en vez de activar alta_cliente,
    # que es un flujo aparte ya cubierto por sus propios tests (fase 3).
    conn = database.get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM clientes WHERE phone_number = ?", (TEL_TEST,))
    c.execute("DELETE FROM sesiones_activas WHERE phone_number = ?", (TEL_TEST,))
    c.execute("""
        INSERT INTO clientes (phone_number, nombre, tipo_cliente, primera_visita, ultima_visita, total_conversaciones)
        VALUES (?, 'Marta Prueba', 'activo', datetime('now'), datetime('now'), 1)
    """, (TEL_TEST,))
    conn.commit()
    conn.close()

    async def fake_download(media_id, dest_path):
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        with open(dest_path, "wb") as f:
            f.write(b"contenido_de_audio_simulado")
        return True

    # -------------------------------------------------------------------------
    # 1. Camino feliz: descarga OK, transcripción OK -> se reprocesa como texto
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 1: audio descargado y transcrito correctamente ---")
    with patch("whatsapp.download_whatsapp_media", new=AsyncMock(side_effect=fake_download)) as mock_download, \
         patch("captura_estructurada.transcribir_audio", new=AsyncMock(return_value=TRANSCRIPCION_FAKE)) as mock_transcribe, \
         patch("captura_estructurada.generar_captura_estructurada", new=AsyncMock(return_value={})) as mock_captura, \
         patch("llm.generate_response", new=AsyncMock(return_value="Claro, ¿qué día te viene bien?")) as mock_llm:

        respuesta = await main.procesar_flujo_mensaje(TEL_TEST, MEDIA_ID_TEST, "audio")
        logger.info(f"Respuesta final: {respuesta}")

        mock_download.assert_called_once()
        assert mock_download.call_args[0][0] == MEDIA_ID_TEST, "Debe descargar exactamente el media_id recibido"

        mock_transcribe.assert_called_once()
        temp_path_usado = mock_transcribe.call_args[0][0]
        assert not os.path.exists(temp_path_usado), "El archivo de audio temporal debe eliminarse tras transcribir"

        # Dar tiempo a la tarea en segundo plano (asyncio.create_task) de la captura estructurada
        await asyncio.sleep(0.05)
        mock_captura.assert_called_once()
        args_captura = mock_captura.call_args[0]
        assert args_captura[0] == TEL_TEST
        assert args_captura[1] == TRANSCRIPCION_FAKE, "La captura estructurada debe recibir la TRANSCRIPCIÓN, no el media_id"
        assert args_captura[2] == "whatsapp_audio"

        assert respuesta == "Claro, ¿qué día te viene bien?", "Debe devolver la respuesta generada a partir del texto transcrito"

    logger.info("✅ TEST 1 superado: audio -> transcripción -> mismo pipeline de texto, con limpieza de temporales.")

    # -------------------------------------------------------------------------
    # 2. Fallo de descarga -> mensaje de error amigable, sin excepción
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 2: fallo al descargar el audio ---")
    with patch("whatsapp.download_whatsapp_media", new=AsyncMock(return_value=False)):
        respuesta_fallo_descarga = await main.procesar_flujo_mensaje(TEL_TEST, MEDIA_ID_TEST, "audio")
        logger.info(f"Respuesta: {respuesta_fallo_descarga}")
        assert "descargar" in respuesta_fallo_descarga.lower()
    logger.info("✅ TEST 2 superado: fallo de descarga gestionado con mensaje amigable.")

    # -------------------------------------------------------------------------
    # 3. Fallo de transcripción (None) -> mensaje de error amigable
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 3: fallo al transcribir (audio ininteligible) ---")
    with patch("whatsapp.download_whatsapp_media", new=AsyncMock(side_effect=fake_download)), \
         patch("captura_estructurada.transcribir_audio", new=AsyncMock(return_value=None)):
        respuesta_fallo_transcripcion = await main.procesar_flujo_mensaje(TEL_TEST, MEDIA_ID_TEST, "audio")
        logger.info(f"Respuesta: {respuesta_fallo_transcripcion}")
        assert "entendido" in respuesta_fallo_transcripcion.lower() or "escribirlo" in respuesta_fallo_transcripcion.lower()
    logger.info("✅ TEST 3 superado: fallo de transcripción gestionado con mensaje amigable.")

    logger.info("\n================================================================================")
    logger.info("       ✅ TODAS LAS PRUEBAS DE NOTAS DE VOZ DE WHATSAPP PASARON CORRECTAMENTE")
    logger.info("================================================================================")

    # Limpieza final
    conn = database.get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM clientes WHERE phone_number = ?", (TEL_TEST,))
    c.execute("DELETE FROM sesiones_activas WHERE phone_number = ?", (TEL_TEST,))
    conn.commit()
    conn.close()


if __name__ == "__main__":
    asyncio.run(run_tests())
