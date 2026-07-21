import os
import sys
import logging

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_fase3_4_gestor_crm")

def test_gestor_crm():
    import database
    import gestor_mode
    import client_memory
    
    database.init_db()
    test_phone = "34611223344"
    gestor_phone = "34600000000"
    
    # 1. Registrar cliente nuevo con nombre
    client_memory.registrar_visita(test_phone)
    conn = database.get_connection()
    c = conn.cursor()
    c.execute("""
        UPDATE clientes 
        SET nombre = 'Maria Garcia', nif_cif = '87654321B', tipo_cliente = 'nuevo', fecha_alta = '2026-07-21'
        WHERE phone_number = ?
    """, (test_phone,))
    conn.commit()
    conn.close()
    
    logger.info("--- 1. Probar /clientes_nuevos ---")
    res_nuevos = gestor_mode.procesar_comando(gestor_phone, "/clientes_nuevos")
    logger.info(f"Resultado de /clientes_nuevos:\n{res_nuevos}")
    assert "Maria Garcia" in res_nuevos, "Maria Garcia debe aparecer en clientes nuevos"
    assert test_phone in res_nuevos, f"{test_phone} debe aparecer en clientes nuevos"
    
    logger.info("--- 2. Probar /alta_cliente ---")
    res_alta = gestor_mode.procesar_comando(gestor_phone, f'/alta_cliente {test_phone} "EXP-2026-99" "Maria Garcia"')
    logger.info(f"Resultado de /alta_cliente: {res_alta}")
    assert "activado con éxito" in res_alta, "Debe confirmar la activación"
    assert "EXP-2026-99" in res_alta, "Debe mencionar el número de expediente"
    
    logger.info("--- 3. Probar /cliente_info ---")
    res_info = gestor_mode.procesar_comando(gestor_phone, f"/cliente_info {test_phone}")
    logger.info(f"Resultado de /cliente_info:\n{res_info}")
    assert "Maria Garcia" in res_info, "Ficha debe incluir nombre"
    assert "activo" in res_info, "Ficha debe indicar estado activo"
    assert "EXP-2026-99" in res_info, "Ficha debe indicar el expediente"
    assert "87654321B" in res_info, "Ficha debe indicar el NIF/CIF"
    
    logger.info("¡Fase 3.4: Comandos de gestor CRM completados con ÉXITO!")
    return True

if __name__ == "__main__":
    success = test_gestor_crm()
    sys.exit(0 if success else 1)
