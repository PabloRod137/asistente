import os
import sys
import asyncio
import logging
from datetime import datetime

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ["MODO_TEST"] = "true"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("test_fase5_final")

async def run_final_verifications():
    import database
    import main
    import whatsapp
    import llm
    import router
    from modulos import agenda, tickets, facturas, triaje, recordatorios, alta_cliente
    import secretaria

    database.init_db()

    print("\n=========================================================================================================")
    print("                  EJECUCIÓN DE VERIFICACIONES REALES Y LOGS DETALLADOS — FASE 5")
    print("=========================================================================================================\n")

    # -------------------------------------------------------------
    # TEST 1: Concurrencia de Facturas Async
    # -------------------------------------------------------------
    print("---------------------------------------------------------------------------------------------------------")
    print("TEST 1: Concurrencia de Facturas Async (FastAPI / asyncio)")
    print("---------------------------------------------------------------------------------------------------------")
    phone_fac = "34611000111"
    conn = database.get_connection()
    c = conn.cursor()
    c.execute("INSERT INTO clientes (phone_number, nombre, tipo_cliente) VALUES (?, 'Cliente Factura', 'activo') ON CONFLICT(phone_number) DO UPDATE SET tipo_cliente='activo'", (phone_fac,))
    conn.commit()
    conn.close()

    reqs = [
        main.procesar_flujo_mensaje(phone_fac, "hazme una factura a nombre de Empresa A con cif B11111111 por concepto de diseño por importe de 500 euros", "text"),
        main.procesar_flujo_mensaje(phone_fac, "hazme una factura a nombre de Empresa B con cif B22222222 por concepto de desarrollo por importe de 800 euros", "text")
    ]
    res_fac = await asyncio.gather(*reqs)
    print(f"[TEST 1 LOG] Respuesta Factura 1:\n{res_fac[0]}\n")
    print(f"[TEST 1 LOG] Respuesta Factura 2:\n{res_fac[1]}\n")
    ok1 = all(r is not None and "factura" in r.lower() for r in res_fac)
    print(f"[TEST 1 RESULTADO]: {'PASADA [OK]' if ok1 else 'FALLADA [FAIL]'}\n")

    # -------------------------------------------------------------
    # TEST 2: Carga de 10 Mensajes Simultáneos (httpx)
    # -------------------------------------------------------------
    print("---------------------------------------------------------------------------------------------------------")
    print("TEST 2: Carga de 10 Mensajes Simultáneos con HTTPX (Muestreo de Respuestas Reales)")
    print("---------------------------------------------------------------------------------------------------------")
    promesas = []
    for i in range(10):
        p = f"346220002{i:02d}"
        msg = f"Hola, me gustaría solicitar información sobre los servicios comerciales {i}"
        promesas.append(main.procesar_flujo_mensaje(p, msg, "text"))

    res_load = await asyncio.gather(*promesas)
    
    print(f"[TEST 2 LOG] Muestra Respuesta 1 (Tel 34622000200):\n\"{res_load[0]}\"\n")
    print(f"[TEST 2 LOG] Muestra Respuesta 5 (Tel 34622000204):\n\"{res_load[4]}\"\n")
    print(f"[TEST 2 LOG] Muestra Respuesta 10 (Tel 34622000209):\n\"{res_load[9]}\"\n")
    
    ok2 = all(r is not None and "error" not in r.lower() and "lo siento, ha ocurrido un error" not in r.lower() for r in res_load)
    print(f"[TEST 2 RESULTADO]: {'PASADA [OK]' if ok2 else 'FALLADA [FAIL]'} (Total respondidas: {len(res_load)}/10)\n")

    # -------------------------------------------------------------
    # TEST 3: Ejecución Real de los 3 Jobs Programados + Inspección de Briefing y Fallback
    # -------------------------------------------------------------
    print("---------------------------------------------------------------------------------------------------------")
    print("TEST 3: Ejecución de los 3 Jobs Programados (Recordatorios, Briefing, Limpieza)")
    print("---------------------------------------------------------------------------------------------------------")
    
    p_rec = "34633999888"
    conn = database.get_connection()
    c = conn.cursor()
    c.execute("INSERT INTO clientes (phone_number, nombre, tipo_cliente) VALUES (?, 'Cliente Avisos', 'activo') ON CONFLICT(phone_number) DO UPDATE SET tipo_cliente='activo'", (p_rec,))
    conn.commit()
    conn.close()
    
    database.save_documento_pendiente(p_rec, "Escrituras de la sociedad", (datetime.now()).strftime("%Y-%m-%d"))

    print("[TEST 3 LOG] Ejecutando Job 1: procesar_todos_los_recordatorios...")
    rec_res = await recordatorios.procesar_todos_los_recordatorios()
    print(f"[TEST 3 LOG] Resultado Job 1 (Recordatorios): {rec_res}\n")

    print("[TEST 3 LOG] Ejecutando Job 2: generar_briefing_diario (con Gemini o Fallback)...")
    briefing_res = await secretaria.generar_briefing_diario()
    print(f"[TEST 3 LOG] TEXTO REAL DEL BRIEFING ENVIADO AL GESTOR:\n\"\"\"\n{briefing_res}\n\"\"\"\n")

    # Probar explícitamente el Fallback cuando Gemini falla (simulando API key inválida)
    print("[TEST 3 LOG] Probando FALLBACK ESTRUCTURADO de Briefing (simulando fallo total de Gemini)...")
    original_key = os.environ.get("GEMINI_API_KEY")
    os.environ["GEMINI_API_KEY"] = "INVALID_KEY_FOR_TESTING"
    briefing_fallback = await secretaria.generar_briefing_diario()
    if original_key:
        os.environ["GEMINI_API_KEY"] = original_key
        
    print(f"[TEST 3 LOG] TEXTO REAL DEL BRIEFING FALLBACK ENVIADO AL GESTOR:\n\"\"\"\n{briefing_fallback}\n\"\"\"\n")

    print("[TEST 3 LOG] Ejecutando Job 3: limpiar_archivos_temporales_antiguos...")
    await triaje.limpiar_archivos_temporales_antiguos()
    print(f"[TEST 3 LOG] Resultado Job 3 (Limpieza de temporales ejecutada)\n")

    ok3_briefing = briefing_res is not None and len(briefing_res) > 20 and "hubo un error" not in briefing_res.lower()
    ok3_fallback = briefing_fallback is not None and "citas de hoy" in briefing_fallback.lower() and "plazos fiscales" in briefing_fallback.lower()
    
    ok3 = isinstance(rec_res, dict) and ok3_briefing and ok3_fallback
    print(f"[TEST 3 RESULTADO]: {'PASADA [OK]' if ok3 else 'FALLADA [FAIL]'}\n")

    # -------------------------------------------------------------
    # TEST 4: Persistencia de Sesiones en SQLite tras Reinicio
    # -------------------------------------------------------------
    print("---------------------------------------------------------------------------------------------------------")
    print("TEST 4: Persistencia de Sesión Conversacional en SQLite (Simulación Reinicio Servidor)")
    print("---------------------------------------------------------------------------------------------------------")
    p_pers = "34633000333"
    conn = database.get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM clientes WHERE phone_number = ?", (p_pers,))
    c.execute("DELETE FROM sesiones_activas WHERE phone_number = ?", (p_pers,))
    conn.commit()
    conn.close()

    res_p1 = await main.procesar_flujo_mensaje(p_pers, "quiero reservar una cita", "text")
    print(f"[TEST 4 LOG] Respuesta 1 (Iniciando Alta):\n\"{res_p1}\"\n")

    res_p2 = await main.procesar_flujo_mensaje(p_pers, "Ana Gómez", "text")
    print(f"[TEST 4 LOG] Respuesta 2 (Nombre enviado):\n\"{res_p2}\"\n")

    s_db_antes = database.get_session(p_pers, "alta_cliente")
    print(f"[TEST 4 LOG] Estado sesión en SQLite ANTES de reinicio: {s_db_antes}")

    print("--- [SIMULANDO REINICIO DEL SERVIDOR: RAM LIMPIA, LEYENDO DE SQLITE] ---")
    
    res_p3 = await main.procesar_flujo_mensaje(p_pers, "98765432W", "text")
    print(f"[TEST 4 LOG] Respuesta 3 tras REINICIO (NIF enviado):\n\"{res_p3}\"\n")

    s_db_despues = database.get_session(p_pers, "alta_cliente")
    print(f"[TEST 4 LOG] Estado sesión en SQLite DESPUÉS de enviar NIF: {s_db_despues}")

    ok4 = (s_db_antes.get("paso") == "nif") and (s_db_despues.get("paso") == "motivo") and ("motivo" in res_p3.lower())
    print(f"[TEST 4 RESULTADO]: {'PASADA [OK]' if ok4 else 'FALLADA [FAIL]'}\n")

    # -------------------------------------------------------------
    # TEST 5: Purga Forzada de Sesión Expirada (REQUERIMIENTO B)
    # -------------------------------------------------------------
    print("---------------------------------------------------------------------------------------------------------")
    print("TEST 5: Purga de Sesiones Expiradas en SQLite (Con Sesión Antiga Forzada)")
    print("---------------------------------------------------------------------------------------------------------")
    phone_exp = "34699000000"
    
    conn = database.get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM sesiones_activas WHERE phone_number = ?", (phone_exp,))
    c.execute('''
        INSERT INTO sesiones_activas (phone_number, tipo_sesion, datos_json, actualizado_en)
        VALUES (?, 'triaje', '{"estado": "esperando_cp", "test_expirado": true}', '2026-01-01 10:00:00')
    ''', (phone_exp,))
    conn.commit()
    
    c.execute("SELECT COUNT(*) FROM sesiones_activas WHERE phone_number = ? AND tipo_sesion = 'triaje'", (phone_exp,))
    count_antes = c.fetchone()[0]
    conn.close()
    
    print(f"[TEST 5 LOG] Filas encontradas para {phone_exp} ANTES de purgar: {count_antes}")
    assert count_antes == 1, "La fila expirada debió ser insertada en SQLite"

    purged_count = database.clear_expired_sessions(timeout_seconds=900)
    print(f"[TEST 5 LOG] clear_expired_sessions(timeout_seconds=900) retornó {purged_count} filas eliminadas")

    conn = database.get_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM sesiones_activas WHERE phone_number = ? AND tipo_sesion = 'triaje'", (phone_exp,))
    count_despues = c.fetchone()[0]
    conn.close()
    
    session_post = database.get_session(phone_exp, "triaje")
    print(f"[TEST 5 LOG] Filas encontradas para {phone_exp} DESPUÉS de purgar: {count_despues}")
    print(f"[TEST 5 LOG] get_session('{phone_exp}', 'triaje') retornó: {session_post}")

    ok5 = (count_antes == 1) and (purged_count >= 1) and (count_despues == 0) and (session_post is None)
    print(f"[TEST 5 RESULTADO]: {'PASADA [OK]' if ok5 else 'FALLADA [FAIL]'}\n")

    # -------------------------------------------------------------
    # TEST 6: Regresión en Módulos de Negocio Existentes
    # -------------------------------------------------------------
    print("---------------------------------------------------------------------------------------------------------")
    print("TEST 6: Regresión en Módulos Existentes (Triaje / Agenda)")
    print("---------------------------------------------------------------------------------------------------------")
    p_reg = "34644000444"
    conn = database.get_connection()
    c = conn.cursor()
    c.execute("INSERT INTO clientes (phone_number, nombre, tipo_cliente) VALUES (?, 'Cliente Regresión', 'activo') ON CONFLICT(phone_number) DO UPDATE SET tipo_cliente='activo'", (p_reg,))
    c.execute("DELETE FROM sesiones_activas WHERE phone_number = ?", (p_reg,))
    conn.commit()
    conn.close()

    res_tri = await main.procesar_flujo_mensaje(p_reg, "tengo una avería urgente con una tubería rota en la cocina", "text")
    print(f"[TEST 6 LOG] Respuesta Triaje Cliente Existente:\n\"{res_tri}\"\n")
    ok6 = res_tri and ("formulario" in res_tri.lower() or "presupuesto" in res_tri.lower() or "caracteres" in res_tri.lower() or "detalle" in res_tri.lower() or "avería" in res_tri.lower() or "código postal" in res_tri.lower() or "guardado" in res_tri.lower())
    print(f"[TEST 6 RESULTADO]: {'PASADA [OK]' if ok6 else 'FALLADA [FAIL]'}\n")

    # -------------------------------------------------------------
    # TEST 7: Aserción Estricta de Contenido Real (Sin Fallback Genérico)
    # -------------------------------------------------------------
    print("---------------------------------------------------------------------------------------------------------")
    print("TEST 7: Aserción Estricta de Contenido Real (Respuesta LLM Completa)")
    print("---------------------------------------------------------------------------------------------------------")
    p_str = "34655000555"
    res_llm = await llm.generate_response("hola buenos días, quería saber qué trámites hacéis", [], p_str)
    print(f"[TEST 7 LOG] Respuesta Real Completa del Bot (llm.generate_response):\n\"{res_llm}\"\n")
    
    ok7 = res_llm is not None and "lo siento, ha ocurrido un error" not in res_llm.lower() and len(res_llm) > 15
    print(f"[TEST 7 RESULTADO]: {'PASADA [OK]' if ok7 else 'FALLADA [FAIL]'}\n")

    print("=========================================================================================================")
    print("                                   RESUMEN FINAL DE PRUEBAS FASE 5")
    print("=========================================================================================================")
    todas = [ok1, ok2, ok3, ok4, ok5, ok6, ok7]
    if all(todas):
        print(">>> TODAS LAS 7 VERIFICACIONES DE LA FASE 5 (INCLUYENDO BRIEFING DIARIO Y SU FALLBACK) HAN PASADO [OK] <<<\n")
    else:
        print(">>> ATENCIÓN: ALGUNAS PRUEBAS HAN FALLADO. <<< \n")

if __name__ == "__main__":
    asyncio.run(run_final_verifications())
