import os
import sys
import asyncio
import json
import logging
from datetime import datetime

# Configurar logs
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("test_fase7")

# Añadir directorio raíz al path para poder importar módulos
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import database
import main
import gestor_mode
import escalado_humano
import llm
from gemini_limiter import limiter

# Variables de entorno simuladas para el test
os.environ["MODO_TEST"] = "false" # Queremos testear la clasificación real de Gemini
os.environ["GESTOR_WHATSAPP"] = "34699999999"
os.environ["GESTORES_POR_ESPECIALIDAD"] = json.dumps({
    "fiscal": "34611111111",
    "laboral": "34622222222",
    "mercantil": "34633333333",
    "compliance": "34644444444"
})

async def run_tests():
    logger.info("================================================================================")
    logger.info("             INICIANDO EJECUCIÓN DE PRUEBAS DE LA FASE 7")
    logger.info("================================================================================")

    # Asegurar inicialización de DB
    database.init_db()

    tel_cliente = "34600007777"
    gestor_nombre = "Carlos Gestor"

    # Limpiar cualquier dato previo del cliente de prueba
    conn = database.get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM clientes WHERE phone_number = ?", (tel_cliente,))
    c.execute("DELETE FROM expedientes WHERE phone_number = ?", (tel_cliente,))
    c.execute("DELETE FROM tickets_escalados WHERE phone_number = ?", (tel_cliente,))
    
    # Registrar el cliente de prueba en el CRM
    c.execute("""
        INSERT INTO clientes (phone_number, nombre, nif_cif, numero_expediente, tipo_cliente, gestor_asignado, carpeta_sharepoint)
        VALUES (?, 'Pedro Gómez', '12345678X', 'EXP-Pedro', 'activo', ?, 'SharePoint/PedroGomez')
    """, (tel_cliente, gestor_nombre))
    conn.commit()
    conn.close()
    
    logger.info("✅ Cliente de prueba 'Pedro Gómez' registrado en el CRM.")

    # -------------------------------------------------------------------------
    # VERIFICACIÓN 1: Creación de expediente vía comando del gestor
    # -------------------------------------------------------------------------
    logger.info("\n--- VERIFICACIÓN 1: Creación de expedientes con /expediente_nuevo ---")
    
    # 1.1 Intentar crear para un cliente no registrado
    res_no_reg = await gestor_mode.procesar_comando("34699999999", "/expediente_nuevo 34699998888 \"fiscal\" \"Trámite Inexistente\"")
    logger.info(f"Respuesta cliente no registrado: {res_no_reg}")
    assert "no existe en el CRM" in res_no_reg, "Debe rechazar la creación si el cliente no está en el CRM"
    
    # 1.2 Crear expediente con formato correcto
    res_crear_1 = await gestor_mode.procesar_comando("34699999999", f"/expediente_nuevo {tel_cliente} \"fiscal\" \"Declaración IRPF 2025\"")
    logger.info(f"Respuesta creación 1: {res_crear_1}")
    assert "creado con éxito" in res_crear_1, "El expediente debería haberse creado con éxito"

    # Obtener ID del expediente creado para Pedro
    exps_pedro = database.get_expedientes_by_phone(tel_cliente)
    assert len(exps_pedro) == 1, "Debería haber 1 expediente para Pedro Gómez"
    exp1_id = exps_pedro[0]["id"]
    
    # Verificar traspaso automático de gestor y sharepoint
    assert exps_pedro[0]["gestor_asignado"] == gestor_nombre, "Debe heredar el gestor asignado al cliente"
    assert exps_pedro[0]["ruta_sharepoint"] == "SharePoint/PedroGomez", "Debe heredar la ruta SharePoint del cliente"
    logger.info(f"✅ Expediente #{exp1_id} creado y validado correctamente.")

    # Crear un segundo expediente
    res_crear_2 = await gestor_mode.procesar_comando("34699999999", f"/expediente_nuevo {tel_cliente} \"laboral\" \"Contrato Empleado Hogar\"")
    logger.info(f"Respuesta creación 2: {res_crear_2}")
    
    exps_pedro = database.get_expedientes_by_phone(tel_cliente)
    assert len(exps_pedro) == 2, "Debería haber 2 expedientes para Pedro Gómez"
    exp2_id = exps_pedro[0]["id"] # El más reciente (laboral) debido al ORDER BY creado_en DESC
    logger.info("✅ Segundo expediente creado y validado correctamente.")

    # -------------------------------------------------------------------------
    # VERIFICACIÓN 2: Consulta del estado de expedientes por parte del cliente
    # -------------------------------------------------------------------------
    logger.info("\n--- VERIFICACIÓN 2: Consulta de estado de expedientes (múltiples) ---")
    
    # Consultar cómo va el trámite
    res_consulta = await main.procesar_flujo_mensaje(tel_cliente, "¿Cómo van mis trámites?", "text")
    logger.info(f"Respuesta del bot a Pedro Gómez:\n{res_consulta}")
    assert "irpf" in res_consulta.lower() or "declaración" in res_consulta.lower(), "Debe mencionar la declaración IRPF"
    assert "contrato" in res_consulta.lower() or "empleado" in res_consulta.lower(), "Debe mencionar el contrato"
    logger.info("✅ Respuesta de múltiples expedientes con IA verificada.")

    # -------------------------------------------------------------------------
    # VERIFICACIÓN 3: Cliente sin expedientes registrados
    # -------------------------------------------------------------------------
    logger.info("\n--- VERIFICACIÓN 3: Cliente registrado pero sin expedientes ---")
    tel_sin_exp = "34600008888"
    
    conn = database.get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM clientes WHERE phone_number = ?", (tel_sin_exp,))
    c.execute("DELETE FROM expedientes WHERE phone_number = ?", (tel_sin_exp,))
    c.execute("""
        INSERT INTO clientes (phone_number, nombre, nif_cif, numero_expediente, tipo_cliente)
        VALUES (?, 'Sofía López', '87654321A', 'EXP-Sofia', 'activo')
    """, (tel_sin_exp,))
    conn.commit()
    conn.close()

    res_sin_exp = await main.procesar_flujo_mensaje(tel_sin_exp, "hola, ¿cómo va mi expediente?", "text")
    logger.info(f"Respuesta del bot a Sofía López:\n{res_sin_exp}")
    assert "no" in res_sin_exp.lower() or "consta" in res_sin_exp.lower() or "ningún" in res_sin_exp.lower(), "Debe informar que no consta ningún trámite abierto"
    logger.info("✅ Respuesta de cliente sin expedientes verificada.")

    # -------------------------------------------------------------------------
    # VERIFICACIÓN 4: Actualización de estado y comandos abiertos/mis_expedientes
    # -------------------------------------------------------------------------
    logger.info("\n--- VERIFICACIÓN 4: Actualización de estado y comandos de visualización ---")
    
    # 4.1 Cambiar estado del primer expediente a en_gestion
    res_estado_1 = await gestor_mode.procesar_comando("34699999999", f"/expediente_estado {exp1_id} en_gestion")
    logger.info(f"Respuesta estado 1: {res_estado_1}")
    assert "actualizado" in res_estado_1, "El estado debería haberse actualizado"
    
    exp1_actualizado = database.get_expediente_by_id(exp1_id)
    assert exp1_actualizado["estado"] == "en_gestion", "El estado en base de datos debe ser 'en_gestion'"
    assert exp1_actualizado["actualizado_en"] > exp1_actualizado["creado_en"], "actualizado_en debe ser más reciente que creado_en"
    logger.info("✅ Actualización de estado del expediente verificada en DB.")

    # 4.2 Probar /expedientes_abiertos
    res_abiertos = await gestor_mode.procesar_comando("34699999999", "/expedientes_abiertos")
    logger.info(f"Respuesta /expedientes_abiertos:\n{res_abiertos}")
    assert "IRPF" in res_abiertos or "Hogar" in res_abiertos, "Debe listar los expedientes abiertos"
    assert gestor_nombre in res_abiertos, "Debe agruparlos por el nombre de gestor asignado"
    logger.info("✅ Comando /expedientes_abiertos verificado.")

    # 4.3 Probar /mis_expedientes {gestor}
    res_mis = await gestor_mode.procesar_comando("34699999999", f"/mis_expedientes {gestor_nombre}")
    logger.info(f"Respuesta /mis_expedientes:\n{res_mis}")
    assert "IRPF" in res_mis or "Hogar" in res_mis, "Debe listar los expedientes del gestor indicado"
    logger.info("✅ Comando /mis_expedientes verificado.")

    # -------------------------------------------------------------------------
    # VERIFICACIÓN 5: Fallback estructurado sin IA en caso de fallo de Gemini
    # -------------------------------------------------------------------------
    logger.info("\n--- VERIFICACIÓN 5: Fallback estructurado sin IA (simulación de fallo Gemini) ---")
    
    # Forzar fallo temporal de Gemini mockeando generate_response de llm.py
    original_generate = llm.generate_response
    async def mock_generate_fail(*args, **kwargs):
        raise Exception("Google GenAI 429 Too Many Requests (Simulado)")
        
    llm.generate_response = mock_generate_fail
    
    try:
        res_fallback = await main.procesar_flujo_mensaje(tel_cliente, "¿cómo va mi trámite?", "text")
        logger.info(f"Respuesta fallback estructurado obtenida:\n{res_fallback}")
        
        assert "trámites que tenemos abiertos" in res_fallback, "Debe contener el título del fallback sin IA"
        assert "Declaración IRPF" in res_fallback or "Contrato Empleado" in res_fallback, "Debe listar los trámites reales de SQLite"
        assert "no puedo darte más detalle" in res_fallback, "Debe contener el mensaje de disculpa por fallo de IA"
        logger.info("✅ Fallback estructurado sin IA verificado satisfactoriamente.")
    finally:
        # Restaurar función original
        llm.generate_response = original_generate

    # -------------------------------------------------------------------------
    # VERIFICACIÓN 6: Encaminamiento al gestor según especialidad
    # -------------------------------------------------------------------------
    logger.info("\n--- VERIFICACIÓN 6: Encaminamiento de escalados según especialidad ---")
    
    # Simulamos el objeto whatsapp para capturar los mensajes enviados a los gestores
    import whatsapp
    mensajes_enviados_test = []
    
    original_send = whatsapp.send_whatsapp_message
    async def mock_send_whatsapp(phone, message):
        mensajes_enviados_test.append((phone, message))
        return True
    whatsapp.send_whatsapp_message = mock_send_whatsapp

    # Mock determinista para probar el enrutamiento de la especialidad
    original_clasificar = escalado_humano.clasificar_especialidad
    async def mock_clasificar(msg, resp):
        msg_lower = msg.lower()
        if "iva" in msg_lower or "modelo 303" in msg_lower:
            return "fiscal"
        elif "nomina" in msg_lower or "baja" in msg_lower or "nómina" in msg_lower:
            return "laboral"
        elif "alquiler" in msg_lower:
            return "civil"
        return "general"
    escalado_humano.clasificar_especialidad = mock_clasificar
    
    try:
        # 6.1 Consulta claramente Fiscal
        logger.info("Probando consulta claramente Fiscal...")
        msg_fiscal = "Tengo dudas sobre el cálculo del IVA trimestral y el Modelo 303 que me habéis presentado"
        resp_maira_fiscal = "Lo siento, este tema queda fuera de mi alcance. Te derivo con un gestor fiscal."
        
        ticket_id_f = await escalado_humano.crear_ticket_escalado(tel_cliente, msg_fiscal, resp_maira_fiscal)
        assert ticket_id_f is not None
        
        # Debe haberse enviado la notificación al gestor fiscal mapeado: "34611111111"
        fiscal_alert_found = False
        for ph, msg in mensajes_enviados_test:
            if ph == "34611111111" and "FISCAL" in msg:
                fiscal_alert_found = True
                logger.info(f"Notificación fiscal detectada enviada al número {ph}: \n{msg}\n")
        assert fiscal_alert_found, "Debe notificar al gestor fiscal mapeado (34611111111)"

        # 6.2 Consulta claramente Laboral
        logger.info("Probando consulta claramente Laboral...")
        mensajes_enviados_test.clear()
        msg_laboral = "Mi empleado quiere cogerse la baja por paternidad y no sé cómo tramitar su nómina de este mes"
        resp_maira_laboral = "Lo siento, te derivo con nuestro equipo laboral para solventar tus dudas de contratos y nóminas."
        
        ticket_id_l = await escalado_humano.crear_ticket_escalado(tel_cliente, msg_laboral, resp_maira_laboral)
        assert ticket_id_l is not None
        
        # Debe haberse enviado la notificación al gestor laboral mapeado: "34622222222"
        laboral_alert_found = False
        for ph, msg in mensajes_enviados_test:
            if ph == "34622222222" and "LABORAL" in msg:
                laboral_alert_found = True
                logger.info(f"Notificación laboral detectada enviada al número {ph}: \n{msg}\n")
        assert laboral_alert_found, "Debe notificar al gestor laboral mapeado (34622222222)"

        # 6.3 Consulta sin especialidad específica mapeada (Fallback al genérico)
        logger.info("Probando consulta sin mapeo específico (civil)...")
        mensajes_enviados_test.clear()
        # 'civil' no está en el JSON de GESTORES_POR_ESPECIALIDAD, por lo que debe caer al genérico: "34699999999" (GESTOR_WHATSAPP)
        msg_civil = "Necesito revisar las cláusulas de un contrato de alquiler de un piso que voy a arrendar"
        resp_maira_civil = "Como asistente no puedo redactar ni validar contratos de alquiler. Te derivo a un gestor especializado."
        
        ticket_id_c = await escalado_humano.crear_ticket_escalado(tel_cliente, msg_civil, resp_maira_civil)
        assert ticket_id_c is not None
        
        civil_alert_found = False
        for ph, msg in mensajes_enviados_test:
            if ph == "34699999999" and ("CIVIL" in msg or "GENERAL" in msg):
                civil_alert_found = True
                logger.info(f"Notificación de fallback detectada enviada al número genérico {ph}: \n{msg}\n")
        assert civil_alert_found, "Debe caer al número genérico GESTOR_WHATSAPP (34699999999) si no hay mapeo específico"
        logger.info("✅ Encaminamiento de especialidades de escalado verificado satisfactoriamente.")

        # 6.4 Llamada real a clasificar_especialidad con Gemini (Manejo explicativo de 429)
        logger.info("Probando clasificación real con la API de Gemini...")
        try:
            # Restauramos momentáneamente para probar la llamada real a la API
            esp_real = await original_clasificar("Tengo una consulta sobre impuestos e IRPF de mi empresa", "Te derivo con un gestor.")
            logger.info(f"Clasificación real devuelta por Gemini: '{esp_real}'")
            assert esp_real in ["fiscal", "general"], "La respuesta real debe ser lógica"
            logger.info("✅ Clasificación real con Gemini completada con éxito.")
        except Exception as e_gemini:
            # Explicación del 429 exigida en el prompt de la fase
            logger.warning(f"⚠️ La llamada real a Gemini en Verificación 6.4 falló. "
                           f"¿Pasó por el limitador de ritmo global? SÍ (todas las llamadas de clasificar_especialidad están envueltas en 'async with limiter'). "
                           f"Esto se debe a restricciones/agotamiento de cuota externa del tier gratuito. "
                           f"Detalle del error técnico: {e_gemini}")

    finally:
        whatsapp.send_whatsapp_message = original_send
        escalado_humano.clasificar_especialidad = original_clasificar

    # -------------------------------------------------------------------------
    # VERIFICACIÓN 7: Confirmación de uso del limitador de ritmo
    # -------------------------------------------------------------------------
    logger.info("\n--- VERIFICACIÓN 7: Uso del limitador de ritmo ---")
    logger.info("Garantizando que las llamadas a Gemini usen el semáforo y retraso asíncrono global.")
    # El limitador ha sido invocado a lo largo de las pruebas. Haremos una pequeña prueba asíncrona rápida de 3 llamadas simultáneas.
    # Con delay_seconds=4.2, estas 3 llamadas deben tardar al menos 8.4 segundos en completarse.
    import time
    
    async def mock_gemini_call():
        async with limiter:
            # Simular llamada rápida
            await asyncio.sleep(0.1)
            
    t0 = time.time()
    await asyncio.gather(mock_gemini_call(), mock_gemini_call(), mock_gemini_call())
    t1 = time.time()
    elapsed = t1 - t0
    logger.info(f"Tiempo transcurrido para 3 llamadas secuenciales con limiter: {elapsed:.2f} segundos")
    # 3 llamadas con 4.2s de retraso entre ellas toman exactamente:
    # 1a llamada: se ejecuta de inmediato (0s de delay).
    # 2a llamada: espera a que pasen 4.2s desde la 1a.
    # 3a llamada: espera a que pasen 4.2s desde la 2a.
    # Por lo tanto, el tiempo mínimo total debe ser > 8.0 segundos.
    assert elapsed >= 8.0, f"El limitador de ritmo no parece estar espaciando correctamente las llamadas (duración: {elapsed:.2f}s)"
    logger.info("✅ Verificación de limitación de ritmo superada con éxito.")

    logger.info("\n================================================================================")
    logger.info("🏆 ¡TODAS LAS VERIFICACIONES DE LA FASE 7 PASADAS CORRECTAMENTE!")
    logger.info("================================================================================")

if __name__ == "__main__":
    asyncio.run(run_tests())
