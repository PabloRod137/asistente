import os
import sys
import shutil
import asyncio
import logging
import tempfile
from datetime import datetime, timedelta

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("test_contrato_maira_claudia")

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

TEST_DIR = tempfile.mkdtemp(prefix="contrato_maira_claudia_test_")
os.environ["CONTRATO_MAIRA_CLAUDIA_TEST_DIR"] = TEST_DIR

import contrato_maira_claudia as cmc


def run_tests_sync():
    logger.info("================================================================================")
    logger.info("   PRUEBAS: MECÁNICAS DEL CONTRATO MAIRA-CLAUDIA V4 (sintéticas, sin SharePoint)")
    logger.info("================================================================================")

    # -------------------------------------------------------------------------
    # 0. Este módulo no debe tocar SharePoint/Graph bajo ninguna circunstancia
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 0: el módulo no importa nada de Graph/SharePoint ---")
    import ast
    with open(os.path.join(os.path.dirname(__file__), "..", "contrato_maira_claudia.py"), encoding="utf-8") as f:
        arbol = ast.parse(f.read())
    nombres_importados = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            nombres_importados.update(alias.name for alias in nodo.names)
        elif isinstance(nodo, ast.ImportFrom) and nodo.module:
            nombres_importados.add(nodo.module)
    assert "graph_auth" not in nombres_importados and "storage_adapter" not in nombres_importados, \
        f"Este módulo debe operar exclusivamente en local, sin ninguna dependencia de Graph/SharePoint. Imports encontrados: {nombres_importados}"
    logger.info("✅ TEST 0 superado: sin dependencias de Graph/SharePoint en el código (comprobado por AST, no por texto).")

    # -------------------------------------------------------------------------
    # 1. Crear una entrada -> paquete cerrado con manifiesto + hash externo
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 1: crear operación de entrada ---")
    op_id = cmc.crear_operacion_entrada(
        telefono_correlacion="34600001111",
        archivos=[("formulario.pdf", b"contenido de prueba del formulario")],
        tipo="documento",
    )
    paquetes = cmc._listar_todos_los_paquetes()
    encontrado = next(p for p in paquetes if p["OPERATION_ID"] == op_id)
    assert encontrado["DIRECCION"] == "MAIRA_A_CLAUDIA"
    assert encontrado["ESTADO_IDENTIDAD"] == "IDENTIDAD_PENDIENTE", "Sin cliente_id, debe quedar pendiente, nunca inventar identidad"
    assert encontrado["ESTADO"] == "READY"
    carpeta = encontrado["_carpeta"]
    assert os.path.exists(os.path.join(carpeta, "formulario.pdf"))
    assert not os.path.exists(os.path.join(carpeta, "formulario.pdf.partial")), "No debe quedar ningún .partial tras cerrar"
    assert os.path.exists(os.path.join(carpeta, "manifiesto.sha256")), "El hash debe ser un archivo externo"
    with open(os.path.join(carpeta, "manifiesto.md"), encoding="utf-8") as f:
        assert "HASH_MANIFIESTO" not in f.read(), "El manifiesto no debe contener su propio hash (autorreferencia)"
    logger.info("✅ TEST 1 superado: paquete de entrada bien formado, identidad pendiente por defecto, hash externo.")

    # -------------------------------------------------------------------------
    # 2. Entrada con cliente_id resuelto -> ESTADO_IDENTIDAD: RESUELTA
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 2: entrada con identidad ya resuelta ---")
    op_id_resuelta = cmc.crear_operacion_entrada(
        "34600002222", [("doc.pdf", b"x")], cliente_id="323", expediente_id="245",
        numero_visible_cliente="2013-001"
    )
    paquete_resuelto = next(p for p in cmc._listar_todos_los_paquetes() if p["OPERATION_ID"] == op_id_resuelta)
    assert paquete_resuelto["ESTADO_IDENTIDAD"] == "RESUELTA"
    assert paquete_resuelto["CLIENTE_ID"] == "323"
    logger.info("✅ TEST 2 superado.")

    # -------------------------------------------------------------------------
    # 3. MANIPULACIÓN: si se toca el manifiesto tras READY, se detecta y se ignora
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 3: detección de manipulación (hash no coincide) ---")
    ruta_manifiesto = os.path.join(carpeta, "manifiesto.md")
    with open(ruta_manifiesto, "a", encoding="utf-8") as f:
        f.write("CAMPO_INYECTADO: intento_de_manipulacion\n")
    paquete_manipulado = cmc._leer_paquete(carpeta)
    assert paquete_manipulado is None, "Un manifiesto modificado tras READY debe ser rechazado, no leído como válido"
    logger.info("✅ TEST 3 superado: manipulación detectada, el paquete se ignora en vez de procesarse.")

    logger.info("\n================================================================================")
    logger.info("   ✅ TESTS SÍNCRONOS (0-3) SUPERADOS")
    logger.info("================================================================================")


async def run_tests_async():
    # -------------------------------------------------------------------------
    # 4. Salida bloqueada: sin AUTORIZADO_PARA_ENTREGA
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 4: salida sin autorización queda bloqueada ---")
    salida_sin_autorizar = {
        "OPERATION_ID": "MAIRA-TEST-SALIDA-1",
        "AUTORIZADO_PARA_ENTREGA": "NO",
        "CONVERSACION_EXACTA": "34600001111",
    }
    try:
        cmc.validar_salida_para_entrega(salida_sin_autorizar)
        assert False, "Debe lanzar EntregaBloqueada"
    except cmc.EntregaBloqueada:
        pass
    logger.info("✅ TEST 4 superado.")

    # -------------------------------------------------------------------------
    # 5. Salida bloqueada: requiere validación humana pero faltan campos
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 5: falta validación humana requerida ---")
    salida_sin_validacion = {
        "OPERATION_ID": "MAIRA-TEST-SALIDA-2",
        "AUTORIZADO_PARA_ENTREGA": "SI",
        "CONVERSACION_EXACTA": "34600001111",
        "VALIDACION_HUMANA_REQUERIDA": "SI",
        # faltan VALIDACION_HUMANA_ID / AUTORIZADO_POR / AUTORIZADO_EN
    }
    try:
        cmc.validar_salida_para_entrega(salida_sin_validacion)
        assert False, "Debe bloquear sin validación humana completa"
    except cmc.EntregaBloqueada as e:
        assert "validación humana" in str(e).lower()
    logger.info("✅ TEST 5 superado: nunca entrega una respuesta jurídica/documento sin validación humana completa.")

    # -------------------------------------------------------------------------
    # 6. Salida caducada -> bloqueada
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 6: salida caducada ---")
    fecha_pasada = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    salida_caducada = {
        "OPERATION_ID": "MAIRA-TEST-SALIDA-3",
        "AUTORIZADO_PARA_ENTREGA": "SI",
        "CONVERSACION_EXACTA": "34600001111",
        "CADUCIDAD_ENTREGA": fecha_pasada,
    }
    try:
        cmc.validar_salida_para_entrega(salida_caducada)
        assert False
    except cmc.EntregaBloqueada as e:
        assert "caduc" in str(e).lower()
    logger.info("✅ TEST 6 superado.")

    # -------------------------------------------------------------------------
    # 7. Entrega correcta -> acuse ENTREGADO, y REINTENTOS: no reenvía si ya hubo éxito
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 7: entrega exitosa y no-duplicación en reintento ---")
    fecha_futura = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    salida_valida = {
        "OPERATION_ID": "MAIRA-TEST-SALIDA-4",
        "AUTORIZADO_PARA_ENTREGA": "SI",
        "CONVERSACION_EXACTA": "34600001111",
        "CADUCIDAD_ENTREGA": fecha_futura,
        "VALIDACION_HUMANA_REQUERIDA": "NO",
    }

    llamadas = []

    async def entregar_ok(paquete):
        llamadas.append(paquete["OPERATION_ID"])
        return {"exito": True, "id_proveedor": "wamid.TEST123", "estado_proveedor": "aceptado_por_api"}

    resultado_1 = await cmc.procesar_operacion_salida(salida_valida, entregar_ok)
    assert resultado_1["resultado"] == "ENTREGADO"
    assert len(llamadas) == 1

    # DUPLICADOS: reprocesar la misma operación no debe intentar entregar de nuevo
    resultado_2 = await cmc.procesar_operacion_salida(salida_valida, entregar_ok)
    assert resultado_2.get("ya_procesado") is True
    assert len(llamadas) == 1, "No debe volver a llamar a entregar_fn si ya hubo un acuse ENTREGADO"
    logger.info("✅ TEST 7 superado: entrega correcta registrada, reintento posterior no duplica el envío.")

    # -------------------------------------------------------------------------
    # 8. REINTENTOS: fallo reintentable varias veces y luego éxito
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 8: reintentos hasta éxito ---")
    intentos_hechos = []

    async def entregar_falla_dos_veces(paquete):
        intentos_hechos.append(1)
        if len(intentos_hechos) < 3:
            return {"exito": False, "reintentable": True, "estado_proveedor": "error_temporal"}
        return {"exito": True, "id_proveedor": "wamid.TEST456", "estado_proveedor": "aceptado_por_api"}

    salida_reintentos = {
        "OPERATION_ID": "MAIRA-TEST-SALIDA-5",
        "AUTORIZADO_PARA_ENTREGA": "SI",
        "CONVERSACION_EXACTA": "34600001111",
        "VALIDACION_HUMANA_REQUERIDA": "NO",
    }
    resultado_reintentos = await cmc.procesar_operacion_salida(salida_reintentos, entregar_falla_dos_veces, max_intentos=5)
    assert resultado_reintentos["resultado"] == "ENTREGADO"
    assert resultado_reintentos["intentos"] == 3
    logger.info("✅ TEST 8 superado: reintenta automáticamente hasta lograr la entrega.")

    # -------------------------------------------------------------------------
    # 9. FALLIDO_DEFINITIVO cuando el proveedor dice que no es reintentable
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 9: fallo definitivo ---")

    async def entregar_falla_definitivo(paquete):
        return {"exito": False, "reintentable": False, "estado_proveedor": "numero_invalido"}

    salida_fallo_def = {
        "OPERATION_ID": "MAIRA-TEST-SALIDA-6",
        "AUTORIZADO_PARA_ENTREGA": "SI",
        "CONVERSACION_EXACTA": "34600001111",
        "VALIDACION_HUMANA_REQUERIDA": "NO",
    }
    resultado_def = await cmc.procesar_operacion_salida(salida_fallo_def, entregar_falla_definitivo)
    assert resultado_def["resultado"] == "FALLIDO_DEFINITIVO"
    assert resultado_def["intentos"] == 1, "Un fallo no reintentable no debe seguir intentándolo"
    logger.info("✅ TEST 9 superado.")

    # -------------------------------------------------------------------------
    # 10. El acuse es un paquete NUEVO e independiente, nunca dentro de la salida
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 10: el acuse no modifica el paquete original ---")
    todos = cmc._listar_todos_los_paquetes()
    acuses = [p for p in todos if p.get("PARENT_OPERATION_ID") == "MAIRA-TEST-SALIDA-4"]
    assert len(acuses) == 1
    assert acuses[0]["OPERATION_ID"] != "MAIRA-TEST-SALIDA-4", "El acuse debe tener su propio OPERATION_ID"
    assert acuses[0]["TIPO"] == "acuse_entrega"
    assert acuses[0]["DIRECCION"] == "MAIRA_A_CLAUDIA"
    with open(os.path.join(acuses[0]["_carpeta"], "manifiesto.sha256"), encoding="utf-8") as f:
        assert len(f.read().strip()) == 64, "El acuse también debe tener su hash externo (SHA-256)"
    logger.info("✅ TEST 10 superado: acuse independiente, con su propio hash externo, sin tocar el paquete original.")

    logger.info("\n================================================================================")
    logger.info("   ✅ TODAS LAS PRUEBAS DEL CONTRATO MAIRA-CLAUDIA (SINTÉTICAS) PASARON")
    logger.info("================================================================================")


if __name__ == "__main__":
    try:
        run_tests_sync()
        asyncio.run(run_tests_async())
    finally:
        shutil.rmtree(TEST_DIR, ignore_errors=True)
