import os
import sys
import asyncio
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("test_captura_estructurada")

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv()

import database
import captura_estructurada
import gestor_mode

TEL_TEST = "34600001234"
GESTOR_TEST = "34699999999"
os.environ["GESTOR_WHATSAPP"] = GESTOR_TEST


async def run_tests():
    logger.info("================================================================================")
    logger.info("       INICIANDO PRUEBAS: CAPTURA ESTRUCTURADA UNIVERSAL (FASE 8.1)")
    logger.info("================================================================================")

    database.init_db()

    conn = database.get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM capturas_estructuradas WHERE phone_number = ?", (TEL_TEST,))
    conn.commit()
    conn.close()

    # -------------------------------------------------------------------------
    # 1. Mensaje informativo -> debería producir campos rellenos y confianza alta
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 1: mensaje con información suficiente ---")
    mensaje_1 = (
        "Hola, soy Alberto de la Comunidad Castilla 87. Se nos ha inundado el garaje, "
        "necesitamos que alguien contacte con el seguro y con un fontanero urgentemente. "
        "Ya he hecho fotos de los daños."
    )
    resultado_1 = await captura_estructurada.generar_captura_estructurada(TEL_TEST, mensaje_1, "whatsapp_texto")
    logger.info(f"Resultado 1: {resultado_1}")
    assert resultado_1 is not None, "Debe devolver un resultado para un mensaje válido"
    for campo in captura_estructurada.CAMPOS_CAPTURA:
        assert campo in resultado_1, f"Falta el campo '{campo}' en el resultado"
    assert resultado_1["urgencia"] is not None, "Debería inferir algún nivel de urgencia"
    logger.info("✅ TEST 1 superado: estructura completa con los 9 campos.")

    # -------------------------------------------------------------------------
    # 2. Verificar persistencia en base de datos
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 2: persistencia en capturas_estructuradas ---")
    pendientes = database.get_capturas_pendientes(limit=20)
    encontrada = next((p for p in pendientes if p["phone_number"] == TEL_TEST), None)
    assert encontrada is not None, "La captura debe quedar persistida y pendiente de revisión"
    assert encontrada["canal"] == "whatsapp_texto"
    captura_id = encontrada["id"]
    logger.info(f"✅ TEST 2 superado: captura #{captura_id} persistida correctamente.")

    # -------------------------------------------------------------------------
    # 3. Mensaje vago -> no debe inventar datos (nulls permitidos)
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 3: mensaje vago, sin inventar datos ---")
    resultado_3 = await captura_estructurada.generar_captura_estructurada(TEL_TEST, "hola", "whatsapp_texto")
    logger.info(f"Resultado 3: {resultado_3}")
    assert resultado_3 is not None, "Debe devolver un JSON válido incluso con poca información"
    logger.info("✅ TEST 3 superado: no lanza excepción con mensajes vagos.")

    # -------------------------------------------------------------------------
    # 4. Comando de gestor /capturas_pendientes
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 4: comando /capturas_pendientes ---")
    respuesta_gestor = await gestor_mode.procesar_comando(GESTOR_TEST, "/capturas_pendientes")
    logger.info(f"Respuesta gestor: {respuesta_gestor}")
    assert f"#{captura_id}" in respuesta_gestor, "El comando debe listar la captura recién creada"
    assert TEL_TEST in respuesta_gestor
    logger.info("✅ TEST 4 superado: /capturas_pendientes lista la captura.")

    # -------------------------------------------------------------------------
    # 5. Comando de gestor /captura_revisada {id}
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 5: comando /captura_revisada ---")
    respuesta_revisada = await gestor_mode.procesar_comando(GESTOR_TEST, f"/captura_revisada {captura_id}")
    logger.info(f"Respuesta revisión: {respuesta_revisada}")
    assert "revisada" in respuesta_revisada.lower()

    pendientes_tras_revision = database.get_capturas_pendientes(limit=20)
    sigue_pendiente = any(p["id"] == captura_id for p in pendientes_tras_revision)
    assert not sigue_pendiente, "La captura ya no debe aparecer como pendiente tras marcarla revisada"
    logger.info("✅ TEST 5 superado: /captura_revisada retira la captura de pendientes.")

    # -------------------------------------------------------------------------
    # 6. Enriquecimiento: teléfono ya conocido -> sustituye el nombre/expediente de Gemini
    #    por los datos reales de la ficha del cliente (prueba directa, sin llamar a Gemini)
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 6: enriquecimiento con cliente real por teléfono ---")
    TEL_CLIENTE_REAL = "34600009999"
    conn = database.get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM clientes WHERE phone_number = ?", (TEL_CLIENTE_REAL,))
    c.execute("""
        INSERT INTO clientes (phone_number, nombre, tipo_cliente, numero_expediente, primera_visita, ultima_visita, total_conversaciones)
        VALUES (?, 'Marta Fernandez Ruiz', 'activo', '2026-045', datetime('now'), datetime('now'), 1)
    """, (TEL_CLIENTE_REAL,))
    conn.commit()
    conn.close()

    datos_gemini_simulados = {
        "cliente_probable": "una tal Marta", "area_probable": "fiscal", "asunto": "duda sobre IVA",
        "urgencia": "baja", "solicitud": "informacion", "documentos_mencionados": None,
        "servicio_sugerido": "consulta fiscal", "expediente_probable": None, "confianza": 60
    }
    enriquecido = captura_estructurada._enriquecer_con_datos_reales(TEL_CLIENTE_REAL, datos_gemini_simulados)
    assert enriquecido["cliente_probable"] == "Marta Fernandez Ruiz", "Debe sustituir el nombre por el real de la ficha del cliente"
    assert enriquecido["expediente_probable"] == "2026-045", "Debe rellenar el expediente real cuando Gemini no dio ninguno"
    assert enriquecido["asunto"] == "duda sobre IVA", "No debe tocar los campos que no dependen de la identidad"
    logger.info("✅ TEST 6 superado: teléfono conocido sustituye cliente/expediente por los datos reales.")

    # -------------------------------------------------------------------------
    # 7. Enriquecimiento: teléfono desconocido, pero el nombre coincide sin ambigüedad
    #    con la lista de espera de clientes reales sin teléfono asignado
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 7: enriquecimiento con coincidencia en la lista de espera ---")
    TEL_DESCONOCIDO = "34600008888"
    conn = database.get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM clientes WHERE phone_number = ?", (TEL_DESCONOCIDO,))
    c.execute("DELETE FROM clientes_importados_pendientes WHERE nombre = ?", ("Roberto Gimenez Castro",))
    c.execute("""
        INSERT INTO clientes_importados_pendientes (nombre, numero_expediente, tipo_cliente)
        VALUES ('Roberto Gimenez Castro', '2026-099', 'activo')
    """)
    conn.commit()
    conn.close()

    datos_gemini_simulados_2 = {
        "cliente_probable": "Roberto Gimenez", "area_probable": "laboral", "asunto": "baja voluntaria",
        "urgencia": "media", "solicitud": "tramitar baja", "documentos_mencionados": None,
        "servicio_sugerido": "baja voluntaria", "expediente_probable": None, "confianza": 70
    }
    enriquecido_2 = captura_estructurada._enriquecer_con_datos_reales(TEL_DESCONOCIDO, datos_gemini_simulados_2)
    assert enriquecido_2["cliente_probable"] == "Roberto Gimenez Castro", "Debe completar el nombre con el de la lista de espera"
    assert enriquecido_2["expediente_probable"] == "2026-099", "Debe rellenar el expediente del candidato de la lista de espera"
    logger.info("✅ TEST 7 superado: coincidencia sin ambigüedad en la lista de espera enriquece la captura.")

    # -------------------------------------------------------------------------
    # 8. Enriquecimiento: sin teléfono conocido ni coincidencia -> se deja tal cual (sin inventar)
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 8: sin coincidencia, no se toca nada ---")
    datos_sin_match = {
        "cliente_probable": "Persona Totalmente Desconocida", "area_probable": None, "asunto": "consulta",
        "urgencia": None, "solicitud": None, "documentos_mencionados": None,
        "servicio_sugerido": None, "expediente_probable": None, "confianza": 30
    }
    enriquecido_3 = captura_estructurada._enriquecer_con_datos_reales("34600007777", datos_sin_match)
    assert enriquecido_3["cliente_probable"] == "Persona Totalmente Desconocida", "Sin coincidencia real, no debe inventar ni tocar el nombre"
    assert enriquecido_3["expediente_probable"] is None
    logger.info("✅ TEST 8 superado: sin coincidencia real, la captura no se modifica (no inventa datos).")

    logger.info("\n================================================================================")
    logger.info("       ✅ TODAS LAS PRUEBAS DE CAPTURA ESTRUCTURADA PASARON CORRECTAMENTE")
    logger.info("================================================================================")

    # Limpieza final
    conn = database.get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM capturas_estructuradas WHERE phone_number = ?", (TEL_TEST,))
    c.execute("DELETE FROM clientes WHERE phone_number IN (?, ?)", (TEL_CLIENTE_REAL, TEL_DESCONOCIDO))
    c.execute("DELETE FROM clientes_importados_pendientes WHERE nombre = ?", ("Roberto Gimenez Castro",))
    conn.commit()
    conn.close()


if __name__ == "__main__":
    asyncio.run(run_tests())
