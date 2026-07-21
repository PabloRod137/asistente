import os
import sys
import logging

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_fase3_3_alta")

def test_alta_flow():
    import database
    import main
    import client_memory
    
    database.init_db()
    phone = "34655443322"
    
    def simular_mensaje(tel, msg):
        client_memory.registrar_visita(tel)
        return main.procesar_flujo_mensaje(tel, msg, "text")

    logger.info("--- 1. Enviar mensaje de saludo (FAQ) como usuario nuevo ---")
    res1 = simular_mensaje(phone, "Hola, ¿qué servicios ofrecéis?")
    logger.info(f"Respuesta a saludo: {res1[:100]}...")
    cliente1 = client_memory.get_cliente(phone)
    assert cliente1 is not None and cliente1.get("nombre") is None, "No debería haber pedido alta en el saludo"
    
    logger.info("--- 2. Enviar petición de cita (requiere identificación) ---")
    res2 = simular_mensaje(phone, "Quiero reservar una cita para asesoramiento")
    logger.info(f"Respuesta a petición de cita: {res2}")
    assert "nombre y apellidos" in res2.lower(), "Debería haber iniciado el flujo de alta solicitando nombre"
    
    logger.info("--- 3. Responder con Nombre ---")
    res3 = simular_mensaje(phone, "Carlos Santana")
    logger.info(f"Respuesta a Nombre: {res3}")
    assert "nif" in res3.lower() or "dni" in res3.lower(), "Debería haber solicitado NIF/DNI"
    
    logger.info("--- 4. Responder con NIF ---")
    res4 = simular_mensaje(phone, "12345678A")
    logger.info(f"Respuesta a NIF: {res4}")
    assert "motivo" in res4.lower(), "Debería haber solicitado el motivo"
    
    logger.info("--- 5. Responder con Motivo ---")
    res5 = simular_mensaje(phone, "Consulta fiscal para nueva SL")
    logger.info(f"Respuesta final tras alta: {res5}")
    assert "completado" in res5.lower(), "Debería confirmar el registro completado"
    
    # Verificar en SQLite
    cliente_registrado = client_memory.get_cliente(phone)
    logger.info(f"Cliente en BD tras alta: {cliente_registrado}")
    assert cliente_registrado["nombre"] == "Carlos Santana", "El nombre debe estar guardado"
    assert cliente_registrado["nif_cif"] == "12345678A", "El NIF debe estar guardado"
    assert cliente_registrado["tipo_cliente"] == "nuevo", "El estado debe ser 'nuevo'"
    
    logger.info("--- 6. Enviar SEGUNDA acción antes de revisión del gestor ---")
    res6 = simular_mensaje(phone, "Quiero pedir una factura de 500 euros para Carlos Santana CIF 12345678A")
    logger.info(f"Respuesta a segunda solicitud (factura): {res6[:100]}...")
    assert "nombre y apellidos" not in res6.lower(), "NO debe volver a pedir los datos de alta!"
    
    logger.info("¡Fase 3.3: Prueba del flujo de alta de cliente completada con ÉXITO!")
    return True

if __name__ == "__main__":
    success = test_alta_flow()
    sys.exit(0 if success else 1)
