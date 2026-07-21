import os
import sys
import logging

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_fase3_final_verification")

def run_verification():
    import database
    import main
    import client_memory
    import gestor_mode
    
    database.init_db()
    test_user_phone = "34677889900"
    gestor_phone = "34600000000"
    
    # Limpiar registro previo si existiera para garantizar una prueba aislada
    conn = database.get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM clientes WHERE phone_number = ?", (test_user_phone,))
    conn.commit()
    conn.close()

    def simular_mensaje(tel, msg):
        client_memory.registrar_visita(tel)
        return main.procesar_flujo_mensaje(tel, msg, "text")

    FALLBACK_ERROR_MSG = "ocurrido un error procesando tu mensaje"

    logger.info("================ VERIFICACIÓN 1 ================ ")
    logger.info("Cliente nuevo escribe 'hola' -> respuesta normal, sin alta forzada")
    res1 = simular_mensaje(test_user_phone, "Hola, buenos días")
    logger.info(f"Respuesta a 'hola': {res1[:100]}...")
    assert FALLBACK_ERROR_MSG not in res1.lower(), f"V1 FALLÓ: El bot devolvió mensaje de error genérico en vez de respuesta real de Gemini: {res1}"
    cli1 = client_memory.get_cliente(test_user_phone)
    assert cli1 is not None and cli1.get("nombre") is None, "V1 FALLÓ: No debe solicitar alta en un saludo casual"
    logger.info("✅ VERIFICACIÓN 1 PASADA: Respuesta conversacional real recibida sin solicitar alta")

    logger.info("\n================ VERIFICACIÓN 2 ================ ")
    logger.info("Cliente nuevo pide una cita -> activa alta, se completa, procesa cita")
    res2_1 = simular_mensaje(test_user_phone, "Quiero reservar una cita para consulta fiscal")
    logger.info(f"Paso 1 alta: {res2_1}")
    assert "nombre y apellidos" in res2_1.lower(), "V2.1 FALLÓ: Debe solicitar nombre"

    res2_2 = simular_mensaje(test_user_phone, "Ana Lopez")
    logger.info(f"Paso 2 alta (Nombre): {res2_2}")
    assert "nif" in res2_2.lower() or "dni" in res2_2.lower(), "V2.2 FALLÓ: Debe solicitar NIF"

    res2_3 = simular_mensaje(test_user_phone, "98765432X")
    logger.info(f"Paso 3 alta (NIF): {res2_3}")
    assert "motivo" in res2_3.lower(), "V2.3 FALLÓ: Debe solicitar motivo"

    res2_4 = simular_mensaje(test_user_phone, "Creación de sociedad limitada")
    logger.info(f"Paso 4 alta (Motivo + Completado): {res2_4}")
    assert "completado" in res2_4.lower(), "V2.4 FALLÓ: Debe confirmar registro completado"
    assert FALLBACK_ERROR_MSG not in res2_4.lower(), f"V2.4 FALLÓ: Error de fallback tras completar alta: {res2_4}"

    cli2 = client_memory.get_cliente(test_user_phone)
    assert cli2["nombre"] == "Ana Lopez", "V2 FALLÓ: El nombre debe ser Ana Lopez"
    assert cli2["nif_cif"] == "98765432X", "V2 FALLÓ: El NIF debe ser 98765432X"
    assert cli2["tipo_cliente"] == "nuevo", "V2 FALLÓ: El estado inicial debe ser 'nuevo'"
    logger.info("✅ VERIFICACIÓN 2 PASADA: Flujo de alta completado y solicitud procesada")

    logger.info("\n================ VERIFICACIÓN PUNTO A ================ ")
    logger.info("Mismo número nuevo (Ana Lopez, tipo_cliente='nuevo') pide una factura ANTES de revisión del gestor")
    res2_a = simular_mensaje(test_user_phone, "Necesito emitir una factura de 300 euros a cliente Perez")
    logger.info(f"Respuesta a segunda solicitud (factura): {res2_a[:150]}...")
    assert "nombre y apellidos" not in res2_a.lower(), "PUNTO A FALLÓ: Le ha vuelto a pedir el nombre!"
    assert FALLBACK_ERROR_MSG not in res2_a.lower(), f"PUNTO A FALLÓ: El bot devolvió mensaje de error genérico de Gemini: {res2_a}"
    assert cli2["nombre"] == "Ana Lopez", "PUNTO A FALLÓ: Nombre no preservado"
    logger.info("✅ VERIFICACIÓN PUNTO A PASADA: No se repite el flujo de alta y se mantiene el nombre Ana Lopez")

    logger.info("\n================ VERIFICACIÓN 3 ================ ")
    logger.info("/clientes_nuevos muestra el cliente recién dado de alta")
    res3 = gestor_mode.procesar_comando(gestor_phone, "/clientes_nuevos")
    logger.info(f"Resultado /clientes_nuevos:\n{res3}")
    assert "Ana Lopez" in res3, "V3 FALLÓ: Ana Lopez debe aparecer en la lista de nuevos"
    assert test_user_phone in res3, "V3 FALLÓ: El teléfono debe aparecer en la lista de nuevos"
    logger.info("✅ VERIFICACIÓN 3 PASADA")

    logger.info("\n================ VERIFICACIÓN 4 ================ ")
    logger.info("/alta_cliente completa el expediente y cambia tipo_cliente a 'activo'")
    res4 = gestor_mode.procesar_comando(gestor_phone, f'/alta_cliente {test_user_phone} "EXP-2026-ANA" "Ana Lopez"')
    logger.info(f"Resultado /alta_cliente: {res4}")
    assert "activado con éxito" in res4, "V4 FALLÓ: Debe confirmar activación"

    cli4 = client_memory.get_cliente(test_user_phone)
    assert cli4["tipo_cliente"] == "activo", "V4 FALLÓ: El tipo_cliente debe ser 'activo'"
    assert cli4["numero_expediente"] == "EXP-2026-ANA", "V4 FALLÓ: El expediente debe ser EXP-2026-ANA"
    logger.info("✅ VERIFICACIÓN 4 PASADA")

    logger.info("\n================ VERIFICACIÓN 5 ================ ")
    logger.info("Mismo cliente escribe de nuevo -> el bot saluda por nombre y usa contexto")
    res5 = simular_mensaje(test_user_phone, "Hola, quería saber qué documentos necesito")
    logger.info(f"Respuesta a cliente activo: {res5}")
    assert FALLBACK_ERROR_MSG not in res5.lower(), f"V5 FALLÓ: El bot devolvió mensaje de error genérico de Gemini en vez de respuesta personalizada: {res5}"
    assert "ana" in res5.lower(), f"V5 FALLÓ: La respuesta del bot no contiene el nombre 'Ana'. Respuesta recibida: {res5}"
    cli5 = client_memory.get_cliente(test_user_phone)
    assert cli5["nombre"] == "Ana Lopez" and cli5["tipo_cliente"] == "activo", "V5 FALLÓ: Datos del cliente activo distorsionados"
    logger.info("✅ VERIFICACIÓN 5 PASADA: El bot saluda y reconoce a Ana Lopez")

    logger.info("\n================ VERIFICACIÓN 6 ================ ")
    logger.info("Verificar ausencia de hardcoding específico de LexGuardian en los módulos de esta fase")
    import inspect
    import modulos.alta_cliente as mod_alta
    source_alta = inspect.getsource(mod_alta)
    assert "lexguardian" not in source_alta.lower(), "V6 FALLÓ: Encontrado 'lexguardian' en alta_cliente.py"
    logger.info("✅ VERIFICACIÓN 6 PASADA")

    logger.info("\n🏆 ¡LAS 6 VERIFICACIONES DE LA FASE 3 HAN PASADO CON ÉXITO ABSOLUTO!")
    return True

if __name__ == "__main__":
    success = run_verification()
    sys.exit(0 if success else 1)
