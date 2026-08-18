import os
import sys
import base64
import asyncio
import logging

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("test_panel")

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

os.environ.setdefault("GEMINI_API_KEY", "mock_key_para_no_llamar_a_gemini_en_este_test")

import database
import main

TEL_TEST = "34600006543"
PASSWORD_TEST = "clave_de_prueba_panel_2026"


def _auth_header(password: str) -> dict:
    token = base64.b64encode(f"maira:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _limpiar():
    conn = database.get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM conversaciones WHERE phone_number = ?", (TEL_TEST,))
    c.execute("DELETE FROM tickets_escalados WHERE phone_number = ?", (TEL_TEST,))
    c.execute("DELETE FROM documentos_puente WHERE phone_number = ?", (TEL_TEST,))
    c.execute("DELETE FROM clientes WHERE phone_number = ?", (TEL_TEST,))
    conn.commit()
    conn.close()


async def run_tests():
    logger.info("================================================================================")
    logger.info("   PRUEBAS: PANEL VISUAL (/panel)")
    logger.info("================================================================================")

    import httpx

    database.init_db()
    _limpiar()

    # -------------------------------------------------------------------------
    # 1. Sin PANEL_PASSWORD configurado -> 503, no expone nada
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 1: sin PANEL_PASSWORD configurado ---")
    os.environ.pop("PANEL_PASSWORD", None)
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/panel", headers=_auth_header("cualquiera"))
    assert resp.status_code == 503, f"Sin PANEL_PASSWORD debe responder 503, respondió {resp.status_code}"
    logger.info("✅ TEST 1 superado: sin contraseña configurada, el panel responde 503 (falla seguro).")

    os.environ["PANEL_PASSWORD"] = PASSWORD_TEST

    # -------------------------------------------------------------------------
    # 2. Sin credenciales -> 401
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 2: sin credenciales ---")
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/panel")
    assert resp.status_code == 401, f"Sin credenciales debe responder 401, respondió {resp.status_code}"
    logger.info("✅ TEST 2 superado: sin credenciales, 401.")

    # -------------------------------------------------------------------------
    # 3. Contraseña incorrecta -> 401
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 3: contraseña incorrecta ---")
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/panel", headers=_auth_header("contrasena_incorrecta"))
    assert resp.status_code == 401, f"Con contraseña incorrecta debe responder 401, respondió {resp.status_code}"
    logger.info("✅ TEST 3 superado: contraseña incorrecta, 401.")

    # -------------------------------------------------------------------------
    # 4. Contraseña correcta -> 200, con datos reales insertados reflejados en el HTML
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 4: contraseña correcta, datos reales reflejados ---")
    conn = database.get_connection()
    c = conn.cursor()
    c.execute("""
        INSERT INTO conversaciones (phone_number, inicio, ultimo_mensaje)
        VALUES (?, datetime('now'), datetime('now'))
    """, (TEL_TEST,))
    c.execute("""
        INSERT INTO tickets_escalados (phone_number, mensaje_cliente, respuesta_maira, estado)
        VALUES (?, 'necesito ayuda urgente', 'te derivo con un gestor', 'pendiente')
    """, (TEL_TEST,))
    c.execute("""
        INSERT INTO documentos_puente (phone_number, direccion, ruta_logica, nombre_archivo)
        VALUES (?, 'entrada', 'puente_claudia/test/entrada/doc_prueba_panel.pdf', 'doc_prueba_panel.pdf')
    """, (TEL_TEST,))
    conn.commit()
    conn.close()

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/panel", headers=_auth_header(PASSWORD_TEST))

    assert resp.status_code == 200, f"Con contraseña correcta debe responder 200, respondió {resp.status_code}"
    cuerpo = resp.text
    assert "Panel Maira" in cuerpo
    assert TEL_TEST in cuerpo, "El teléfono de prueba debe aparecer en la actividad reciente"
    assert "doc_prueba_panel.pdf" in cuerpo, "El documento de prueba debe aparecer en la tabla de actividad"
    logger.info("✅ TEST 4 superado: con contraseña correcta, 200 y los datos reales aparecen en el HTML.")

    logger.info("\n================================================================================")
    logger.info("   ✅ TODAS LAS PRUEBAS DEL PANEL PASARON CORRECTAMENTE")
    logger.info("================================================================================")

    _limpiar()


if __name__ == "__main__":
    asyncio.run(run_tests())
