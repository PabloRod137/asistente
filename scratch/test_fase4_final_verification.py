import os
import sys
import logging
from datetime import datetime, timedelta

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_fase4_final_verification")

def run_verification():
    import database
    import main
    import client_memory
    import gestor_mode
    import whatsapp
    from modulos import recordatorios

    database.init_db()
    test_user_phone = "34688990011"
    gestor_phone = "34600000000"
    
    # Limpieza previa de registros de prueba
    conn = database.get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM documentos_pendientes WHERE phone_number = ?", (test_user_phone,))
    c.execute("DELETE FROM plazos_fiscales WHERE phone_number = ? OR cliente = 'Cliente Sin Tel'", (test_user_phone,))
    c.execute("DELETE FROM clientes WHERE phone_number = ?", (test_user_phone,))
    conn.commit()
    conn.close()

    # Registrar cliente de prueba en CRM
    client_memory.registrar_visita(test_user_phone)
    conn = database.get_connection()
    c = conn.cursor()
    c.execute("UPDATE clientes SET nombre = 'Sofia Martin', tipo_cliente = 'activo' WHERE phone_number = ?", (test_user_phone,))
    conn.commit()
    conn.close()

    FALLBACK_ERROR_MSG = "ocurrido un error procesando tu mensaje"
    captured_messages = []
    orig_send = whatsapp.send_whatsapp_message
    
    def spy_send(phone, text):
        captured_messages.append({"phone": phone, "text": text})
        return True

    whatsapp.send_whatsapp_message = spy_send

    try:
        logger.info("================ VERIFICACIÓN 1 ================")
        logger.info("Documento pendiente con fecha cercana -> llega recordatorio real por WhatsApp con contenido coherente")
        fecha_cercana_doc = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")
        res_doc1 = gestor_mode.procesar_comando(gestor_phone, f'/documento_pendiente {test_user_phone} "Certificado de retenciones 2025" {fecha_cercana_doc}')
        assert "registrado con éxito" in res_doc1, "V1 FALLÓ: No se registró el documento"

        captured_messages.clear()
        count_doc1 = recordatorios.procesar_recordatorios_documentos()
        assert count_doc1 == 1, "V1 FALLÓ: Debe enviar 1 recordatorio"
        assert len(captured_messages) == 1, "V1 FALLÓ: Debe haberse enviado un mensaje de WhatsApp"
        msg_doc1 = captured_messages[0]["text"]
        logger.info(f"Contenido del WhatsApp enviado (V1):\n{msg_doc1}")
        assert FALLBACK_ERROR_MSG not in msg_doc1.lower(), f"V1 FALLÓ: Mensaje de error genérico detectado: {msg_doc1}"
        assert "Sofia Martin" in msg_doc1, "V1 FALLÓ: No incluye el nombre Sofia Martin"
        assert "Certificado de retenciones 2025" in msg_doc1, "V1 FALLÓ: No incluye la descripción"
        assert fecha_cercana_doc in msg_doc1, "V1 FALLÓ: No incluye la fecha límite"
        logger.info("✅ VERIFICACIÓN 1 PASADA")

        logger.info("\n================ VERIFICACIÓN 2 ================")
        logger.info("El mismo documento no genera un segundo recordatorio el mismo día")
        captured_messages.clear()
        count_doc2 = recordatorios.procesar_recordatorios_documentos()
        assert count_doc2 == 0, "V2 FALLÓ: No debe reenviar en la misma fecha"
        assert len(captured_messages) == 0, "V2 FALLÓ: No debe haber mensajes en el segundo intento del mismo día"
        logger.info("✅ VERIFICACIÓN 2 PASADA")

        logger.info("\n================ VERIFICACIÓN 3 ================")
        logger.info("Documento VENCIDO (fecha límite en el pasado) -> NO envía WhatsApp pero aparece VENCIDO al gestor")
        fecha_pasada_doc = "2026-01-10"
        gestor_mode.procesar_comando(gestor_phone, f'/documento_pendiente {test_user_phone} "Escritura vencida" {fecha_pasada_doc}')
        
        captured_messages.clear()
        count_doc3 = recordatorios.procesar_recordatorios_documentos()
        assert count_doc3 == 0, "V3 FALLÓ: No se debe enviar WhatsApp al cliente por documento vencido"
        assert len(captured_messages) == 0

        res_pend = gestor_mode.procesar_comando(gestor_phone, "/pendientes_documentos")
        logger.info(f"Resultado /pendientes_documentos (V3):\n{res_pend}")
        assert "⚠️ VENCIDO" in res_pend, "V3 FALLÓ: El documento pasado debe mostrar etiqueta VENCIDO"
        assert "Escritura vencida" in res_pend
        logger.info("✅ VERIFICACIÓN 3 PASADA")

        logger.info("\n================ VERIFICACIÓN 4 ================")
        logger.info("Plazo fiscal con teléfono asignado y fecha cercana -> llega recordatorio real por WhatsApp")
        fecha_cercana_fis = (datetime.now() + timedelta(days=5)).strftime("%Y-%m-%d")
        res_fis1 = gestor_mode.procesar_comando(gestor_phone, f'/plazo_fiscal "Modelo 200 (IS)" "Sofia Martin" {fecha_cercana_fis} {test_user_phone}')
        assert "Plazo fiscal añadido" in res_fis1, "V4 FALLÓ: No se añadió el plazo fiscal"

        captured_messages.clear()
        count_fis1 = recordatorios.procesar_recordatorios_plazos_fiscales()
        assert count_fis1 == 1, "V4 FALLÓ: Debe enviar 1 recordatorio fiscal"
        assert len(captured_messages) == 1
        msg_fis1 = captured_messages[0]["text"]
        logger.info(f"Contenido del WhatsApp enviado (V4):\n{msg_fis1}")
        assert FALLBACK_ERROR_MSG not in msg_fis1.lower(), f"V4 FALLÓ: Mensaje de error genérico detectado: {msg_fis1}"
        assert "Sofia Martin" in msg_fis1, "V4 FALLÓ: No incluye el nombre Sofia Martin"
        assert "Modelo 200 (IS)" in msg_fis1, "V4 FALLÓ: No incluye el modelo fiscal"
        assert fecha_cercana_fis in msg_fis1, "V4 FALLÓ: No incluye la fecha límite"
        logger.info("✅ VERIFICACIÓN 4 PASADA")

        logger.info("\n================ VERIFICACIÓN 5 ================")
        logger.info("El mismo plazo fiscal no se recuerda dos veces (recordatorio_enviado = 1)")
        captured_messages.clear()
        count_fis2 = recordatorios.procesar_recordatorios_plazos_fiscales()
        assert count_fis2 == 0, "V5 FALLÓ: No debe reenviar plazo fiscal ya marcado como enviado"
        assert len(captured_messages) == 0
        logger.info("✅ VERIFICACIÓN 5 PASADA")

        logger.info("\n================ VERIFICACIÓN 6 ================")
        logger.info("Plazo fiscal SIN teléfono asignado -> aparece en resumen del gestor sin enviar WhatsApp a clientes")
        gestor_mode.procesar_comando(gestor_phone, f'/plazo_fiscal "Modelo 130" "Cliente Sin Tel" {fecha_cercana_fis}')
        captured_messages.clear()
        count_fis3 = recordatorios.procesar_recordatorios_plazos_fiscales()
        assert count_fis3 == 0, "V6 FALLÓ: No debe intentar enviar WhatsApp cuando no hay teléfono"
        assert len(captured_messages) == 0
        res_plazos_gestor = gestor_mode.procesar_comando(gestor_phone, "/plazos")
        logger.info(f"Resultado /plazos del gestor (V6):\n{res_plazos_gestor}")
        assert "Modelo 130" in res_plazos_gestor and "Cliente Sin Tel" in res_plazos_gestor, "V6 FALLÓ: El plazo sin teléfono debe aparecer en el resumen del gestor"
        logger.info("✅ VERIFICACIÓN 6 PASADA")

        logger.info("\n================ VERIFICACIÓN 7 ================")
        logger.info("Verificar ausencia de hardcoding específico de LexGuardian en modulos/recordatorios.py")
        import inspect
        source_rec = inspect.getsource(recordatorios)
        assert "lexguardian" not in source_rec.lower(), "V7 FALLÓ: Encontrado 'lexguardian' en recordatorios.py"
        logger.info("✅ VERIFICACIÓN 7 PASADA")

    finally:
        whatsapp.send_whatsapp_message = orig_send

    logger.info("\n🏆 ¡LAS 7 VERIFICACIONES DE LA FASE 4 HAN PASADO CON ÉXITO ABSOLUTO!")
    return True

if __name__ == "__main__":
    success = run_verification()
    sys.exit(0 if success else 1)
