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
import json
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

    IMPORTANTE: esto es una proyección LOCAL, PROVISIONAL -- verificar la cadena localmente no la
    hace firme. Para saber si un estado ya tiene el anclaje externo que lo confirma, usar
    obtener_estado_confirmado().
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


# ---------------------------------------------------------------------------
# Anclaje externo (checkpoint firmado) -- V3, según el veredicto de Claudia del 31/08/2026 sobre
# la V2 ("mejora sustancialmente, pero requiere V3 antes del spike real"). Correcciones:
#
# 1. El ACK dejó de ser el eslabón débil: ahora es una copia COMPLETA y verificable del
#    checkpoint persistido (incluye FIRMA y SIGNED_PAYLOAD_HASH) -- Maira puede verificarlo por
#    sí misma con verificar_checkpoint_estructural, no solo confiar en de dónde vino el archivo.
# 2. Serialización canónica: se sustituye el "campo=valor\n" (vulnerable a valores con '=', saltos
#    de línea o unicode sin escapar) por un array JSON de valores en orden fijo, con
#    ensure_ascii=True y separators sin espacios -- evita la ambigüedad de un objeto JSON (que
#    exigiría ordenar claves al estilo RFC 8785) codificando el orden en la propia lista de
#    campos, no en el documento. IDENTIDAD_FIRMANTE ahora forma parte de los campos firmados.
# 3. La detección de conflicto compara una huella completa (HASH_CABEZA, HASH_PAQUETE,
#    VERSION_ESQUEMA) por SECUENCIA, no solo HASH_CABEZA.
# 4. HASH_PAQUETE usa ausencia TIPADA (la clave simplemente no existe, nunca "NULL" de texto) y
#    se recalcula SIEMPRE directamente sobre manifiesto.md -- nunca leyendo manifiesto.sha256,
#    que aunque hoy está protegido por la exclusividad del directorio del paquete, no tiene su
#    propia protección O_CREAT|O_EXCL de archivo.
# 5. _simular_claudia_crear_checkpoint relee el checkpoint YA ESCRITO en disco y lo verifica
#    estructuralmente antes de publicar su ACK -- nunca publica un ACK solo porque la escritura
#    "aparentemente" tuvo éxito. La exigencia de ETag/versionado real contra SharePoint queda
#    en el spike (ver docs/PROPUESTA_ANCLAJE_EXTERNO_V3.md) -- un doble read local no puede
#    simular la consistencia eventual de un backend remoto real.
# 6. Confianza inicial explícita (registrar_clave_vigente -- default-DENY, una clave nunca se
#    confía solo por aparecer en un checkpoint) y revocación tipada: "cese" es prospectiva
#    (rotación normal), "compromiso" invalida desde una fecha_efectiva estimada que puede ser
#    anterior a cuándo se detectó, obligando a reanclar con clave válida todo lo posterior.
#    Fuente horaria: sigue siendo el reloj del proceso (datetime.utcnow()) -- no es una fuente de
#    tiempo confiable frente a un adversario que controle el proceso; el spike debe evaluar usar
#    el timestamp que el propio backend (SharePoint/Purview) asigna en servidor, no uno que
#    cualquiera de las partes declare por su cuenta.
# ---------------------------------------------------------------------------

NOMBRE_CARPETA_NOTIFICACIONES = "NOTIFICACIONES_CABEZA"
NOMBRE_CARPETA_ANCLAJE = "ANCLAJE_EXTERNO"      # almacén completo y protegido -- Maira no lo lee en producción
NOMBRE_CARPETA_ACKS = "ACKS_ANCLAJE"            # buzón de Maira: copia completa y verificable del checkpoint
NOMBRE_CARPETA_CLAVES_REVOCADAS = "CLAVES_REVOCADAS"
NOMBRE_CARPETA_CLAVES_VIGENTES = "CLAVES_VIGENTES"

VERSION_ESQUEMA_ANCLAJE = "3"
TIPOS_REVOCACION = ("cese", "compromiso")

# Campos exactos, en este orden, que entran en el payload firmado -- cualquier cambio a esta
# lista es un cambio de esquema y exige subir VERSION_ESQUEMA_ANCLAJE. Un campo ausente serializa
# como null de verdad (json.dumps de una lista con None), no como cadena vacía ni "NULL" de texto.
CAMPOS_FIRMADOS_ANCLAJE_V3 = (
    "CHECKPOINT_ID", "OPERATION_ID", "SECUENCIA", "HASH_CABEZA", "HASH_PAQUETE",
    "MOTIVO_SIN_PAQUETE", "FECHA_UTC", "KEY_ID", "IDENTIDAD_FIRMANTE",
    "ALGORITMO_FIRMA", "VERSION_ESQUEMA",
)
CAMPOS_CHECKPOINT_OBLIGATORIOS = (
    "CHECKPOINT_ID", "OPERATION_ID", "SECUENCIA", "HASH_CABEZA",
    "FECHA_UTC", "KEY_ID", "IDENTIDAD_FIRMANTE", "ALGORITMO_FIRMA", "VERSION_ESQUEMA",
    "SIGNED_PAYLOAD_HASH", "FIRMA",
)  # HASH_PAQUETE queda fuera a propósito -- puede estar legítimamente ausente (ver _registro_bien_formado)
CAMPOS_ACK_OBLIGATORIOS = CAMPOS_CHECKPOINT_OBLIGATORIOS + ("ACK_ID", "FECHA_ENTREGA_UTC")


class CheckpointConflictivo(Exception):
    pass


def _carpeta_notificaciones_operacion(operation_id: str) -> str:
    ruta = os.path.join(_carpeta_raiz_pruebas(), NOMBRE_CARPETA_NOTIFICACIONES, operation_id)
    os.makedirs(ruta, exist_ok=True)
    return ruta


def _carpeta_anclaje_operacion(operation_id: str) -> str:
    ruta = os.path.join(_carpeta_raiz_pruebas(), NOMBRE_CARPETA_ANCLAJE, operation_id)
    os.makedirs(ruta, exist_ok=True)
    return ruta


def _carpeta_acks_operacion(operation_id: str) -> str:
    ruta = os.path.join(_carpeta_raiz_pruebas(), NOMBRE_CARPETA_ACKS, operation_id)
    os.makedirs(ruta, exist_ok=True)
    return ruta


def _carpeta_claves_revocadas() -> str:
    ruta = os.path.join(_carpeta_raiz_pruebas(), NOMBRE_CARPETA_CLAVES_REVOCADAS)
    os.makedirs(ruta, exist_ok=True)
    return ruta


def _carpeta_claves_vigentes() -> str:
    ruta = os.path.join(_carpeta_raiz_pruebas(), NOMBRE_CARPETA_CLAVES_VIGENTES)
    os.makedirs(ruta, exist_ok=True)
    return ruta


def notificar_cabeza_nueva(operation_id: str) -> str:
    """
    Disparador mínimo e inmutable para que Claudia sepa que hay una cabeza nueva que revisar. NO
    incluye HASH_CABEZA ni nada que pudiera tratarse como fuente de verdad -- SECUENCIA se incluye
    solo como referencia orientativa. Idempotente: el nombre de archivo depende únicamente de la
    SECUENCIA, así que reintentar la notificación de la misma cabeza nunca duplica nada.
    """
    diagnostico = diagnosticar_cadena_eventos(operation_id)
    if not diagnostico["eventos"]:
        raise ValueError(f"No hay eventos para {operation_id} -- nada que notificar")

    secuencia = int(diagnostico["eventos"][-1]["SECUENCIA"])
    carpeta = _carpeta_notificaciones_operacion(operation_id)
    ruta = os.path.join(carpeta, f"{secuencia:010d}.json")

    if os.path.exists(ruta):
        with open(ruta, "r", encoding="utf-8") as f:
            return _parsear_manifiesto(f.read())["NOTIFICATION_ID"]

    notification_id = uuid.uuid4().hex[:12]
    campos = {
        "NOTIFICATION_ID": notification_id,
        "OPERATION_ID": operation_id,
        "SECUENCIA": str(secuencia),
        "FECHA_UTC": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    try:
        fd = os.open(ruta, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(_serializar_manifiesto(campos))
        return notification_id
    except FileExistsError:
        # Otra llamada concurrente ganó la carrera -- idempotente igualmente, se lee lo que ya hay.
        with open(ruta, "r", encoding="utf-8") as f:
            return _parsear_manifiesto(f.read())["NOTIFICATION_ID"]


def _hash_manifiesto_sellado(operation_id: str) -> str | None:
    """
    Hash CANÓNICO del manifiesto ya sellado -- recomputado directamente sobre manifiesto.md,
    nunca leído de manifiesto.sha256 (que, aunque hoy protegido por la exclusividad del
    directorio del paquete, no tiene su propia protección de archivo O_CREAT|O_EXCL). Retorna
    None (ausencia tipada, no "NULL" de texto) si no existe paquete para esa operación.
    """
    paquete = next((p for p in _listar_todos_los_paquetes() if p["OPERATION_ID"] == operation_id), None)
    if paquete is None:
        return None
    return _sha256_archivo(os.path.join(paquete["_carpeta"], "manifiesto.md"))


def _payload_canonico_checkpoint(campos: dict) -> bytes:
    """
    Serialización canónica y determinista de los campos firmados: un array JSON de valores en el
    orden fijo de CAMPOS_FIRMADOS_ANCLAJE_V3 (el orden lo da la lista, no el documento -- evita
    tener que canonicalizar un objeto al estilo RFC 8785), con ensure_ascii=True (sin ambigüedad
    de normalización Unicode) y sin espacios. Un campo ausente serializa como null real, no como
    cadena vacía. Es la única superficie que la firma protege.
    """
    valores = [campos.get(campo) for campo in CAMPOS_FIRMADOS_ANCLAJE_V3]
    return json.dumps(valores, ensure_ascii=True, separators=(",", ":")).encode("utf-8")


def verificar_checkpoint_estructural(checkpoint: dict) -> bool:
    """
    Recalcula el hash canónico a partir de los propios campos del checkpoint y lo compara con
    SIGNED_PAYLOAD_HASH -- detecta manipulación estructural (incluida una falsificación del ACK
    por otro escritor con acceso al buzón) sin verificar FIRMA criptográficamente todavía, lo que
    depende del esquema de claves/PKI real pendiente del spike.
    """
    return hashlib.sha256(_payload_canonico_checkpoint(checkpoint)).hexdigest() == checkpoint.get("SIGNED_PAYLOAD_HASH")


def _registro_bien_formado(campos: dict, campos_obligatorios: tuple) -> bool:
    """HASH_PAQUETE y MOTIVO_SIN_PAQUETE son mutuamente excluyentes: exactamente uno debe estar presente."""
    tiene_obligatorios = all(campos.get(c) for c in campos_obligatorios)
    paquete_xor_motivo = ("HASH_PAQUETE" in campos) != ("MOTIVO_SIN_PAQUETE" in campos)
    return tiene_obligatorios and paquete_xor_motivo


def registrar_clave_vigente(key_id: str, identidad: str, fecha_utc: str = None) -> None:
    """
    SOLO PARA PRUEBAS SINTÉTICAS: confianza inicial EXPLÍCITA -- una clave nunca se considera
    vigente solo por aparecer en un checkpoint (default-deny, no default-allow). Rotación de
    claves = registrar la nueva + revocar la vieja con tipo="cese" desde la fecha de corte.
    """
    ruta = os.path.join(_carpeta_claves_vigentes(), f"{key_id}.json")
    campos = {
        "KEY_ID": key_id,
        "IDENTIDAD": identidad,
        "FECHA_ALTA_UTC": fecha_utc or datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    fd = os.open(ruta, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(_serializar_manifiesto(campos))


def revocar_clave(key_id: str, tipo: str, motivo: str, fecha_utc: str = None, fecha_efectiva: str = None) -> None:
    """
    SOLO PARA PRUEBAS SINTÉTICAS. tipo="cese": revocación PROSPECTIVA (rotación normal, fin de
    vida útil) -- invalida checkpoints firmados en o después de esta revocación, nunca los
    anteriores. tipo="compromiso": invalida checkpoints firmados en o después de fecha_efectiva
    -- la fecha ESTIMADA del compromiso, que puede ser anterior a cuándo se detectó -- y obliga a
    reanclar con una clave válida todo lo posterior a esa fecha.
    """
    if tipo not in TIPOS_REVOCACION:
        raise ValueError(f"tipo de revocación inválido: {tipo}")
    fecha_utc = fecha_utc or datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    if tipo == "compromiso":
        if not fecha_efectiva:
            raise ValueError("Una revocación por compromiso exige fecha_efectiva (fecha estimada del compromiso)")
        fecha_corte = fecha_efectiva
    else:
        fecha_corte = fecha_utc

    ruta = os.path.join(_carpeta_claves_revocadas(), f"{key_id}.json")
    campos = {
        "KEY_ID": key_id,
        "TIPO": tipo,
        "MOTIVO": motivo,
        "FECHA_UTC": fecha_utc,
        "FECHA_CORTE": fecha_corte,
    }
    fd = os.open(ruta, os.O_CREAT | os.O_EXCL | os.O_WRONLY)  # una revocación es inmutable, nunca se deshace
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(_serializar_manifiesto(campos))


def _clave_vigente_en(key_id: str, fecha_utc_checkpoint: str) -> bool:
    """Vigente = dada de alta antes (o en) esa fecha, y sin corte de revocación anterior (o igual) a esa fecha."""
    ruta_alta = os.path.join(_carpeta_claves_vigentes(), f"{key_id}.json")
    if not os.path.exists(ruta_alta):
        return False
    with open(ruta_alta, "r", encoding="utf-8") as f:
        alta = _parsear_manifiesto(f.read())
    if alta["FECHA_ALTA_UTC"] > fecha_utc_checkpoint:
        return False

    ruta_revocacion = os.path.join(_carpeta_claves_revocadas(), f"{key_id}.json")
    if not os.path.exists(ruta_revocacion):
        return True
    with open(ruta_revocacion, "r", encoding="utf-8") as f:
        revocacion = _parsear_manifiesto(f.read())
    return revocacion["FECHA_CORTE"] > fecha_utc_checkpoint


def _crear_ack_checkpoint(checkpoint: dict) -> str:
    """
    SOLO PARA PRUEBAS SINTÉTICAS: simula a Claudia entregando el ACK a Maira. El ACK es una copia
    COMPLETA y verificable del checkpoint persistido (incluye FIRMA y SIGNED_PAYLOAD_HASH) -- un
    ACK despojado de esos campos no se puede autenticar, y el acceso de solo lectura al buzón no
    evita que otro escritor falsifique uno; Maira tiene que poder verificarlo por sí misma.
    """
    ack_id = uuid.uuid4().hex[:12]
    campos = dict(checkpoint)
    campos["ACK_ID"] = ack_id
    campos["FECHA_ENTREGA_UTC"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    carpeta = _carpeta_acks_operacion(checkpoint["OPERATION_ID"])
    ruta = os.path.join(carpeta, f"{ack_id}.json")
    fd = os.open(ruta, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(_serializar_manifiesto(campos))
    return ack_id


def _leer_checkpoint_individual(carpeta_anclaje: str, checkpoint_id: str) -> dict | None:
    ruta = os.path.join(carpeta_anclaje, f"{checkpoint_id}.json")
    if not os.path.exists(ruta):
        return None
    with open(ruta, "r", encoding="utf-8") as f:
        campos = _parsear_manifiesto(f.read())
    return campos if _registro_bien_formado(campos, CAMPOS_CHECKPOINT_OBLIGATORIOS) else None


def _simular_claudia_crear_checkpoint(operation_id: str, identidad_firmante: str, key_id: str,
                                       algoritmo_firma: str = "Ed25519", max_reintentos: int = 3) -> str:
    """
    SOLO PARA PRUEBAS SINTÉTICAS: simula el lado de Claudia. Modela la instantánea estable exigida
    -- lee la cabeza, y la relee antes de firmar; si cambió entre medias, reintenta sobre la
    cabeza nueva en vez de firmar una vista obsoleta -- y confirma que el checkpoint quedó
    persistido (releído desde disco y verificado estructuralmente) antes de publicar su ACK. En
    el sistema real, quien ejecuta esto es Claudia -- Maira nunca escribe en el almacén de
    anclaje protegido ni en los ACKs.
    """
    for _ in range(max_reintentos):
        d1 = diagnosticar_cadena_eventos(operation_id)
        if not d1["eventos"]:
            raise ValueError(f"No hay eventos para {operation_id} -- nada que anclar")
        if not d1["valida"]:
            raise CadenaEventosInvalida(f"No se puede anclar una cadena no fiable: {operation_id}")
        cabeza_1 = d1["eventos"][-1]

        d2 = diagnosticar_cadena_eventos(operation_id)
        cabeza_2 = d2["eventos"][-1] if d2["eventos"] else None
        if cabeza_2 is None or cabeza_2["_hash_evento"] != cabeza_1["_hash_evento"]:
            continue  # la cabeza cambió mientras se verificaba -- reintentar sobre la nueva
        cabeza = cabeza_2
        break
    else:
        raise RuntimeError(f"La cabeza de {operation_id} no se estabilizó tras {max_reintentos} intentos")

    campos = {
        "CHECKPOINT_ID": uuid.uuid4().hex[:12],
        "OPERATION_ID": operation_id,
        "SECUENCIA": cabeza["SECUENCIA"],
        "HASH_CABEZA": cabeza["_hash_evento"],
        "FECHA_UTC": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "KEY_ID": key_id,
        "IDENTIDAD_FIRMANTE": identidad_firmante,
        "ALGORITMO_FIRMA": algoritmo_firma,
        "VERSION_ESQUEMA": VERSION_ESQUEMA_ANCLAJE,
    }
    hash_paquete = _hash_manifiesto_sellado(operation_id)
    if hash_paquete is not None:
        campos["HASH_PAQUETE"] = hash_paquete
    else:
        campos["MOTIVO_SIN_PAQUETE"] = "no_existe_paquete_para_esta_operacion"

    campos["SIGNED_PAYLOAD_HASH"] = hashlib.sha256(_payload_canonico_checkpoint(campos)).hexdigest()
    # Marcador de firma para el prototipo -- verificación criptográfica real pendiente del
    # esquema de claves/PKI que se decida en el spike, no se valida matemáticamente aquí.
    campos["FIRMA"] = _sha256_bytes(f"{campos['SIGNED_PAYLOAD_HASH']}{key_id}".encode())

    carpeta = _carpeta_anclaje_operacion(operation_id)
    ruta = os.path.join(carpeta, f"{campos['CHECKPOINT_ID']}.json")
    fd = os.open(ruta, os.O_CREAT | os.O_EXCL | os.O_WRONLY)  # append-only: un checkpoint nunca se reescribe
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(_serializar_manifiesto(campos))

    checkpoint_persistido = _leer_checkpoint_individual(carpeta, campos["CHECKPOINT_ID"])
    if checkpoint_persistido is None or not verificar_checkpoint_estructural(checkpoint_persistido):
        raise RuntimeError(f"El checkpoint {campos['CHECKPOINT_ID']} no se pudo confirmar persistido -- no se publica ACK")

    _crear_ack_checkpoint(checkpoint_persistido)
    return campos["CHECKPOINT_ID"]


def _leer_anclaje_completo_para_pruebas(operation_id: str) -> list:
    """SOLO PARA PRUEBAS/AUDITORÍA: lee el almacén protegido completo. Maira nunca llama a esto en producción."""
    carpeta = os.path.join(_carpeta_raiz_pruebas(), NOMBRE_CARPETA_ANCLAJE, operation_id)
    if not os.path.isdir(carpeta):
        return []
    checkpoints = []
    for nombre in os.listdir(carpeta):
        if not nombre.endswith(".json"):
            continue
        with open(os.path.join(carpeta, nombre), "r", encoding="utf-8") as f:
            campos = _parsear_manifiesto(f.read())
        if _registro_bien_formado(campos, CAMPOS_CHECKPOINT_OBLIGATORIOS):
            checkpoints.append(campos)
    return checkpoints


def leer_acks_checkpoint(operation_id: str) -> list:
    """
    Única lectura que Maira necesita en producción: el ACK, entregado uno a uno en su propio
    buzón por operación -- nunca un listado abierto de todo el almacén protegido. A diferencia de
    la V2, el ACK SÍ trae lo necesario para autenticarse (ver verificar_checkpoint_estructural).
    """
    carpeta = os.path.join(_carpeta_raiz_pruebas(), NOMBRE_CARPETA_ACKS, operation_id)
    if not os.path.isdir(carpeta):
        return []
    acks = []
    for nombre in os.listdir(carpeta):
        if not nombre.endswith(".json"):
            continue
        with open(os.path.join(carpeta, nombre), "r", encoding="utf-8") as f:
            campos = _parsear_manifiesto(f.read())
        if _registro_bien_formado(campos, CAMPOS_ACK_OBLIGATORIOS):
            acks.append(campos)
    return acks


def obtener_estado_confirmado(operation_id: str) -> dict:
    """
    A diferencia de obtener_estado_actual (proyección local, PROVISIONAL), esto solo marca un
    estado como firme si existe un ACK que (a) verifica estructuralmente
    (verificar_checkpoint_estructural), (b) coincide en SECUENCIA, HASH_CABEZA y HASH_PAQUETE con
    la cabeza local, y (c) fue firmado con una clave vigente en esa fecha (alta registrada, sin
    revocación de corte anterior). Dos ACKs para la misma SECUENCIA cuya huella (HASH_CABEZA,
    HASH_PAQUETE, VERSION_ESQUEMA) difiere bloquean la proyección entera -- CheckpointConflictivo,
    nunca se elige uno en silencio.
    """
    diagnostico = diagnosticar_cadena_eventos(operation_id)
    if not diagnostico["eventos"]:
        return {"estado": None, "firme": False, "motivo": "sin eventos"}
    if not diagnostico["valida"]:
        raise CadenaEventosInvalida(
            f"Cadena de eventos de {operation_id} no es fiable: huecos={diagnostico['huecos']}, "
            f"cadena_rota={diagnostico['cadena_rota']}, ultimo_evento_ausente={diagnostico['ultimo_evento_ausente']}"
        )

    cabeza = diagnostico["eventos"][-1]
    estado_provisional = cabeza["ESTADO_NUEVO"]
    acks = leer_acks_checkpoint(operation_id)

    por_secuencia = {}
    for ack in acks:
        huella = (ack.get("HASH_CABEZA"), ack.get("HASH_PAQUETE"), ack.get("VERSION_ESQUEMA"))
        por_secuencia.setdefault(ack["SECUENCIA"], set()).add(huella)
    conflictos = {seq: huellas for seq, huellas in por_secuencia.items() if len(huellas) > 1}
    if conflictos:
        logger.error(f"Checkpoints CONFLICTIVOS para {operation_id}: {conflictos} -- posible bifurcación en el anclaje externo")
        raise CheckpointConflictivo(f"Checkpoints incompatibles para {operation_id} en secuencia(s) {list(conflictos.keys())}")

    hash_paquete_real = _hash_manifiesto_sellado(operation_id)
    for ack in acks:
        if not (ack["SECUENCIA"] == cabeza["SECUENCIA"]
                and ack["HASH_CABEZA"] == cabeza["_hash_evento"]
                and ack.get("HASH_PAQUETE") == hash_paquete_real):
            continue
        if not verificar_checkpoint_estructural(ack):
            logger.error(f"ACK {ack['ACK_ID']} de {operation_id} no verifica estructuralmente -- descartado, posible falsificación")
            continue
        if not _clave_vigente_en(ack["KEY_ID"], ack["FECHA_UTC"]):
            logger.error(f"ACK {ack['ACK_ID']} de {operation_id} firmado con clave no vigente ({ack['KEY_ID']}) en esa fecha -- no cuenta")
            continue
        return {"estado": estado_provisional, "firme": True, "checkpoint_id": ack["CHECKPOINT_ID"]}

    return {"estado": estado_provisional, "firme": False, "motivo": "sin ACK verificable que coincida con la cabeza actual y una clave vigente"}
