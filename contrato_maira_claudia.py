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
    os.makedirs(carpeta_paquete, exist_ok=True)

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
