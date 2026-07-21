import os
import sys
import logging

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_fase3_2_detection")

def test_detection():
    import database
    import client_memory
    
    database.init_db()
    test_phone = "34699001122"
    
    logger.info("--- 1. Probando registrar_visita para cliente nuevo ---")
    client_memory.registrar_visita(test_phone)
    cliente = client_memory.get_cliente(test_phone)
    logger.info(f"Cliente inicial registrado: {cliente}")
    assert cliente is not None, "El cliente debería existir en memoria"
    assert cliente["tipo_cliente"] == "nuevo", "El tipo_cliente inicial debe ser 'nuevo'"
    assert cliente["nombre"] is None, "El nombre debe ser None para visitante nuevo"
    
    logger.info("--- 2. Actualizando datos de cliente activo ---")
    database.activar_cliente(test_phone, "EXP-TEST-99", nombre_opcional="Laura Gomez", gestor_asignado="Pablo")
    
    cliente_activo = client_memory.get_cliente(test_phone)
    logger.info(f"Cliente tras activación: {cliente_activo}")
    assert cliente_activo["tipo_cliente"] == "activo", "El tipo_cliente debe ser 'activo'"
    assert cliente_activo["nombre"] == "Laura Gomez", "El nombre debe coincidir"
    assert cliente_activo["numero_expediente"] == "EXP-TEST-99", "El expediente debe coincidir"
    
    logger.info("¡Fase 3.2: Prueba de detección y memoria de clientes completada con ÉXITO!")
    return True

if __name__ == "__main__":
    success = test_detection()
    sys.exit(0 if success else 1)
