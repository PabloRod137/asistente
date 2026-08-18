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


NOMBRE_PENDIENTE_TEST = "Cliente Pendiente Panel Prueba"


def _limpiar():
    conn = database.get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM conversaciones WHERE phone_number = ?", (TEL_TEST,))
    c.execute("DELETE FROM tickets_escalados WHERE phone_number = ?", (TEL_TEST,))
    c.execute("DELETE FROM documentos_puente WHERE phone_number = ?", (TEL_TEST,))
    c.execute("DELETE FROM messages WHERE phone_number = ?", (TEL_TEST,))
    c.execute("DELETE FROM expedientes WHERE phone_number = ?", (TEL_TEST,))
    c.execute("DELETE FROM capturas_estructuradas WHERE phone_number = ?", (TEL_TEST,))
    c.execute("DELETE FROM clientes WHERE phone_number = ?", (TEL_TEST,))
    c.execute("DELETE FROM clientes_importados_pendientes WHERE nombre = ?", (NOMBRE_PENDIENTE_TEST,))
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

    # -------------------------------------------------------------------------
    # 5. Datos ricos para las páginas de detalle: cliente, mensajes, expediente, captura
    # -------------------------------------------------------------------------
    conn = database.get_connection()
    c = conn.cursor()
    c.execute("""
        INSERT INTO clientes (phone_number, nombre, tipo_cliente, numero_expediente, primera_visita, ultima_visita, total_conversaciones)
        VALUES (?, 'Cliente Panel Prueba', 'nuevo', '2026-777', datetime('now'), datetime('now'), 2)
    """, (TEL_TEST,))
    c.execute("INSERT INTO messages (phone_number, role, content) VALUES (?, 'user', 'hola, tengo una duda fiscal')", (TEL_TEST,))
    c.execute("INSERT INTO messages (phone_number, role, content) VALUES (?, 'assistant', 'claro, cuéntame')", (TEL_TEST,))
    c.execute("""
        INSERT INTO expedientes (phone_number, tipo, titulo, estado)
        VALUES (?, 'fiscal', 'Consulta IVA trimestral', 'en_gestion')
    """, (TEL_TEST,))
    c.execute("""
        INSERT INTO capturas_estructuradas (phone_number, canal, cliente_probable, area_probable, asunto, urgencia, confianza, mensaje_original, revisado)
        VALUES (?, 'whatsapp_texto', 'Cliente Panel Prueba', 'fiscal', 'duda sobre IVA', 'media', 80, 'hola, tengo una duda fiscal', 0)
    """, (TEL_TEST,))
    c.execute("""
        INSERT INTO clientes_importados_pendientes (nombre, numero_expediente, tipo_cliente)
        VALUES (?, '2026-888', 'activo')
    """, (NOMBRE_PENDIENTE_TEST,))
    conn.commit()
    conn.close()

    # -------------------------------------------------------------------------
    # 6. Lista de conversaciones + detalle de una conversación
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 6: /panel/conversaciones y /panel/conversacion/{tel} ---")
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp_lista = await client.get("/panel/conversaciones", headers=_auth_header(PASSWORD_TEST))
        resp_detalle = await client.get(f"/panel/conversacion/{TEL_TEST}", headers=_auth_header(PASSWORD_TEST))

    assert resp_lista.status_code == 200
    assert TEL_TEST in resp_lista.text
    assert resp_detalle.status_code == 200
    assert "hola, tengo una duda fiscal" in resp_detalle.text, "Debe mostrar el contenido real de los mensajes"
    assert "claro, cuéntame" in resp_detalle.text
    assert "Cliente Panel Prueba" in resp_detalle.text, "Debe mostrar la ficha del cliente si existe"
    logger.info("✅ TEST 6 superado: lista de conversaciones y detalle con mensajes reales.")

    # -------------------------------------------------------------------------
    # 7. Lista de clientes (con filtro) + ficha de cliente
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 7: /panel/clientes(+filtro) y /panel/cliente/{tel} ---")
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp_todos = await client.get("/panel/clientes", headers=_auth_header(PASSWORD_TEST))
        resp_nuevos = await client.get("/panel/clientes?tipo=nuevo", headers=_auth_header(PASSWORD_TEST))
        resp_ficha = await client.get(f"/panel/cliente/{TEL_TEST}", headers=_auth_header(PASSWORD_TEST))
        resp_404 = await client.get("/panel/cliente/34600000000_no_existe", headers=_auth_header(PASSWORD_TEST))

    assert resp_todos.status_code == 200 and "Cliente Panel Prueba" in resp_todos.text
    assert resp_nuevos.status_code == 200 and TEL_TEST in resp_nuevos.text
    assert resp_ficha.status_code == 200
    assert "2026-777" in resp_ficha.text, "Debe mostrar el expediente principal del cliente"
    assert "Consulta IVA trimestral" in resp_ficha.text, "Debe listar los expedientes reales del cliente"
    assert resp_404.status_code == 404, "Un teléfono sin cliente dado de alta debe devolver 404, no una página vacía"
    logger.info("✅ TEST 7 superado: lista filtrable de clientes y ficha con expedientes reales; 404 si no existe.")

    # -------------------------------------------------------------------------
    # 8. Capturas estructuradas y escalados (con filtro)
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 8: /panel/capturas(+filtro) y /panel/escalados(+filtro) ---")
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp_capturas = await client.get("/panel/capturas?estado=pendientes", headers=_auth_header(PASSWORD_TEST))
        resp_escalados = await client.get("/panel/escalados", headers=_auth_header(PASSWORD_TEST))

    assert resp_capturas.status_code == 200 and "duda sobre IVA" in resp_capturas.text
    assert resp_escalados.status_code == 200 and "necesito ayuda urgente" in resp_escalados.text
    logger.info("✅ TEST 8 superado: capturas y escalados muestran datos reales, filtros aplican.")

    # -------------------------------------------------------------------------
    # 9. Documentos completos y pendientes de teléfono
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 9: /panel/documentos y /panel/pendientes_telefono ---")
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp_docs = await client.get("/panel/documentos", headers=_auth_header(PASSWORD_TEST))
        resp_pend = await client.get("/panel/pendientes_telefono", headers=_auth_header(PASSWORD_TEST))

    assert resp_docs.status_code == 200 and "doc_prueba_panel.pdf" in resp_docs.text
    assert resp_pend.status_code == 200 and NOMBRE_PENDIENTE_TEST in resp_pend.text
    logger.info("✅ TEST 9 superado: documentos completos y lista de pendientes de teléfono.")

    logger.info("\n================================================================================")
    logger.info("   ✅ TODAS LAS PRUEBAS DEL PANEL PASARON CORRECTAMENTE")
    logger.info("================================================================================")

    _limpiar()


if __name__ == "__main__":
    asyncio.run(run_tests())
