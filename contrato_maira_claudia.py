"""
Implementación de las MECÁNICAS del contrato aprobado con Claudia
(docs/CONTRATO_MAIRA_CLAUDIA_V4_APROBADO.md) -- para pruebas sintéticas únicamente. El propio
addendum del contrato (punto 5) lo autoriza explícitamente mientras no exista un broker/ACL
real: "La inmutabilidad a nivel de aplicación... es válida únicamente para pruebas sintéticas.
Bloquea producción y datos reales hasta disponer de un broker/ACL efectivo...".

Este módulo:
- NO se conecta a la carpeta puente real de OneDrive/SharePoint (PUENTE_AGENTES) -- no importa
  graph_auth ni storage_adapter, opera siempre sobre una carpeta local de pruebas.
- NO está enganchado al flujo de conversación real de Maira (main.py/telegram_handler.py) --
  es un prototipo aislado para validar que la lógica del contrato es correcta.
- Implementa solo el lado de Maira: crear paquetes nuevos (entradas y acuses), leer paquetes
  dirigidos a ella. Nunca mueve nada entre carpetas de estado (01...05/90/99) -- esas
  transiciones son responsabilidad exclusiva de Claudia y no se simulan aquí.
"""
import os
import time
import uuid
import hashlib
import logging
from datetime import datetime

logger = logging.getLogger("asistente.contrato_maira_claudia")

VERSION_CONTRATO = 4
NOMBRE_CARPETA_NUEVAS = "00_ORDENES_NUEVAS"
RESULTADOS_VALIDOS = ("ENTREGADO", "FALLIDO_REINTENTABLE", "FALLIDO_DEFINITIVO")


def _carpeta_raiz_pruebas() -> str:
    return os.getenv("CONTRATO_MAIRA_CLAUDIA_TEST_DIR", "./storage/contrato_maira_claudia_pruebas")


def _generar_operation_id() -> str:
    return f"MAIRA-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"


def _sha256_bytes(contenido: bytes) -> str:
    return hashlib.sha256(contenido).hexdigest()


def _sha256_archivo(ruta: str) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(65536), b""):
            h.update(bloque)
    return h.hexdigest()


def _carpeta_nuevas() -> str:
    ruta = os.path.join(_carpeta_raiz_pruebas(), NOMBRE_CARPETA_NUEVAS)
    os.makedirs(ruta, exist_ok=True)
    return ruta


def _serializar_manifiesto(campos: dict) -> str:
    return "\n".join(f"{k}: {v if v is not None else ''}" for k, v in campos.items()) + "\n"


def _parsear_manifiesto(texto: str) -> dict:
    campos = {}
    for linea in texto.splitlines():
        if ":" not in linea:
            continue
        clave, _, valor = linea.partition(":")
        campos[clave.strip()] = valor.strip()
    return campos


def _escribir_paquete_atomico(operation_id: str, campos: dict, archivos: list) -> str:
    """
    archivos: lista de tuplas (nombre_archivo, contenido_bytes).
    Cada archivo se sube con sufijo .partial y se renombra de forma atómica al completarse.
    Solo cuando todos los archivos están renombrados se escribe manifiesto.md y, aparte,
    manifiesto.sha256 (hash EXTERNO, nunca autorreferencial, calculado sobre el manifiesto ya
    finalizado). Un paquete a medio escribir nunca aparenta estar completo ni se procesa.
    """
    carpeta_paquete = os.path.join(_carpeta_nuevas(), operation_id)
    try:
        os.makedirs(carpeta_paquete)  # exist_ok=False a propósito: un READY nunca admite dos escrituras
    except FileExistsError:
        raise RuntimeError(
            f"Ya existe un paquete para {operation_id} -- un paquete READY nunca admite una segunda escritura."
        )

    lista_archivos = []
    for nombre_archivo, contenido in archivos:
        ruta_parcial = os.path.join(carpeta_paquete, nombre_archivo + ".partial")
        ruta_final = os.path.join(carpeta_paquete, nombre_archivo)
        with open(ruta_parcial, "wb") as f:
            f.write(contenido)
        os.replace(ruta_parcial, ruta_final)
        lista_archivos.append(f"{nombre_archivo}|{len(contenido)}|{_sha256_bytes(contenido)}")

    campos_completos = dict(campos)
    campos_completos["ARCHIVOS"] = ";".join(lista_archivos)
    campos_completos["ESTADO"] = "READY"

    texto_manifiesto = _serializar_manifiesto(campos_completos)
    ruta_manifiesto_parcial = os.path.join(carpeta_paquete, "manifiesto.md.partial")
    ruta_manifiesto = os.path.join(carpeta_paquete, "manifiesto.md")
    with open(ruta_manifiesto_parcial, "w", encoding="utf-8") as f:
        f.write(texto_manifiesto)
    os.replace(ruta_manifiesto_parcial, ruta_manifiesto)

    hash_manifiesto = _sha256_archivo(ruta_manifiesto)
    with open(os.path.join(carpeta_paquete, "manifiesto.sha256"), "w", encoding="utf-8") as f:
        f.write(hash_manifiesto)

    logger.info(f"Paquete {operation_id} cerrado (READY) en {carpeta_paquete}")
    return carpeta_paquete


CAMPOS_EVIDENCIA_SELLADO = ("etiqueta_aplicada", "bloqueo_efectivo", "referencia_auditoria")


def confirmar_sellado_real(operation_id: str, evidencia: dict) -> None:
    """
    READY (sellado local, contenido completo + hash) no es lo mismo que "protegido de verdad".
    Esta función NUNCA debe activarse por un temporizador ni solo porque una petición a la API
    del proveedor respondió con éxito -- exige evidencia verificable explícita: que la etiqueta
    quedó realmente aplicada, que el bloqueo es efectivo (no solo solicitado), y una referencia
    de auditoría correlacionada que lo confirme. Sin los tres campos, se rechaza la llamada.
    """
    faltan = [c for c in CAMPOS_EVIDENCIA_SELLADO if not evidencia.get(c)]
    if faltan:
        raise ValueError(f"confirmar_sellado_real requiere evidencia verificable, faltan: {', '.join(faltan)}")

    carpeta_paquete = os.path.join(_carpeta_nuevas(), operation_id)
    ruta_confirmacion = os.path.join(carpeta_paquete, "sellado_confirmado.marker")
    contenido = _serializar_manifiesto({
        "FECHA_UTC": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ETIQUETA_APLICADA": evidencia["etiqueta_aplicada"],
        "BLOQUEO_EFECTIVO": evidencia["bloqueo_efectivo"],
        "REFERENCIA_AUDITORIA": evidencia["referencia_auditoria"],
    })
    with open(ruta_confirmacion, "w", encoding="utf-8") as f:
        f.write(contenido)


def paquete_accesible(operation_id: str) -> bool:
    """
    False durante la ventana de latencia entre READY y la confirmación real del mecanismo de
    inmutabilidad. Ni Maira ni Claudia deberían actuar sobre un paquete todavía no confirmado.
    """
    carpeta_paquete = os.path.join(_carpeta_nuevas(), operation_id)
    return os.path.exists(os.path.join(carpeta_paquete, "sellado_confirmado.marker"))


def _leer_paquete(carpeta_paquete: str) -> dict | None:
    """Retorna None si el paquete está incompleto o si el hash no verifica (manipulado)."""
    ruta_manifiesto = os.path.join(carpeta_paquete, "manifiesto.md")
    ruta_hash = os.path.join(carpeta_paquete, "manifiesto.sha256")
    if not os.path.exists(ruta_manifiesto) or not os.path.exists(ruta_hash):
        return None

    with open(ruta_hash, "r", encoding="utf-8") as f:
        hash_esperado = f.read().strip()
    if _sha256_archivo(ruta_manifiesto) != hash_esperado:
        logger.error(f"Hash de manifiesto no coincide en {carpeta_paquete} -- posible manipulación, se ignora.")
        return None

    with open(ruta_manifiesto, "r", encoding="utf-8") as f:
        campos = _parsear_manifiesto(f.read())
    campos["_carpeta"] = carpeta_paquete
    return campos


def _listar_todos_los_paquetes() -> list:
    carpeta = _carpeta_nuevas()
    resultado = []
    for nombre in os.listdir(carpeta):
        ruta_paquete = os.path.join(carpeta, nombre)
        if os.path.isdir(ruta_paquete):
            paquete = _leer_paquete(ruta_paquete)
            if paquete:
                resultado.append(paquete)
    return resultado


def crear_operacion_entrada(telefono_correlacion: str, archivos: list, tipo: str = "documento",
                             cliente_id: str = None, expediente_id: str = None,
                             numero_visible_cliente: str = None, numero_visible_expediente: str = None) -> str:
    """
    Crea un paquete MAIRA_A_CLAUDIA (entrada). Maira nunca consulta SharePoint para resolver
    la identidad -- si no se le pasa cliente_id ya resuelto por fuera, queda IDENTIDAD_PENDIENTE.
    """
    operation_id = _generar_operation_id()
    campos = {
        "OPERATION_ID": operation_id,
        "DIRECCION": "MAIRA_A_CLAUDIA",
        "PARENT_OPERATION_ID": "",
        "CLAVE_IDEMPOTENTE": _sha256_bytes(f"{telefono_correlacion}-{time.time()}".encode())[:16],
        "VERSION_CONTRATO": str(VERSION_CONTRATO),
        "FECHA_HORA": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "ORIGEN": "whatsapp",
        "TELEFONO_CORRELACION": telefono_correlacion,
        "CLIENTE_ID": cliente_id or "",
        "EXPEDIENTE_ID": expediente_id or "",
        "NUMERO_VISIBLE_CLIENTE": numero_visible_cliente or "",
        "NUMERO_VISIBLE_EXPEDIENTE": numero_visible_expediente or "",
        "ESTADO_IDENTIDAD": "RESUELTA" if cliente_id else "IDENTIDAD_PENDIENTE",
        "TIPO": tipo,
    }
    _escribir_paquete_atomico(operation_id, campos, archivos)
    return operation_id


def leer_operaciones_dirigidas_a_maira() -> list:
    """Lee del área de 'nuevos' los paquetes con DIRECCION: CLAUDIA_A_MAIRA."""
    return [p for p in _listar_todos_los_paquetes() if p.get("DIRECCION") == "CLAUDIA_A_MAIRA"]


RESULTADOS_IDENTIDAD_VALIDOS = ("UNICO", "AMBIGUO", "NO_ENCONTRADO")


def crear_resolucion_identidad(parent_operation_id: str, resultado: str, cliente_id: str = None,
                                expediente_id: str = None) -> str:
    """
    Simula el lado de Claudia creando una RESOLUCION_IDENTIDAD -- existe en este prototipo
    solo para poder probar cómo la consume Maira (ver leer_resolucion_identidad). En el sistema
    real, quien crea esta operación es Claudia, nunca Maira.
    """
    if resultado not in RESULTADOS_IDENTIDAD_VALIDOS:
        raise ValueError(f"RESULTADO inválido: {resultado}")
    if resultado != "UNICO" and (cliente_id or expediente_id):
        raise ValueError("Solo un resultado UNICO puede llevar CLIENTE_ID/EXPEDIENTE_ID")

    operation_id = _generar_operation_id()
    campos = {
        "OPERATION_ID": operation_id,
        "DIRECCION": "CLAUDIA_A_MAIRA",
        "TIPO": "RESOLUCION_IDENTIDAD",
        "PARENT_OPERATION_ID": parent_operation_id,
        "CLIENTE_ID": cliente_id or "",
        "RESULTADO": resultado,
        "EXPEDIENTE_ID": expediente_id or "",
    }
    _escribir_paquete_atomico(operation_id, campos, [])
    return operation_id


def leer_resolucion_identidad(parent_operation_id: str) -> dict | None:
    """
    Busca la resolución de identidad para UNA operación concreta. Deliberadamente no cachea
    nada entre llamadas -- cada consulta relee del almacén, y el resultado solo debe usarse
    para la operación/conversación que lo originó (nunca se guarda como "el cliente de este
    teléfono" para el futuro; el número puede cambiar de dueño, reciclarse o compartirse).
    """
    for paquete in _listar_todos_los_paquetes():
        if (paquete.get("TIPO") == "RESOLUCION_IDENTIDAD"
                and paquete.get("DIRECCION") == "CLAUDIA_A_MAIRA"
                and paquete.get("PARENT_OPERATION_ID") == parent_operation_id):
            return paquete
    return None


class EntregaBloqueada(Exception):
    pass


def validar_salida_para_entrega(paquete: dict) -> None:
    """Lanza EntregaBloqueada si el paquete no cumple los requisitos del contrato. No entrega nada."""
    if paquete.get("AUTORIZADO_PARA_ENTREGA") != "SI":
        raise EntregaBloqueada("AUTORIZADO_PARA_ENTREGA no es SI")

    caducidad_str = paquete.get("CADUCIDAD_ENTREGA")
    if caducidad_str:
        try:
            caducidad = datetime.strptime(caducidad_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            raise EntregaBloqueada(f"CADUCIDAD_ENTREGA con formato inválido: {caducidad_str}")
        if datetime.now() > caducidad:
            raise EntregaBloqueada(f"Entrega caducada el {caducidad_str}")

    if paquete.get("VALIDACION_HUMANA_REQUERIDA") == "SI":
        faltan = [c for c in ("VALIDACION_HUMANA_ID", "AUTORIZADO_POR", "AUTORIZADO_EN") if not paquete.get(c)]
        if faltan:
            raise EntregaBloqueada(f"Falta validación humana: {', '.join(faltan)}")

    if not paquete.get("CONVERSACION_EXACTA"):
        raise EntregaBloqueada("Falta CONVERSACION_EXACTA (el teléfono solo nunca basta)")


def ya_entregado(parent_operation_id: str) -> bool:
    """Comprueba si ya existe un acuse ENTREGADO para esta operación (evita reenviar en un reintento)."""
    for paquete in _listar_todos_los_paquetes():
        if (paquete.get("TIPO") == "acuse_entrega"
                and paquete.get("PARENT_OPERATION_ID") == parent_operation_id
                and paquete.get("RESULTADO_ENTREGA") == "ENTREGADO"):
            return True
    return False


def crear_acuse_entrega(parent_operation_id: str, resultado_entrega: str, intentos: int,
                         id_proveedor: str = None, estado_proveedor: str = None) -> str:
    """
    El acuse es SIEMPRE una operación nueva e independiente -- nunca se escribe dentro del
    paquete de salida original (esa era precisamente la violación de inmutabilidad que Claudia
    corrigió en la ronda anterior de revisión del contrato).
    """
    if resultado_entrega not in RESULTADOS_VALIDOS:
        raise ValueError(f"RESULTADO_ENTREGA inválido: {resultado_entrega}")

    operation_id = _generar_operation_id()
    campos = {
        "OPERATION_ID": operation_id,
        "DIRECCION": "MAIRA_A_CLAUDIA",
        "TIPO": "acuse_entrega",
        "PARENT_OPERATION_ID": parent_operation_id,
        "RESULTADO_ENTREGA": resultado_entrega,
        "INTENTOS": str(intentos),
        "FECHA_ENTREGA": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "ID_PROVEEDOR": id_proveedor or "",
        # Solo lo que el canal confirme de verdad -- nunca "entregado/leído" si no está probado.
        "ESTADO_PROVEEDOR": estado_proveedor or "",
    }
    _escribir_paquete_atomico(operation_id, campos, [])
    return operation_id


async def procesar_operacion_salida(paquete: dict, entregar_fn, max_intentos: int = 3) -> dict:
    """
    Orquesta el lado de Maira para una salida (CLAUDIA_A_MAIRA): valida, comprueba idempotencia,
    intenta la entrega (con reintentos) y crea el acuse correspondiente. Nunca mueve el paquete
    de salida ni crea nada fuera de 00_ORDENES_NUEVAS -- mover a 05_VALIDADAS es exclusivo de
    Claudia, aquí no se simula.

    entregar_fn: callable async(paquete) -> dict con
        {"exito": bool, "id_proveedor": str, "estado_proveedor": str, "reintentable": bool}
    """
    operation_id = paquete["OPERATION_ID"]

    if ya_entregado(operation_id):
        logger.info(f"Salida {operation_id} ya tenía un acuse ENTREGADO -- no se reintenta.")
        return {"resultado": "ENTREGADO", "ya_procesado": True}

    try:
        validar_salida_para_entrega(paquete)
    except EntregaBloqueada as e:
        logger.warning(f"Entrega bloqueada para {operation_id}: {e}")
        return {"resultado": "BLOQUEADO", "motivo": str(e)}

    intentos = 0
    resultado_final = "FALLIDO_DEFINITIVO"
    id_proveedor = None
    estado_proveedor = None

    while intentos < max_intentos:
        intentos += 1
        respuesta = await entregar_fn(paquete)
        id_proveedor = respuesta.get("id_proveedor")
        estado_proveedor = respuesta.get("estado_proveedor")
        if respuesta.get("exito"):
            resultado_final = "ENTREGADO"
            break
        if not respuesta.get("reintentable", True):
            resultado_final = "FALLIDO_DEFINITIVO"
            break
        resultado_final = "FALLIDO_REINTENTABLE"

    crear_acuse_entrega(operation_id, resultado_final, intentos, id_proveedor, estado_proveedor)
    return {"resultado": resultado_final, "intentos": intentos}


# ---------------------------------------------------------------------------
# Registro de transiciones de estado (V4, corregida por Claudia sobre V3):
# un paquete READY nunca se mueve ni se edita. Las transiciones de estado se registran como
# eventos INDEPENDIENTES e INMUTABLES (nunca líneas de un archivo compartido). Correcciones V4:
#
# 1. Bifurcación: se impide por diseño, no por convención de "un solo actor". Cada evento
#    reclama un número de SECUENCIA mediante creación exclusiva de archivo (O_CREAT|O_EXCL),
#    que el sistema de archivos garantiza atómica -- es la primitiva compare-and-swap real.
# 2. Idempotencia: la clave identifica el COMANDO/intento de origen (comando_id), no el estado
#    destino -- un mismo estado puede visitarse legítimamente varias veces
#    (EJECUCIÓN->BLOQUEADA->EJECUCIÓN->BLOQUEADA); solo reintentar el mismo comando_id es un
#    duplicado real.
# 3. Orden: SECUENCIA monotónica asignada atómicamente, no el timestamp (que no garantiza orden
#    único). El diagnóstico de la cadena detecta huecos (secuencia reclamada sin evento válido)
#    y bifurcaciones (por si alguien saltó la reclamación atómica escribiendo a mano).
# 4. Borrado del último evento: la reclamación de secuencia (.claim) es un artefacto
#    INDEPENDIENTE del contenido del evento (.json/.sha256). Si se borra el evento pero no su
#    claim, se detecta como hueco en la posición más alta. No protege contra un atacante que
#    borre AMBOS -- eso requiere un anclaje externo cruzado con el lado de Claudia, fuera del
#    alcance de lo que el código de Maira puede garantizar en solitario (ver
#    PROPUESTA_BROKER_ACL_V4.md).
# ---------------------------------------------------------------------------

NOMBRE_CARPETA_ESTADOS = "ESTADOS"
SUBCARPETA_SECUENCIA = "_secuencia"


class CadenaEventosInvalida(Exception):
    pass


def _carpeta_estados() -> str:
    return os.path.join(_carpeta_raiz_pruebas(), NOMBRE_CARPETA_ESTADOS)


def _carpeta_estados_operacion(operation_id: str) -> str:
    ruta = os.path.join(_carpeta_estados(), operation_id)
    os.makedirs(ruta, exist_ok=True)
    return ruta


def _carpeta_secuencia_operacion(operation_id: str) -> str:
    ruta = os.path.join(_carpeta_estados_operacion(operation_id), SUBCARPETA_SECUENCIA)
    os.makedirs(ruta, exist_ok=True)
    return ruta


def _reclamar_secuencia(operation_id: str, max_reintentos: int = 200) -> int:
    """
    Reclama atómicamente el siguiente número de secuencia. La creación exclusiva de archivo
    (O_CREAT|O_EXCL) es la primitiva compare-and-swap: si dos escritores intentan reclamar el
    mismo número a la vez, el sistema de archivos garantiza que solo uno tiene éxito -- el otro
    falla con FileExistsError y reintenta con el siguiente número. Esto es lo que impide una
    bifurcación silenciosa, no una convención de "solo escribe un actor a la vez".
    """
    carpeta_seq = _carpeta_secuencia_operacion(operation_id)
    existentes = [int(f[:-6]) for f in os.listdir(carpeta_seq) if f.endswith(".claim")]
    n = (max(existentes) + 1) if existentes else 0
    for _ in range(max_reintentos):
        ruta_claim = os.path.join(carpeta_seq, f"{n:010d}.claim")
        try:
            fd = os.open(ruta_claim, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return n
        except FileExistsError:
            n += 1
    raise RuntimeError(f"No se pudo reclamar secuencia para {operation_id} tras {max_reintentos} intentos")


def _secuencias_reclamadas(operation_id: str) -> set:
    carpeta_seq = _carpeta_secuencia_operacion(operation_id)
    return {int(f[:-6]) for f in os.listdir(carpeta_seq) if f.endswith(".claim")}


def _leer_evento(ruta_json: str) -> dict | None:
    """Retorna None si falta el hash o no verifica (evento incompleto o manipulado)."""
    ruta_hash = ruta_json[:-5] + ".sha256"  # quita ".json", añade ".sha256"
    if not os.path.exists(ruta_hash):
        return None
    with open(ruta_hash, "r", encoding="utf-8") as f:
        hash_esperado = f.read().strip()
    if _sha256_archivo(ruta_json) != hash_esperado:
        logger.error(f"Hash de evento no coincide en {ruta_json} -- posible manipulación, se ignora.")
        return None
    with open(ruta_json, "r", encoding="utf-8") as f:
        campos = _parsear_manifiesto(f.read())
    campos["_hash_evento"] = hash_esperado
    campos["_ruta"] = ruta_json
    return campos


def _leer_eventos_por_secuencia(operation_id: str) -> dict:
    """{numero_secuencia: evento} -- solo eventos con hash válido y campo SECUENCIA numérico."""
    carpeta_op = os.path.join(_carpeta_estados(), operation_id)
    if not os.path.isdir(carpeta_op):
        return {}
    eventos = {}
    for nombre in os.listdir(carpeta_op):
        if not nombre.endswith(".json"):
            continue
        evento = _leer_evento(os.path.join(carpeta_op, nombre))
        if evento and evento.get("SECUENCIA", "").isdigit():
            eventos[int(evento["SECUENCIA"])] = evento
    return eventos


def _leer_todos_los_eventos(operation_id: str) -> list:
    """Eventos válidos de una operación, en orden de SECUENCIA (no de timestamp)."""
    eventos_por_seq = _leer_eventos_por_secuencia(operation_id)
    return [eventos_por_seq[n] for n in sorted(eventos_por_seq.keys())]


def diagnosticar_cadena_eventos(operation_id: str) -> dict:
    """
    Diagnóstico explícito de la cadena -- no un simple booleano. Distingue huecos (secuencia
    reclamada sin evento válido correspondiente, indicando borrado o escritura incompleta),
    ruptura del encadenamiento de hashes, y si el evento de la secuencia más alta reclamada ha
    desaparecido (posible borrado del último evento).
    """
    reclamadas = _secuencias_reclamadas(operation_id)
    eventos_por_seq = _leer_eventos_por_secuencia(operation_id)

    if not reclamadas:
        return {"valida": True, "huecos": [], "cadena_rota": False, "ultimo_evento_ausente": False, "eventos": []}

    huecos = sorted(n for n in reclamadas if n not in eventos_por_seq)
    eventos_ordenados = [eventos_por_seq[n] for n in sorted(eventos_por_seq.keys())]

    cadena_rota = False
    hash_esperado_anterior = ""
    for evento in eventos_ordenados:
        if evento["HASH_EVENTO_ANTERIOR"] != hash_esperado_anterior:
            cadena_rota = True
            break
        hash_esperado_anterior = evento["_hash_evento"]

    ultimo_evento_ausente = max(reclamadas) not in eventos_por_seq

    return {
        "valida": (not huecos) and (not cadena_rota) and (not ultimo_evento_ausente),
        "huecos": huecos,
        "cadena_rota": cadena_rota,
        "ultimo_evento_ausente": ultimo_evento_ausente,
        "eventos": eventos_ordenados,
    }


def verificar_cadena_eventos(operation_id: str) -> bool:
    """Versión booleana de diagnosticar_cadena_eventos, para el caso común."""
    return diagnosticar_cadena_eventos(operation_id)["valida"]


def registrar_evento_estado(operation_id: str, estado_nuevo: str, actor: str, comando_id: str,
                             motivo: str = "", hash_paquete: str = None) -> str:
    """
    Registra una transición de estado como evento inmutable e independiente. `comando_id`
    identifica el comando/intento que origina la transición (no el estado destino): permite que
    un mismo estado se visite legítimamente varias veces, mientras que reintentar EXACTAMENTE el
    mismo comando_id devuelve el evento ya existente en vez de duplicarlo. Un comando_id repetido
    con un estado_nuevo distinto se rechaza como conflicto, no como reintento legítimo.
    """
    eventos_existentes = _leer_eventos_por_secuencia(operation_id)
    for evento in eventos_existentes.values():
        if evento.get("CLAVE_IDEMPOTENTE") == comando_id:
            if evento["ESTADO_NUEVO"] != estado_nuevo:
                raise ValueError(
                    f"comando_id '{comando_id}' ya se procesó con un estado distinto "
                    f"({evento['ESTADO_NUEVO']} != {estado_nuevo}) -- conflicto, no reintento legítimo"
                )
            logger.info(f"comando_id '{comando_id}' ya procesado (evento {evento['EVENT_ID']}) -- no se duplica.")
            return evento["EVENT_ID"]

    secuencia = _reclamar_secuencia(operation_id)
    eventos_ordenados = [eventos_existentes[n] for n in sorted(eventos_existentes.keys())]
    ultimo = eventos_ordenados[-1] if eventos_ordenados else None
    hash_evento_anterior = ultimo["_hash_evento"] if ultimo else ""
    estado_anterior = ultimo["ESTADO_NUEVO"] if ultimo else ""

    carpeta_op = _carpeta_estados_operacion(operation_id)
    event_id = uuid.uuid4().hex[:12]
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S%f")
    nombre_base = f"{secuencia:010d}_{timestamp}_{event_id}"

    campos = {
        "EVENT_ID": event_id,
        "OPERATION_ID": operation_id,
        "SECUENCIA": str(secuencia),
        "ESTADO_ANTERIOR": estado_anterior,
        "ESTADO_NUEVO": estado_nuevo,
        "ACTOR": actor,
        "FECHA_UTC": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "MOTIVO": motivo,
        "CLAVE_IDEMPOTENTE": comando_id,
        "HASH_PAQUETE": hash_paquete or "",
        "HASH_EVENTO_ANTERIOR": hash_evento_anterior,
    }

    texto = _serializar_manifiesto(campos)
    ruta_parcial = os.path.join(carpeta_op, nombre_base + ".json.partial")
    ruta_json = os.path.join(carpeta_op, nombre_base + ".json")
    with open(ruta_parcial, "w", encoding="utf-8") as f:
        f.write(texto)
    os.replace(ruta_parcial, ruta_json)

    hash_evento = _sha256_archivo(ruta_json)
    with open(os.path.join(carpeta_op, nombre_base + ".sha256"), "w", encoding="utf-8") as f:
        f.write(hash_evento)

    logger.info(f"Evento {event_id} (secuencia {secuencia}) registrado para {operation_id}: {estado_anterior or '(inicio)'} -> {estado_nuevo}")
    return event_id


def obtener_estado_actual(operation_id: str) -> str | None:
    """
    El estado actual NUNCA se lee de un campo almacenado -- se calcula como proyección de la
    cadena de eventos. Si no hay eventos, retorna None. Si la cadena no es fiable (hueco,
    bifurcación, o el último evento ha desaparecido), se BLOQUEA la proyección lanzando
    CadenaEventosInvalida en vez de arriesgarse a devolver un estado desactualizado o manipulado.
    """
    diagnostico = diagnosticar_cadena_eventos(operation_id)
    if not diagnostico["eventos"]:
        return None
    if not diagnostico["valida"]:
        raise CadenaEventosInvalida(
            f"Cadena de eventos de {operation_id} no es fiable: huecos={diagnostico['huecos']}, "
            f"cadena_rota={diagnostico['cadena_rota']}, ultimo_evento_ausente={diagnostico['ultimo_evento_ausente']}"
        )
    return diagnostico["eventos"][-1]["ESTADO_NUEVO"]
