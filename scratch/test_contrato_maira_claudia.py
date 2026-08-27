import os
import sys
import shutil
import asyncio
import logging
import tempfile
import threading
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
    # 1b. READY (sellado local) no es "accesible" hasta la confirmación real del mecanismo
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 1b: ventana de latencia entre READY y confirmación real ---")
    assert cmc.paquete_accesible(op_id) is False, "Sin confirmación del mecanismo real, el paquete no debe considerarse accesible"
    cmc.confirmar_sellado_real(op_id)
    assert cmc.paquete_accesible(op_id) is True
    logger.info("✅ TEST 1b superado: la confirmación real es un paso explícito y separado, nunca automático.")

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

    # -------------------------------------------------------------------------
    # 11. Resolución de identidad: UNICO devuelve CLIENTE_ID, como operación aparte
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 11: resolución de identidad UNICO ---")
    op_entrada = cmc.crear_operacion_entrada("34600009999", [("doc.pdf", b"x")])
    cmc.crear_resolucion_identidad(op_entrada, "UNICO", cliente_id="323", expediente_id="245")
    resolucion = cmc.leer_resolucion_identidad(op_entrada)
    assert resolucion is not None
    assert resolucion["RESULTADO"] == "UNICO"
    assert resolucion["CLIENTE_ID"] == "323"
    assert resolucion["OPERATION_ID"] != op_entrada, "La resolución debe ser una operación nueva, no editar la original"
    logger.info("✅ TEST 11 superado.")

    # -------------------------------------------------------------------------
    # 12. AMBIGUO/NO_ENCONTRADO no llevan CLIENTE_ID -- Maira nunca elige por su cuenta
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 12: resultado AMBIGUO no lleva identidad ---")
    op_entrada_2 = cmc.crear_operacion_entrada("34600008888", [("doc.pdf", b"y")])
    cmc.crear_resolucion_identidad(op_entrada_2, "AMBIGUO")
    resolucion_2 = cmc.leer_resolucion_identidad(op_entrada_2)
    assert resolucion_2["RESULTADO"] == "AMBIGUO"
    assert not resolucion_2["CLIENTE_ID"], "Un resultado AMBIGUO no debe traer un CLIENTE_ID adivinado"

    try:
        cmc.crear_resolucion_identidad("MAIRA-OTRA-OP", "AMBIGUO", cliente_id="999")
        assert False, "No debe permitir CLIENTE_ID junto a un resultado que no sea UNICO"
    except ValueError:
        pass
    logger.info("✅ TEST 12 superado: sin correspondencia inequívoca, nunca se inventa una identidad.")

    # -------------------------------------------------------------------------
    # 13. Sin caché: Maira no debe recordar nada entre operaciones distintas del mismo teléfono
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 13: sin asociación permanente teléfono→cliente ---")
    # Un segundo mensaje del MISMO teléfono es una operación totalmente nueva y no arrastra
    # ninguna resolución previa -- el contrato exige resolver de nuevo cada vez.
    op_entrada_repetida = cmc.crear_operacion_entrada("34600009999", [("doc2.pdf", b"z")])
    resolucion_repetida = cmc.leer_resolucion_identidad(op_entrada_repetida)
    assert resolucion_repetida is None, "Una operación nueva no debe heredar la resolución de una operación anterior del mismo teléfono"
    assert not hasattr(cmc, "_cache_identidad") and not hasattr(cmc, "_telefono_a_cliente"), \
        "El módulo no debe tener ninguna estructura de caché teléfono->cliente"
    logger.info("✅ TEST 13 superado: cada operación se resuelve de cero, sin memoria entre teléfonos.")

    # -------------------------------------------------------------------------
    # 14. Registro de eventos: cada transición es un archivo independiente, no un log compartido
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 14: eventos de estado independientes, no un archivo compartido ---")
    op_id_estado = cmc.crear_operacion_entrada("34600007777", [("doc.pdf", b"contenido")])
    assert cmc.obtener_estado_actual(op_id_estado) is None, "Sin eventos todavía, no debe haber estado"

    ev1 = cmc.registrar_evento_estado(op_id_estado, "01_ORDENES_ACEPTADAS", actor="Claudia", comando_id="cmd-001", motivo="recibido")
    assert cmc.obtener_estado_actual(op_id_estado) == "01_ORDENES_ACEPTADAS"

    ev2 = cmc.registrar_evento_estado(op_id_estado, "04_ENTREGADAS", actor="Claudia", comando_id="cmd-002", motivo="procesado")
    assert cmc.obtener_estado_actual(op_id_estado) == "04_ENTREGADAS"

    carpeta_op = cmc._carpeta_estados_operacion(op_id_estado)
    archivos = os.listdir(carpeta_op)
    assert sum(1 for a in archivos if a.endswith(".json")) == 2, "Cada transición debe ser un archivo .json independiente"
    assert sum(1 for a in archivos if a.endswith(".sha256")) == 2, "Cada evento debe tener su propio hash externo"

    paquete_original = next(p for p in cmc._listar_todos_los_paquetes() if p["OPERATION_ID"] == op_id_estado)
    assert paquete_original["ESTADO"] == "READY", "El paquete original nunca cambia, solo se leen eventos aparte"
    logger.info("✅ TEST 14 superado: cada transición es un archivo independiente; el paquete original nunca se toca.")

    # -------------------------------------------------------------------------
    # 15. Cadena de hashes encadenada correctamente, con SECUENCIA monotónica
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 15: verificación de la cadena de eventos ---")
    assert cmc.verificar_cadena_eventos(op_id_estado) is True

    eventos = cmc._leer_todos_los_eventos(op_id_estado)
    assert eventos[0]["SECUENCIA"] == "0" and eventos[1]["SECUENCIA"] == "1", "La secuencia debe ser monótona empezando en 0"
    assert eventos[0]["HASH_EVENTO_ANTERIOR"] == "", "El primer evento no tiene predecesor"
    assert eventos[1]["HASH_EVENTO_ANTERIOR"] == eventos[0]["_hash_evento"], "El segundo evento debe encadenar el hash del primero"
    logger.info("✅ TEST 15 superado: secuencia monótona y cadena de hashes correctamente encadenada.")

    # -------------------------------------------------------------------------
    # 16. MANIPULACIÓN de un evento intermedio: se detecta y bloquea la proyección del estado
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 16: manipulación de un evento bloquea la proyección ---")
    ruta_primer_evento = eventos[0]["_ruta"]
    with open(ruta_primer_evento, "a", encoding="utf-8") as f:
        f.write("CAMPO_INYECTADO: manipulado\n")

    assert cmc.verificar_cadena_eventos(op_id_estado) is False, "Con un evento manipulado, la cadena ya no es verificable"
    try:
        cmc.obtener_estado_actual(op_id_estado)
        assert False, "obtener_estado_actual debe bloquear (lanzar excepción), nunca devolver un estado no fiable"
    except cmc.CadenaEventosInvalida:
        pass
    logger.info("✅ TEST 16 superado: un evento manipulado bloquea la proyección del estado, no la deja pasar en silencio.")

    # -------------------------------------------------------------------------
    # 17. Idempotencia por comando de origen: repetir el MISMO comando no duplica
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 17: idempotencia por comando_id, no por estado destino ---")
    op_id_idem = cmc.crear_operacion_entrada("34600006666", [("doc.pdf", b"a")])
    ev_a = cmc.registrar_evento_estado(op_id_idem, "01_ORDENES_ACEPTADAS", actor="Claudia", comando_id="cmd-idem-1")
    ev_b = cmc.registrar_evento_estado(op_id_idem, "01_ORDENES_ACEPTADAS", actor="Claudia", comando_id="cmd-idem-1")
    assert ev_a == ev_b, "Reintentar el mismo comando_id debe devolver el evento ya existente, no crear uno nuevo"
    assert len(cmc._leer_todos_los_eventos(op_id_idem)) == 1, "No debe haber duplicados en disco"

    try:
        cmc.registrar_evento_estado(op_id_idem, "03_BLOQUEADAS", actor="Claudia", comando_id="cmd-idem-1")
        assert False, "El mismo comando_id con un estado distinto debe rechazarse como conflicto"
    except ValueError:
        pass
    logger.info("✅ TEST 17 superado: repetir el mismo comando no duplica; el mismo comando con otro estado se rechaza como conflicto.")

    # -------------------------------------------------------------------------
    # 18. Repetición LEGÍTIMA de un mismo estado con comandos distintos -- SÍ debe permitirse
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 18: EJECUCIÓN->BLOQUEADA->EJECUCIÓN->BLOQUEADA es legítimo ---")
    op_id_repeticion = cmc.crear_operacion_entrada("34600005555", [("doc.pdf", b"b")])
    cmc.registrar_evento_estado(op_id_repeticion, "02_EN_EJECUCION", actor="Claudia", comando_id="c1")
    cmc.registrar_evento_estado(op_id_repeticion, "03_BLOQUEADAS", actor="Claudia", comando_id="c2", motivo="falta documento")
    cmc.registrar_evento_estado(op_id_repeticion, "02_EN_EJECUCION", actor="Claudia", comando_id="c3", motivo="documento recibido")
    cmc.registrar_evento_estado(op_id_repeticion, "03_BLOQUEADAS", actor="Claudia", comando_id="c4", motivo="otro motivo distinto")

    eventos_repeticion = cmc._leer_todos_los_eventos(op_id_repeticion)
    assert len(eventos_repeticion) == 4, "Los cuatro comandos son distintos -- ninguno debe descartarse como duplicado"
    assert cmc.obtener_estado_actual(op_id_repeticion) == "03_BLOQUEADAS"
    assert cmc.verificar_cadena_eventos(op_id_repeticion) is True
    logger.info("✅ TEST 18 superado: un estado puede revisitarse legítimamente varias veces con comandos distintos.")

    # -------------------------------------------------------------------------
    # 19. Bifurcación real: dos escrituras "concurrentes" no pueden reclamar la misma secuencia
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 19: la reclamación atómica de secuencia impide la bifurcación ---")
    op_id_bifurcacion = cmc.crear_operacion_entrada("34600004444", [("doc.pdf", b"c")])
    n1 = cmc._reclamar_secuencia(op_id_bifurcacion)
    n2 = cmc._reclamar_secuencia(op_id_bifurcacion)
    assert n1 != n2, "Dos reclamaciones consecutivas nunca deben obtener el mismo número de secuencia"
    assert n2 == n1 + 1
    logger.info("✅ TEST 19 superado: la reclamación de secuencia es realmente exclusiva (compare-and-swap vía O_CREAT|O_EXCL).")

    # -------------------------------------------------------------------------
    # 19b. Lo mismo, pero con CONCURRENCIA REAL (hilos de verdad, no llamadas secuenciales) --
    # mismo patrón ya usado en este proyecto para probar la condición de carrera de
    # promover_cliente_pendiente. Es la prueba que de verdad exige Claudia, no una aproximación.
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 19b: 20 hilos reales reclamando secuencia para la MISMA operación ---")
    op_id_concurrencia = cmc.crear_operacion_entrada("34600002222", [("doc.pdf", b"e")])
    secuencias_obtenidas = []
    errores_hilo = []
    lock_resultados = threading.Lock()

    def _reclamar_en_hilo():
        try:
            n = cmc._reclamar_secuencia(op_id_concurrencia)
            with lock_resultados:
                secuencias_obtenidas.append(n)
        except Exception as e:
            with lock_resultados:
                errores_hilo.append(e)

    hilos = [threading.Thread(target=_reclamar_en_hilo) for _ in range(20)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()

    assert not errores_hilo, f"Ningún hilo debe fallar: {errores_hilo}"
    assert len(secuencias_obtenidas) == 20
    assert len(set(secuencias_obtenidas)) == 20, f"20 hilos concurrentes deben obtener 20 números de secuencia DISTINTOS, se obtuvieron {sorted(secuencias_obtenidas)}"
    assert sorted(secuencias_obtenidas) == list(range(20)), "Las secuencias reclamadas deben cubrir 0..19 sin huecos ni repeticiones"
    logger.info("✅ TEST 19b superado: 20 hilos concurrentes reales, cero colisiones, cero huecos -- la exclusión mutua es real, no una convención.")

    # -------------------------------------------------------------------------
    # 20. Borrado del último evento: se detecta como hueco (el .claim sobrevive, el .json no)
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 20: borrado del último evento se detecta como hueco ---")
    op_id_borrado = cmc.crear_operacion_entrada("34600003333", [("doc.pdf", b"d")])
    cmc.registrar_evento_estado(op_id_borrado, "01_ORDENES_ACEPTADAS", actor="Claudia", comando_id="d1")
    ultimo_evento = cmc.registrar_evento_estado(op_id_borrado, "04_ENTREGADAS", actor="Claudia", comando_id="d2")

    assert cmc.verificar_cadena_eventos(op_id_borrado) is True

    eventos_borrado = cmc._leer_todos_los_eventos(op_id_borrado)
    ruta_ultimo = next(e["_ruta"] for e in eventos_borrado if e["EVENT_ID"] == ultimo_evento)
    ruta_hash_ultimo = ruta_ultimo[:-5] + ".sha256"
    os.remove(ruta_ultimo)
    os.remove(ruta_hash_ultimo)
    # El .claim de esa secuencia sigue existiendo -- eso es justo lo que delata el borrado.

    diagnostico = cmc.diagnosticar_cadena_eventos(op_id_borrado)
    assert diagnostico["valida"] is False
    assert diagnostico["ultimo_evento_ausente"] is True, "Debe detectar específicamente que el evento de mayor secuencia reclamada ha desaparecido"
    try:
        cmc.obtener_estado_actual(op_id_borrado)
        assert False
    except cmc.CadenaEventosInvalida:
        pass
    logger.info("✅ TEST 20 superado: borrar el último evento (sin borrar su reclamación de secuencia) se detecta y bloquea la proyección.")

    logger.info("\n================================================================================")
    logger.info("   ✅ TODAS LAS PRUEBAS DEL CONTRATO MAIRA-CLAUDIA (SINTÉTICAS) PASARON")
    logger.info("================================================================================")


if __name__ == "__main__":
    try:
        run_tests_sync()
        asyncio.run(run_tests_async())
    finally:
        shutil.rmtree(TEST_DIR, ignore_errors=True)
