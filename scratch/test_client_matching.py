import os
import sys
import asyncio
import logging

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("test_client_matching")

os.environ.setdefault("GEMINI_API_KEY", "mock_key")

import database
import client_matching
from modulos import alta_cliente

TEL_1 = "34600990001"
TEL_2 = "34600990002"
TEL_3 = "34600990003"


def limpiar():
    conn = database.get_connection()
    c = conn.cursor()
    for tel in (TEL_1, TEL_2, TEL_3):
        c.execute("DELETE FROM clientes WHERE phone_number = ?", (tel,))
        c.execute("DELETE FROM sesiones_activas WHERE phone_number = ?", (tel,))
    conn.commit()
    conn.close()


async def run():
    database.init_db()
    limpiar()

    logger.info("================================================================================")
    logger.info("   VERIFICACIÓN: COINCIDENCIA Y VINCULACIÓN AUTOMÁTICA CON LA LISTA DE ESPERA")
    logger.info("================================================================================")

    # -------------------------------------------------------------------------
    # TEST 0: la búsqueda directa encuentra al candidato real importado de Alberto
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 0: búsqueda directa contra los datos reales importados ---")
    candidato = client_matching.buscar_coincidencia("Alberto Berdejo Payno")
    assert candidato is not None, "Debería encontrar a BERDEJO PAYNO, ALBERTO en la lista de espera real"
    assert candidato["nombre"] == "BERDEJO PAYNO, ALBERTO"
    assert candidato["numero_expediente"] == "2013-001", f"Expediente esperado 2013-001, obtenido: {candidato['numero_expediente']}"
    logger.info(f"✅ Coincidencia encontrada: {candidato['nombre']} (expediente {candidato['numero_expediente']})")

    # Un solo nombre de pila no debe intentar buscar (demasiado ambiguo)
    assert client_matching.buscar_coincidencia("Alberto") is None, "Un único token no debería intentar buscar coincidencia"
    logger.info("✅ Un nombre de una sola palabra no dispara ninguna coincidencia (conservador por diseño).")

    # -------------------------------------------------------------------------
    # TEST 1: flujo completo por WhatsApp -> confirma -> se vincula el teléfono
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 1: alta completa con confirmación positiva ---")
    r1 = alta_cliente.iniciar_alta(TEL_1, "CHAT", "hola, buenas")
    logger.info(f"Bot: {r1}")
    assert "nombre" in r1.lower()

    r2 = await alta_cliente.gestionar_alta(TEL_1, "Alberto Berdejo Payno")
    logger.info(f"Bot: {r2}")
    assert "2013-001" in r2, "Debería proponer confirmar con el expediente real"
    assert "SÍ" in r2 or "SI" in r2.upper()

    r3 = await alta_cliente.gestionar_alta(TEL_1, "si")
    logger.info(f"Bot: {r3}")
    assert "Perfecto" in r3 and "2013-001" in r3

    cliente_final = database.get_cliente_by_phone(TEL_1)
    assert cliente_final is not None, "El cliente debería haberse creado en la tabla real"
    assert cliente_final["nombre"] == "BERDEJO PAYNO, ALBERTO"
    assert cliente_final["nif_cif"] == "72080302G", f"NIF esperado 72080302G, obtenido: {cliente_final['nif_cif']}"
    assert cliente_final["numero_expediente"] == "2013-001"
    assert cliente_final["tipo_cliente"] == "activo", "Un cliente vinculado desde la lista de espera debe quedar 'activo', no 'nuevo'"
    logger.info(f"✅ Cliente vinculado correctamente en la tabla real: {cliente_final['nombre']}, NIF {cliente_final['nif_cif']}")

    pendientes_tras = database.listar_clientes_pendientes()
    assert not any(p["numero_expediente"] == "2013-001" for p in pendientes_tras), "El pendiente promovido no debería seguir apareciendo como pendiente"
    logger.info("✅ El registro de la lista de espera ya no aparece como pendiente (promovido).")

    # -------------------------------------------------------------------------
    # TEST 2: coincidencia pero el cliente responde NO -> sigue alta normal
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 2: coincidencia rechazada -> continúa alta manual normal ---")
    alta_cliente.iniciar_alta(TEL_2, "CHAT", "hola")
    r_match = await alta_cliente.gestionar_alta(TEL_2, "Juan Antonio Berdejo Vidal")
    logger.info(f"Bot: {r_match}")
    assert "2013-002" in r_match

    r_no = await alta_cliente.gestionar_alta(TEL_2, "no")
    logger.info(f"Bot: {r_no}")
    assert "NIF" in r_no or "nif" in r_no.lower()

    r_nif = await alta_cliente.gestionar_alta(TEL_2, "omitir")
    logger.info(f"Bot: {r_nif}")
    r_motivo = await alta_cliente.gestionar_alta(TEL_2, "una consulta general")
    logger.info(f"Bot: {r_motivo}")

    cliente_2 = database.get_cliente_by_phone(TEL_2)
    assert cliente_2 is not None
    assert cliente_2["nombre"] == "Juan Antonio Berdejo Vidal", "Debe guardarse el nombre tal cual lo escribió, no el de la ficha rechazada"
    assert cliente_2["tipo_cliente"] == "nuevo", "Un alta manual normal debe quedar como 'nuevo', no 'activo'"
    logger.info("✅ Al rechazar la coincidencia, el alta sigue el camino manual normal y no mezcla los datos de otra persona.")

    # -------------------------------------------------------------------------
    # TEST 3: nombre que no coincide con nadie de la lista -> alta normal directa
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 3: nombre sin coincidencia -> alta normal directa, sin preguntar confirmación ---")
    alta_cliente.iniciar_alta(TEL_3, "CHAT", "hola")
    r_sin_match = await alta_cliente.gestionar_alta(TEL_3, "Persona Totalmente Inventada Xyz")
    logger.info(f"Bot: {r_sin_match}")
    assert "NIF" in r_sin_match or "nif" in r_sin_match.lower(), "Sin coincidencia, debe pasar directo a pedir el NIF, no una confirmación"
    logger.info("✅ Sin coincidencia en la lista de espera, sigue el flujo de alta normal sin preguntar nada raro.")

    limpiar()
    logger.info("\n================================================================================")
    logger.info("   ✅ TODAS LAS VERIFICACIONES DE COINCIDENCIA Y VINCULACIÓN PASARON CORRECTAMENTE")
    logger.info("================================================================================")


if __name__ == "__main__":
    asyncio.run(run())
