import os
import sys
import logging
from datetime import datetime, timedelta

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_fase4_2_plazos_fiscales")

def test_fase4_2():
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
    c.execute("DELETE FROM plazos_fiscales WHERE phone_number = ? OR cliente = 'Empresa Sin Tel'", (test_phone,))
    c.execute("DELETE FROM clientes WHERE phone_number = ?", (test_phone,))
    conn.commit()
    conn.close()

    # Register client Carlos Garcia
    client_memory.registrar_visita(test_phone)
    conn = database.get_connection()
    c = conn.cursor()
    c.execute("UPDATE clientes SET nombre = 'Carlos Garcia', tipo_cliente = 'activo' WHERE phone_number = ?", (test_phone,))
    conn.commit()
    conn.close()

    logger.info("--- 1. Probar comando /plazo_fiscal con teléfono y sin teléfono ---")
    fecha_limite_cercana = (datetime.now() + timedelta(days=5)).strftime("%Y-%m-%d")
    
    # Plazo fiscal CON teléfono
    res_add1 = gestor_mode.procesar_comando(gestor_phone, f'/plazo_fiscal "Modelo 303 (IVA)" "Carlos Garcia" {fecha_limite_cercana} {test_phone}')
    logger.info(f"Resultado /plazo_fiscal con teléfono:\n{res_add1}")
    assert "Plazo fiscal añadido" in res_add1 and test_phone in res_add1, "Debe añadir plazo asociando el teléfono"

    # Plazo fiscal SIN teléfono
    res_add2 = gestor_mode.procesar_comando(gestor_phone, f'/plazo_fiscal "Modelo 111 (Retenciones)" "Empresa Sin Tel" {fecha_limite_cercana}')
    logger.info(f"Resultado /plazo_fiscal sin teléfono:\n{res_add2}")
    assert "Plazo fiscal añadido" in res_add2 and "Asociado a cliente" not in res_add2, "Debe añadir plazo sin asociar teléfono"

    # Intercept whatsapp.send_whatsapp_message
    captured_messages = []
    orig_send = whatsapp.send_whatsapp_message
    
    def spy_send(phone, text):
        captured_messages.append({"phone": phone, "text": text})
        return True

    whatsapp.send_whatsapp_message = spy_send

    try:
        logger.info("--- 2. Ejecutar procesar_recordatorios_plazos_fiscales ---")
        enviados1 = recordatorios.procesar_recordatorios_plazos_fiscales()
        logger.info(f"Cantidad de recordatorios enviados a clientes: {enviados1}")
        assert enviados1 == 1, "Debe enviar exactamente 1 recordatorio al cliente que tiene teléfono"
        assert len(captured_messages) == 1

        msg1 = captured_messages[0]["text"]
        logger.info(f"Mensaje WhatsApp capturado:\n{msg1}")

        FALLBACK_ERROR_MSG = "ocurrido un error procesando tu mensaje"
        assert FALLBACK_ERROR_MSG not in msg1.lower(), "ERROR: El mensaje contiene error de fallback genérico"
        assert "Carlos Garcia" in msg1, "El mensaje debe estar personalizado con 'Carlos Garcia'"
        assert "Modelo 303 (IVA)" in msg1, "El mensaje debe indicar el modelo fiscal"
        assert fecha_limite_cercana in msg1, "El mensaje debe indicar la fecha límite"

        # Verificar que recordatorio_enviado pasó a 1
        plazos = database.get_plazos_fiscales_a_recordar_cliente(dias_antes=7)
        assert len(plazos) == 0, "No debe quedar el plazo como pendiente de recordar en el mismo margen"

        logger.info("--- 3. Re-ejecución para verificar no duplicación ---")
        captured_messages.clear()
        enviados2 = recordatorios.procesar_recordatorios_plazos_fiscales()
        logger.info(f"Cantidad enviada en segunda ejecución: {enviados2}")
        assert enviados2 == 0, "NO debe reenviar el recordatorio fiscal de nuevo"
        assert len(captured_messages) == 0

        logger.info("--- 4. Verificar consulta de plazos generales de gestor (/plazos) ---")
        res_plazos = gestor_mode.procesar_comando(gestor_phone, "/plazos")
        logger.info(f"Resultado /plazos:\n{res_plazos}")
        assert "Modelo 303" in res_plazos and "Modelo 111" in res_plazos, "Ambos plazos deben ser visibles en el resumen del gestor"

    finally:
        whatsapp.send_whatsapp_message = orig_send

    logger.info("🏆 ¡Fase 4.2: Recordatorios de plazos fiscales a clientes completados con ÉXITO!")
    return True

if __name__ == "__main__":
    success = test_fase4_2()
    sys.exit(0 if success else 1)
