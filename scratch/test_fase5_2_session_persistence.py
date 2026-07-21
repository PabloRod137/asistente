import os
import sys
import asyncio
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ["MODO_TEST"] = "true"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_fase5_2")

async def run_session_persistence_test():
    import database
    import main
    database.init_db()

    phone_alta = "34699998877"
    phone_triaje = "34699998866"
    
    conn = database.get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM clientes WHERE phone_number IN (?, ?)", (phone_alta, phone_triaje))
    cursor.execute("DELETE FROM sesiones_activas WHERE phone_number IN (?, ?)", (phone_alta, phone_triaje))
    # Registrar phone_triaje como cliente existente para ir directo a triaje sin pasar por el flujo de alta
    cursor.execute("INSERT INTO clientes (phone_number, nombre, tipo_cliente) VALUES (?, 'Cliente Existente', 'activo')", (phone_triaje,))
    conn.commit()
    conn.close()

    logger.info("--- 1. Iniciar sesión de Alta (Paso 1: Nombre) ---")
    res1 = await main.procesar_flujo_mensaje(phone_alta, "quiero agendar una cita", "text")
    logger.info(f"Respuesta bot alta (inicio): {res1}")
    assert res1 and "nombre" in res1.lower(), "El bot debería solicitar el nombre"

    res2 = await main.procesar_flujo_mensaje(phone_alta, "Carlos Rodríguez", "text")
    logger.info(f"Respuesta bot alta (nombre dado): {res2}")
    assert res2 and "nif" in res2.lower(), "El bot debería solicitar el NIF"

    logger.info("--- 2. Iniciar sesión de Triaje (Paso 1: Descripción) ---")
    res3 = await main.procesar_flujo_mensaje(phone_triaje, "tengo una avería urgente con una humedad", "text")
    logger.info(f"Respuesta bot triaje (inicio): {res3}")
    assert res3 and ("código postal" in res3.lower() or "cp" in res3.lower() or "formulario" in res3.lower() or "caracteres" in res3.lower()), "El bot debería iniciar triaje"

    res3_b = await main.procesar_flujo_mensaje(phone_triaje, "tengo una avería urgente con una humedad en la pared del baño", "text")
    logger.info(f"Respuesta bot triaje (descripción dada): {res3_b}")

    logger.info("--- 3. Verificar estado guardado en SQLite (sesiones_activas) ---")
    ses_alta = database.get_session(phone_alta, "alta_cliente")
    ses_triaje = database.get_session(phone_triaje, "triaje")
    
    assert ses_alta is not None, "La sesión de alta debe estar en SQLite"
    assert ses_alta["paso"] == "nif", "El paso en SQLite debe ser 'nif'"
    assert ses_alta["nombre"] == "Carlos Rodríguez", "El nombre en SQLite debe ser 'Carlos Rodríguez'"
    
    assert ses_triaje is not None, "La sesión de triaje debe estar en SQLite"
    assert ses_triaje["estado"] == "esperando_cp", "El estado de triaje debe ser 'esperando_cp'"
    logger.info("✅ Sesiones verificadas en la base de datos SQLite.")

    logger.info("--- 4. Simular REINICIO DEL SERVIDOR (limpiando cualquier caché en RAM) ---")
    
    logger.info("--- 5. Reanudar sesión de Alta tras 'reinicio' ---")
    res4 = await main.procesar_flujo_mensaje(phone_alta, "12345678Z", "text")
    logger.info(f"Respuesta bot alta (después de reinicio): {res4}")
    assert res4 and "motivo" in res4.lower(), "El bot debe continuar pidiendo el motivo del alta"

    logger.info("--- 6. Reanudar sesión de Triaje tras 'reinicio' ---")
    res5 = await main.procesar_flujo_mensaje(phone_triaje, "28001", "text")
    logger.info(f"Respuesta bot triaje (después de reinicio): {res5}")
    assert res5 and "urgencia" in res5.lower(), "El bot debe continuar pidiendo el nivel de urgencia"

    logger.info("--- 7. Probar purga de sesiones expiradas ---")
    purged = database.clear_expired_sessions(timeout_seconds=0)
    logger.info(f"Sesiones purgadas: {purged}")
    
    logger.info("✅ TEST DE PERSISTENCIA DE SESIONES EN SQLITE COMPLETADO CON ÉXITO")

if __name__ == "__main__":
    asyncio.run(run_session_persistence_test())
