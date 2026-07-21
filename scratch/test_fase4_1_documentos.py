import os
import sys
import logging
from datetime import datetime, timedelta

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_fase4_1_documentos")

def test_fase4_1():
    import database
    import gestor_mode
    import client_memory
    import whatsapp
    from modulos import recordatorios

    database.init_db()
    test_phone = "34611223344"
    gestor_phone = "34600000000"

    # Clean previous test records
    conn = database.get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM documentos_pendientes WHERE phone_number = ?", (test_phone,))
    c.execute("DELETE FROM clientes WHERE phone_number = ?", (test_phone,))
    conn.commit()
    conn.close()

    # Register client Maria Garcia
    client_memory.registrar_visita(test_phone)
    conn = database.get_connection()
    c = conn.cursor()
    c.execute("UPDATE clientes SET nombre = 'Maria Garcia', tipo_cliente = 'activo' WHERE phone_number = ?", (test_phone,))
    conn.commit()
    conn.close()

    logger.info("--- 1. Probar comando /documento_pendiente ---")
    fecha_limite_cercana = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")
    res_add = gestor_mode.procesar_comando(gestor_phone, f'/documento_pendiente {test_phone} "Declaración IRPF 2025" {fecha_limite_cercana}')
    logger.info(f"Resultado /documento_pendiente:\n{res_add}")
    assert "registrado con éxito" in res_add, "Debe confirmar registro"

    # Intercept whatsapp.send_whatsapp_message to capture sent content
    captured_messages = []
    orig_send = whatsapp.send_whatsapp_message
    
    def spy_send(phone, text):
        captured_messages.append({"phone": phone, "text": text})
        return True

    whatsapp.send_whatsapp_message = spy_send

    try:
        logger.info("--- 2. Ejecutar procesar_recordatorios_documentos (Primer envío) ---")
        enviados1 = recordatorios.procesar_recordatorios_documentos()
        logger.info(f"Cantidad de recordatorios enviados: {enviados1}")
        assert enviados1 == 1, "Debe enviar exactamente 1 recordatorio"
        assert len(captured_messages) == 1, "Debe haber capturado 1 mensaje"

        msg1 = captured_messages[0]["text"]
        logger.info(f"Mensaje WhatsApp capturado:\n{msg1}")

        FALLBACK_ERROR_MSG = "ocurrido un error procesando tu mensaje"
        assert FALLBACK_ERROR_MSG not in msg1.lower(), "ERROR: El mensaje enviado contiene un fallo de fallback genérico"
        assert "Maria Garcia" in msg1, "El mensaje debe estar personalizado con el nombre 'Maria Garcia'"
        assert "Declaración IRPF 2025" in msg1, "El mensaje debe incluir la descripción del documento"
        assert fecha_limite_cercana in msg1, "El mensaje debe incluir la fecha límite"

        # Verificar incremento de veces_recordado en DB
        docs = database.get_todos_documentos_pendientes()
        assert len(docs) == 1
        assert docs[0]["veces_recordado"] == 1, "veces_recordado debe haberse incrementado a 1"

        logger.info("--- 3. Re-ejecutar el mismo día (Prevención de duplicados) ---")
        captured_messages.clear()
        enviados2 = recordatorios.procesar_recordatorios_documentos()
        logger.info(f"Cantidad enviada en segunda ejecución del mismo día: {enviados2}")
        assert enviados2 == 0, "NO debe reenviar el recordatorio el mismo día"
        assert len(captured_messages) == 0, "No debe haber nuevos mensajes de WhatsApp"

        logger.info("--- 4. Probar documento VENCIDO (fecha límite en el pasado) ---")
        fecha_pasada = "2026-01-01"
        res_vencido = gestor_mode.procesar_comando(gestor_phone, f'/documento_pendiente {test_phone} "Escrituras antiguas" {fecha_pasada}')
        logger.info(f"Resultado /documento_pendiente vencido:\n{res_vencido}")

        captured_messages.clear()
        enviados3 = recordatorios.procesar_recordatorios_documentos()
        assert enviados3 == 0, "NO se debe enviar WhatsApp al cliente por un documento vencido"
        assert len(captured_messages) == 0

        # Verificar que el gestor ve el elemento como VENCIDO
        res_pend = gestor_mode.procesar_comando(gestor_phone, "/pendientes_documentos")
        logger.info(f"Resultado /pendientes_documentos:\n{res_pend}")
        assert "⚠️ VENCIDO" in res_pend, "El documento con fecha pasada debe aparecer etiquetado como ⚠️ VENCIDO al gestor"
        assert "Escrituras antiguas" in res_pend

        logger.info("--- 5. Probar comando /documento_recibido ---")
        # Marcar primer documento como recibido
        doc_id = docs[0]["id"]
        res_rec = gestor_mode.procesar_comando(gestor_phone, f"/documento_recibido {doc_id}")
        logger.info(f"Resultado /documento_recibido:\n{res_rec}")
        assert "marcado como RECIBIDO" in res_rec, "Debe confirmar recepción"

    finally:
        whatsapp.send_whatsapp_message = orig_send

    logger.info("🏆 ¡Fase 4.1: Recordatorios de documentación pendiente completada con ÉXITO!")
    return True

if __name__ == "__main__":
    success = test_fase4_1()
    sys.exit(0 if success else 1)
