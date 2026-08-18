import os
import sys
import shutil
import asyncio
import logging
import tempfile
import hashlib
import hmac as hmac_lib
import json as json_lib
from unittest.mock import patch, AsyncMock

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("test_puente_claudia")

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

os.environ.setdefault("GEMINI_API_KEY", "mock_key_para_no_llamar_a_gemini_en_este_test")

TEST_STORAGE_DIR = tempfile.mkdtemp(prefix="puente_claudia_test_")
os.environ["STORAGE_RUTA"] = TEST_STORAGE_DIR
os.environ["STORAGE_TIPO"] = "local"
os.environ["SHAREPOINT_CARPETA_PUENTE"] = "puente_claudia"

import database
import main
import puente_claudia
import storage_adapter

TEL_TEST = "34600007890"
MEDIA_ID_TEST = "fake_media_doc_123"


def _limpiar():
    conn = database.get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM documentos_puente WHERE phone_number = ?", (TEL_TEST,))
    c.execute("DELETE FROM clientes WHERE phone_number = ?", (TEL_TEST,))
    c.execute("DELETE FROM sesiones_activas WHERE phone_number = ?", (TEL_TEST,))
    conn.commit()
    conn.close()


async def run_tests():
    logger.info("================================================================================")
    logger.info("   PRUEBAS: CARPETA PUENTE MAIRA <-> CLAUDIA (recepcion/envio de documentos)")
    logger.info("================================================================================")

    database.init_db()
    _limpiar()

    conn = database.get_connection()
    c = conn.cursor()
    c.execute("""
        INSERT INTO clientes (phone_number, nombre, tipo_cliente, primera_visita, ultima_visita, total_conversaciones)
        VALUES (?, 'Cliente Puente Prueba', 'activo', datetime('now'), datetime('now'), 1)
    """, (TEL_TEST,))
    conn.commit()
    conn.close()

    async def fake_download(media_id, dest_path):
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        with open(dest_path, "wb") as f:
            f.write(b"%PDF-1.4 contenido simulado de un formulario")
        return True

    # -------------------------------------------------------------------------
    # 1. Recepcion de un documento por WhatsApp -> sube a carpeta puente/entrada
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 1: recepcion de documento entrante ---")
    content_doc = {"id": MEDIA_ID_TEST, "filename": "formulario_alta.pdf", "mime_type": "application/pdf"}

    with patch("whatsapp.download_whatsapp_media", new=AsyncMock(side_effect=fake_download)) as mock_download, \
         patch("captura_estructurada.generar_captura_estructurada", new=AsyncMock(return_value={})) as mock_captura:

        respuesta = await main.procesar_flujo_mensaje(TEL_TEST, content_doc, "document")
        logger.info(f"Respuesta: {respuesta}")

        mock_download.assert_called_once()
        assert "formulario_alta.pdf" in respuesta, "La respuesta debe confirmar el nombre del documento recibido"

        await asyncio.sleep(0.05)
        mock_captura.assert_called_once()

    documentos = database.get_documentos_puente_recientes(limit=5)
    entradas = [d for d in documentos if d["phone_number"] == TEL_TEST and d["direccion"] == "entrada"]
    assert len(entradas) == 1, f"Debe haber exactamente 1 documento de entrada registrado, hay {len(entradas)}"
    assert entradas[0]["ruta_logica"].startswith(f"puente_claudia/{TEL_TEST}/entrada/")
    assert entradas[0]["nombre_archivo"] == "formulario_alta.pdf"

    contenido_guardado = await storage_adapter.leer_archivo(entradas[0]["ruta_logica"])
    assert contenido_guardado == b"%PDF-1.4 contenido simulado de un formulario", "El contenido subido debe coincidir con el descargado"

    logger.info("✅ TEST 1 superado: documento recibido, subido a la carpeta puente y registrado en BD.")

    # -------------------------------------------------------------------------
    # 2. Claudia deja un archivo en salida -> el job periodico lo detecta y lo envia
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 2: revision de la carpeta de salida (documento listo de Claudia) ---")

    ruta_salida = f"puente_claudia/{TEL_TEST}/salida/contrato_firmado.pdf"
    await storage_adapter.guardar_archivo(ruta_salida, b"contenido simulado del contrato ya generado por Claudia")

    with patch("whatsapp.upload_whatsapp_media", new=AsyncMock(return_value="media_id_fake_salida")) as mock_upload, \
         patch("whatsapp.send_whatsapp_document", new=AsyncMock(return_value=True)) as mock_send_doc, \
         patch("whatsapp.send_whatsapp_message", new=AsyncMock(return_value=True)):

        enviados = await puente_claudia.revisar_carpeta_salida()
        assert enviados == 1, f"Debe enviar exactamente 1 documento nuevo, envio {enviados}"
        mock_upload.assert_called_once()
        mock_send_doc.assert_called_once()
        assert mock_send_doc.call_args[0][0] == TEL_TEST
        assert mock_send_doc.call_args[0][2] == "contrato_firmado.pdf"

    logger.info("✅ TEST 2 superado: documento de salida detectado y enviado al cliente.")

    # -------------------------------------------------------------------------
    # 3. Idempotencia: una segunda pasada NO debe reenviar el mismo archivo
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 3: idempotencia (no reenviar el mismo documento) ---")

    with patch("whatsapp.upload_whatsapp_media", new=AsyncMock(return_value="media_id_fake_salida")) as mock_upload2, \
         patch("whatsapp.send_whatsapp_document", new=AsyncMock(return_value=True)) as mock_send_doc2, \
         patch("whatsapp.send_whatsapp_message", new=AsyncMock(return_value=True)):

        enviados_2 = await puente_claudia.revisar_carpeta_salida()
        assert enviados_2 == 0, "No debe reenviar un documento ya entregado en una pasada anterior"
        mock_upload2.assert_not_called()
        mock_send_doc2.assert_not_called()

    logger.info("✅ TEST 3 superado: no se reenvia un documento ya entregado (idempotencia por ruta_logica).")

    # -------------------------------------------------------------------------
    # 4. Un segundo archivo nuevo en salida SI se envia (solo lo nuevo)
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 4: un segundo documento nuevo si se envia ---")

    ruta_salida_2 = f"puente_claudia/{TEL_TEST}/salida/factura_final.pdf"
    await storage_adapter.guardar_archivo(ruta_salida_2, b"contenido simulado de la factura final")

    with patch("whatsapp.upload_whatsapp_media", new=AsyncMock(return_value="media_id_fake_salida_2")), \
         patch("whatsapp.send_whatsapp_document", new=AsyncMock(return_value=True)) as mock_send_doc3, \
         patch("whatsapp.send_whatsapp_message", new=AsyncMock(return_value=True)):

        enviados_3 = await puente_claudia.revisar_carpeta_salida()
        assert enviados_3 == 1, f"Debe enviar solo el documento nuevo, envio {enviados_3}"
        mock_send_doc3.assert_called_once()
        assert mock_send_doc3.call_args[0][2] == "factura_final.pdf"

    logger.info("✅ TEST 4 superado: solo se envia lo nuevo, lo ya entregado sigue sin reenviarse.")

    logger.info("\n================================================================================")
    logger.info("   ✅ TESTS 1-4 (nivel funcion) PASARON CORRECTAMENTE")
    logger.info("================================================================================")

    _limpiar()


async def test_webhook_http():
    """
    Prueba a nivel HTTP real: un documento entrante a traves del endpoint /webhook, con firma
    HMAC valida incluida. Existe porque un bug critico anterior en este proyecto (columna
    'ultima_actividad' inexistente) solo se detecto probando el endpoint HTTP real, no llamando
    directamente a procesar_flujo_mensaje: los tests que saltan la capa HTTP tienen un punto
    ciego real sobre bugs de esa capa (parseo del payload de Meta, firma, tipos de 'content').

    Usa httpx.ASGITransport en vez de fastapi.testclient.TestClient porque la version de
    starlette instalada (0.36) es incompatible con la de httpx instalada (0.28: elimino el
    parametro 'app=' de Client.__init__ que TestClient todavia usa).
    """
    logger.info("\n--- TEST 5: documento a traves del endpoint HTTP real /webhook (con firma HMAC) ---")
    import httpx

    database.init_db()
    _limpiar()

    secreto_test = "test_secret_puente"
    main.APP_SECRET = secreto_test
    os.environ["GESTOR_WHATSAPP"] = "34699999999"  # distinto del cliente de prueba

    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": TEL_TEST,
                        "type": "document",
                        "document": {
                            "id": "media_http_test",
                            "filename": "escritura.docx",
                            "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                        }
                    }]
                }
            }]
        }]
    }
    raw_body = json_lib.dumps(payload).encode("utf-8")
    firma = hmac_lib.new(secreto_test.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()

    async def fake_download(media_id, dest_path):
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        with open(dest_path, "wb") as f:
            f.write(b"contenido simulado de una escritura")
        return True

    with patch("whatsapp.download_whatsapp_media", new=AsyncMock(side_effect=fake_download)), \
         patch("whatsapp.send_whatsapp_message", new=AsyncMock(return_value=True)), \
         patch("captura_estructurada.generar_captura_estructurada", new=AsyncMock(return_value={})):

        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/webhook",
                content=raw_body,
                headers={"X-Hub-Signature-256": f"sha256={firma}", "Content-Type": "application/json"}
            )

    assert response.status_code == 200, f"El webhook debe responder 200, respondio {response.status_code}: {response.text}"
    assert response.json().get("status") == "success"

    documentos = database.get_documentos_puente_recientes(limit=5)
    entradas_http = [d for d in documentos if d["phone_number"] == TEL_TEST and d["nombre_archivo"] == "escritura.docx"]
    assert len(entradas_http) == 1, "El documento enviado por el endpoint HTTP real debe quedar registrado en la carpeta puente"

    logger.info("✅ TEST 5 superado: documento recibido via /webhook real (firma HMAC incluida), sin errores de tipos.")
    _limpiar()


async def run_all():
    await run_tests()
    await test_webhook_http()


if __name__ == "__main__":
    try:
        asyncio.run(run_all())
        logger.info("\n================================================================================")
        logger.info("   ✅ TODAS LAS PRUEBAS DE LA CARPETA PUENTE PASARON CORRECTAMENTE (1-5)")
        logger.info("================================================================================")
    finally:
        shutil.rmtree(TEST_STORAGE_DIR, ignore_errors=True)
