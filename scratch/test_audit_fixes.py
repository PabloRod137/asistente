import os
import sys
import asyncio
import logging
import threading

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("test_audit_fixes")

os.environ.setdefault("GEMINI_API_KEY", "mock_key")

import database
from modulos import alta_cliente

NOMBRE_TEST = "Prueba Auditoria Duplicados"
TEL_RACE_A = "34600991001"
TEL_RACE_B = "34600991002"


def limpiar():
    conn = database.get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM clientes_importados_pendientes WHERE nombre = ?", (NOMBRE_TEST,))
    c.execute("DELETE FROM clientes WHERE phone_number IN (?, ?)", (TEL_RACE_A, TEL_RACE_B))
    conn.commit()
    conn.close()


def run():
    database.init_db()
    limpiar()

    logger.info("================================================================================")
    logger.info("   VERIFICACIÓN DE LOS ARREGLOS DE LA AUDITORÍA (crítico + alto)")
    logger.info("================================================================================")

    # -------------------------------------------------------------------------
    # FIX CRÍTICO: insertar_cliente_pendiente ya no duplica al llamarse dos veces
    # -------------------------------------------------------------------------
    logger.info("\n--- Verificando que insertar_cliente_pendiente es idempotente por nombre ---")
    id_1 = database.insertar_cliente_pendiente(NOMBRE_TEST, nif_cif="11112222A", numero_expediente="EXP-AUD-1")
    id_2 = database.insertar_cliente_pendiente(NOMBRE_TEST, nif_cif="11112222A", numero_expediente="EXP-AUD-2")
    assert id_1 == id_2, f"Debería reutilizar el mismo pendiente, obtuvo ids distintos: {id_1} vs {id_2}"

    pendientes = database.listar_clientes_pendientes()
    coincidencias = [p for p in pendientes if p["nombre"] == NOMBRE_TEST]
    assert len(coincidencias) == 1, f"Debería haber exactamente 1 pendiente con ese nombre, hay {len(coincidencias)}"
    assert coincidencias[0]["numero_expediente"] == "EXP-AUD-2", "La segunda llamada debería haber actualizado el expediente, no crear uno nuevo"
    logger.info("✅ Reejecutar la carga del mismo cliente actualiza en vez de duplicar.")

    # -------------------------------------------------------------------------
    # FIX ALTO: promover_cliente_pendiente es atómico ante concurrencia real
    # -------------------------------------------------------------------------
    logger.info("\n--- Verificando la condición de carrera en promover_cliente_pendiente (hilos reales) ---")
    resultados = []

    def intentar_promover(telefono):
        r = database.promover_cliente_pendiente(id_1, telefono)
        resultados.append((telefono, r))

    hilo_a = threading.Thread(target=intentar_promover, args=(TEL_RACE_A,))
    hilo_b = threading.Thread(target=intentar_promover, args=(TEL_RACE_B,))
    hilo_a.start()
    hilo_b.start()
    hilo_a.join()
    hilo_b.join()

    exitosos = [r for tel, r in resultados if r is not None]
    fallidos = [r for tel, r in resultados if r is None]
    assert len(exitosos) == 1, f"Debería ganar exactamente UNA de las dos peticiones concurrentes, ganaron {len(exitosos)}"
    assert len(fallidos) == 1, f"La otra debería haber sido rechazada (None), se rechazaron {len(fallidos)}"
    logger.info(f"✅ Solo una de las dos peticiones concurrentes promovió el pendiente; la otra recibió None correctamente.")

    cliente_a = database.get_cliente_by_phone(TEL_RACE_A)
    cliente_b = database.get_cliente_by_phone(TEL_RACE_B)
    creados = [c for c in (cliente_a, cliente_b) if c is not None]
    assert len(creados) == 1, f"Solo debería haberse creado UN cliente real entre los dos números, se crearon {len(creados)}"
    logger.info(f"✅ Ningún cliente duplicado: solo se creó un registro real ({creados[0]['nombre']}).")

    limpiar()
    logger.info("\n================================================================================")
    logger.info("   ✅ TODOS LOS ARREGLOS DE LA AUDITORÍA VERIFICADOS CORRECTAMENTE")
    logger.info("================================================================================")


if __name__ == "__main__":
    run()
