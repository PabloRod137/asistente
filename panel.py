import os
import html
import secrets
import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import HTMLResponse

import database

logger = logging.getLogger("asistente.panel")

router = APIRouter(prefix="/panel")
security = HTTPBasic()

LIMITE_FILAS = 200


def _verificar_acceso(credentials: HTTPBasicCredentials = Depends(security)) -> bool:
    password_esperada = os.getenv("PANEL_PASSWORD", "")
    if not password_esperada:
        raise HTTPException(status_code=503, detail="El panel no está configurado (falta PANEL_PASSWORD en el .env).")
    if not secrets.compare_digest(credentials.password, password_esperada):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas",
            headers={"WWW-Authenticate": "Basic"},
        )
    return True


# ---------------------------------------------------------------------------
# Layout compartido
# ---------------------------------------------------------------------------

ESTILO_BASE = """
    :root { color-scheme: light; }
    * { box-sizing: border-box; }
    body {
        font-family: -apple-system, "Segoe UI", Roboto, Arial, sans-serif;
        background: #f4f5f7; color: #1f2430; margin: 0; padding: 0 32px 32px;
    }
    a { color: #2563eb; text-decoration: none; }
    a:hover { text-decoration: underline; }
    nav {
        display: flex; gap: 4px; padding: 18px 0; margin-bottom: 24px;
        border-bottom: 1px solid #e5e7eb; flex-wrap: wrap;
    }
    nav a {
        padding: 6px 12px; border-radius: 999px; font-size: 13px; font-weight: 600;
        color: #4b5563;
    }
    nav a:hover { background: #eef2ff; text-decoration: none; }
    nav a.activo { background: #111827; color: #fff; }
    h1 { font-size: 22px; margin: 0 0 4px; }
    .subtitulo { color: #6b7280; margin: 0 0 28px; font-size: 14px; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-bottom: 32px; }
    .tarjeta {
        background: #fff; border-radius: 10px; padding: 18px 20px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.08); border: 1px solid #e5e7eb;
        display: block; transition: transform 0.1s, box-shadow 0.1s;
    }
    a.tarjeta:hover { transform: translateY(-1px); box-shadow: 0 4px 10px rgba(0,0,0,0.08); text-decoration: none; }
    .tarjeta-valor { font-size: 28px; font-weight: 700; color: #111827; }
    .tarjeta-titulo { font-size: 13px; color: #4b5563; margin-top: 4px; }
    .tarjeta-subtitulo { font-size: 12px; color: #9ca3af; margin-top: 2px; }
    section { background: #fff; border-radius: 10px; padding: 20px; margin-bottom: 24px; border: 1px solid #e5e7eb; }
    section h2 { font-size: 15px; margin: 0 0 14px; color: #111827; }
    .filtros { margin-bottom: 16px; font-size: 13px; }
    .filtros a { padding: 4px 10px; border-radius: 999px; background: #f3f4f6; margin-right: 6px; color: #374151; }
    .filtros a.activo { background: #111827; color: #fff; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid #f0f1f3; vertical-align: top; }
    th { color: #6b7280; font-weight: 600; }
    .estado { padding: 2px 8px; border-radius: 999px; font-size: 12px; white-space: nowrap; }
    .estado-pendiente { background: #fef3c7; color: #92400e; }
    .estado-en_gestion { background: #dbeafe; color: #1e40af; }
    .estado-resuelto { background: #d1fae5; color: #065f46; }
    .urgencia-alta { background: #fee2e2; color: #991b1b; }
    .urgencia-media { background: #fef3c7; color: #92400e; }
    .urgencia-baja { background: #e5e7eb; color: #374151; }
    .overflow { overflow-x: auto; }
    .burbuja { max-width: 70%; padding: 10px 14px; border-radius: 12px; margin-bottom: 10px; font-size: 13px; line-height: 1.4; }
    .burbuja-user { background: #eef2ff; margin-right: auto; }
    .burbuja-assistant { background: #111827; color: #fff; margin-left: auto; }
    .burbuja-meta { font-size: 11px; color: #9ca3af; margin-top: 4px; }
    .campo { margin-bottom: 10px; font-size: 13px; }
    .campo span.etiqueta { color: #6b7280; display: inline-block; min-width: 160px; }
    .volver { font-size: 13px; margin-bottom: 16px; display: inline-block; }
"""

NAV_ITEMS = [
    ("", "Resumen"),
    ("/conversaciones", "Conversaciones"),
    ("/clientes", "Clientes"),
    ("/capturas", "Capturas"),
    ("/escalados", "Escalados"),
    ("/documentos", "Documentos"),
]


def _nav(activo: str) -> str:
    enlaces = "".join(
        f'<a href="/panel{ruta}" class="{"activo" if ruta == activo else ""}">{html.escape(etiqueta)}</a>'
        for ruta, etiqueta in NAV_ITEMS
    )
    return f"<nav>{enlaces}</nav>"


def _layout(titulo: str, subtitulo: str, cuerpo: str, activo: str = "") -> str:
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(titulo)} — Panel Maira</title>
<style>{ESTILO_BASE}</style>
</head>
<body>
    {_nav(activo)}
    <h1>{html.escape(titulo)}</h1>
    <p class="subtitulo">{html.escape(subtitulo)}</p>
    {cuerpo}
</body>
</html>"""


def _tarjeta(titulo: str, valor, subtitulo: str = "", href: str = None) -> str:
    tag = "a" if href else "div"
    href_attr = f' href="{html.escape(href)}"' if href else ""
    return f"""
    <{tag} class="tarjeta"{href_attr}>
        <div class="tarjeta-valor">{html.escape(str(valor))}</div>
        <div class="tarjeta-titulo">{html.escape(titulo)}</div>
        {f'<div class="tarjeta-subtitulo">{html.escape(subtitulo)}</div>' if subtitulo else ''}
    </{tag}>"""


def _truncar(texto: str, n: int = 90) -> str:
    if not texto:
        return ""
    texto = str(texto)
    return texto if len(texto) <= n else texto[:n].rstrip() + "…"


def _enlace_cliente(phone_number: str, etiqueta: str = None) -> str:
    etiqueta = etiqueta or phone_number
    return f'<a href="/panel/conversacion/{quote(phone_number)}">{html.escape(etiqueta)}</a>'


def _tabla_vacia(colspan: int, mensaje: str = "Sin datos todavía.") -> str:
    return f'<tr><td colspan="{colspan}">{html.escape(mensaje)}</td></tr>'


# ---------------------------------------------------------------------------
# Resumen (overview)
# ---------------------------------------------------------------------------

def _obtener_estadisticas() -> dict:
    conn = database.get_connection()
    c = conn.cursor()

    c.execute("SELECT COUNT(*) FROM conversaciones")
    total_conversaciones = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM conversaciones WHERE date(ultimo_mensaje) = date('now')")
    conversaciones_hoy = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM conversaciones WHERE date(ultimo_mensaje) >= date('now', '-7 days')")
    conversaciones_semana = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM clientes")
    total_clientes = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM clientes WHERE tipo_cliente = 'nuevo'")
    clientes_nuevos = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM clientes_importados_pendientes WHERE promovido = 0")
    clientes_pendientes_telefono = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM capturas_estructuradas")
    total_capturas = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM capturas_estructuradas WHERE revisado = 0")
    capturas_pendientes = c.fetchone()[0]

    c.execute("""
        SELECT urgencia, COUNT(*) FROM capturas_estructuradas
        WHERE urgencia IS NOT NULL GROUP BY urgencia
    """)
    capturas_por_urgencia = dict(c.fetchall())

    c.execute("SELECT COUNT(*) FROM tickets_escalados")
    total_escalados = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM tickets_escalados WHERE estado != 'resuelto'")
    escalados_pendientes = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM documentos_puente WHERE direccion = 'entrada'")
    docs_entrada = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM documentos_puente WHERE direccion = 'salida'")
    docs_salida = c.fetchone()[0]

    c.execute("""
        SELECT phone_number, direccion, nombre_archivo, creado_en FROM documentos_puente
        ORDER BY creado_en DESC LIMIT 10
    """)
    documentos_recientes = c.fetchall()

    c.execute("""
        SELECT phone_number, estado, fecha_creacion FROM tickets_escalados
        ORDER BY fecha_creacion DESC LIMIT 10
    """)
    escalados_recientes = c.fetchall()

    conn.close()

    tasa_autoresolucion = None
    if total_conversaciones > 0:
        tasa_autoresolucion = round((1 - (total_escalados / total_conversaciones)) * 100, 1)

    return {
        "total_conversaciones": total_conversaciones,
        "conversaciones_hoy": conversaciones_hoy,
        "conversaciones_semana": conversaciones_semana,
        "total_clientes": total_clientes,
        "clientes_nuevos": clientes_nuevos,
        "clientes_pendientes_telefono": clientes_pendientes_telefono,
        "total_capturas": total_capturas,
        "capturas_pendientes": capturas_pendientes,
        "capturas_por_urgencia": capturas_por_urgencia,
        "total_escalados": total_escalados,
        "escalados_pendientes": escalados_pendientes,
        "tasa_autoresolucion": tasa_autoresolucion,
        "docs_entrada": docs_entrada,
        "docs_salida": docs_salida,
        "documentos_recientes": documentos_recientes,
        "escalados_recientes": escalados_recientes,
    }


def _fila_documento_overview(phone_number: str, direccion: str, nombre_archivo: str, creado_en: str) -> str:
    flecha = "Cliente → Claudia" if direccion == "entrada" else "Claudia → Cliente"
    return f"""
    <tr>
        <td>{html.escape(creado_en or '')}</td>
        <td>{_enlace_cliente(phone_number)}</td>
        <td>{html.escape(flecha)}</td>
        <td>{html.escape(nombre_archivo or '')}</td>
    </tr>"""


def _fila_escalado_overview(phone_number: str, estado: str, fecha_creacion: str) -> str:
    return f"""
    <tr>
        <td>{html.escape(fecha_creacion or '')}</td>
        <td>{_enlace_cliente(phone_number)}</td>
        <td><span class="estado estado-{html.escape(estado or '')}">{html.escape(estado or '')}</span></td>
    </tr>"""


@router.get("", response_class=HTMLResponse)
async def ver_panel(autorizado: bool = Depends(_verificar_acceso)):
    stats = _obtener_estadisticas()

    urgencia_str = ", ".join(
        f"{html.escape(str(k))}: {v}" for k, v in stats["capturas_por_urgencia"].items()
    ) or "sin datos todavía"

    filas_documentos = "".join(
        _fila_documento_overview(*fila) for fila in stats["documentos_recientes"]
    ) or _tabla_vacia(4)

    filas_escalados = "".join(
        _fila_escalado_overview(*fila) for fila in stats["escalados_recientes"]
    ) or _tabla_vacia(3, "Sin escalados todavía.")

    tasa_str = f"{stats['tasa_autoresolucion']}%" if stats["tasa_autoresolucion"] is not None else "—"

    cuerpo = f"""
    <div class="grid">
        {_tarjeta("Conversaciones totales", stats["total_conversaciones"], href="/panel/conversaciones")}
        {_tarjeta("Conversaciones hoy", stats["conversaciones_hoy"], href="/panel/conversaciones")}
        {_tarjeta("Conversaciones últimos 7 días", stats["conversaciones_semana"], href="/panel/conversaciones")}
        {_tarjeta("Tasa de autoresolución", tasa_str, "conversaciones que no necesitaron escalado")}
        {_tarjeta("Clientes totales", stats["total_clientes"], href="/panel/clientes")}
        {_tarjeta("Clientes nuevos", stats["clientes_nuevos"], href="/panel/clientes?tipo=nuevo")}
        {_tarjeta("Pendientes de teléfono", stats["clientes_pendientes_telefono"], "clientes reales sin WhatsApp vinculado", href="/panel/pendientes_telefono")}
        {_tarjeta("Capturas estructuradas", stats["total_capturas"], href="/panel/capturas")}
        {_tarjeta("Capturas sin revisar", stats["capturas_pendientes"], href="/panel/capturas?estado=pendientes")}
        {_tarjeta("Escalados a humano", stats["total_escalados"], href="/panel/escalados")}
        {_tarjeta("Escalados pendientes", stats["escalados_pendientes"], href="/panel/escalados?estado=pendientes")}
        {_tarjeta("Documentos (carpeta puente)", stats["docs_entrada"] + stats["docs_salida"], f"{stats['docs_entrada']} de clientes, {stats['docs_salida']} de Claudia", href="/panel/documentos")}
    </div>

    <section>
        <h2>Capturas estructuradas por urgencia</h2>
        <p>{html.escape(urgencia_str)}</p>
    </section>

    <section>
        <h2>Actividad reciente — carpeta puente</h2>
        <div class="overflow">
        <table>
            <thead><tr><th>Fecha</th><th>Cliente</th><th>Dirección</th><th>Archivo</th></tr></thead>
            <tbody>{filas_documentos}</tbody>
        </table>
        </div>
    </section>

    <section>
        <h2>Escalados recientes</h2>
        <div class="overflow">
        <table>
            <thead><tr><th>Fecha</th><th>Cliente</th><th>Estado</th></tr></thead>
            <tbody>{filas_escalados}</tbody>
        </table>
        </div>
    </section>
    """
    return _layout("Panel Maira", "LexGuardian — resumen de actividad del asistente", cuerpo, activo="")


# ---------------------------------------------------------------------------
# Conversaciones
# ---------------------------------------------------------------------------

@router.get("/conversaciones", response_class=HTMLResponse)
async def ver_conversaciones(autorizado: bool = Depends(_verificar_acceso)):
    conn = database.get_connection()
    c = conn.cursor()
    c.execute(f"""
        SELECT co.phone_number, cl.nombre, co.inicio, co.ultimo_mensaje,
               (SELECT COUNT(*) FROM messages m WHERE m.phone_number = co.phone_number) AS num_mensajes
        FROM conversaciones co
        LEFT JOIN clientes cl ON cl.phone_number = co.phone_number
        ORDER BY co.ultimo_mensaje DESC
        LIMIT {LIMITE_FILAS}
    """)
    filas = c.fetchall()
    conn.close()

    filas_html = "".join(f"""
        <tr>
            <td>{_enlace_cliente(tel)}</td>
            <td>{html.escape(nombre or '—')}</td>
            <td>{html.escape(inicio or '')}</td>
            <td>{html.escape(ultimo or '')}</td>
            <td>{num}</td>
        </tr>""" for tel, nombre, inicio, ultimo, num in filas) or _tabla_vacia(5)

    cuerpo = f"""
    <section>
        <div class="overflow">
        <table>
            <thead><tr><th>Teléfono / chat_id</th><th>Nombre</th><th>Inicio</th><th>Último mensaje</th><th>Nº mensajes</th></tr></thead>
            <tbody>{filas_html}</tbody>
        </table>
        </div>
    </section>
    """
    return _layout("Conversaciones", f"{len(filas)} conversaciones (máx. {LIMITE_FILAS})", cuerpo, activo="/conversaciones")


@router.get("/conversacion/{phone_number}", response_class=HTMLResponse)
async def ver_conversacion(phone_number: str, autorizado: bool = Depends(_verificar_acceso)):
    cliente = database.get_cliente_by_phone(phone_number)

    conn = database.get_connection()
    c = conn.cursor()
    c.execute("SELECT role, content, timestamp FROM messages WHERE phone_number = ? ORDER BY timestamp ASC", (phone_number,))
    mensajes = c.fetchall()
    conn.close()

    burbujas = "".join(f"""
        <div class="burbuja burbuja-{html.escape(role)}">
            {html.escape(content or '')}
            <div class="burbuja-meta">{html.escape(role)} · {html.escape(ts or '')}</div>
        </div>""" for role, content, ts in mensajes) or "<p>Sin mensajes todavía.</p>"

    ficha = ""
    if cliente:
        ficha = f"""
        <section>
            <h2>Ficha del cliente</h2>
            <div class="campo"><span class="etiqueta">Nombre</span>{html.escape(cliente.get('nombre') or '—')}</div>
            <div class="campo"><span class="etiqueta">Expediente</span>{html.escape(cliente.get('numero_expediente') or '—')}</div>
            <div class="campo"><span class="etiqueta">Tipo</span>{html.escape(cliente.get('tipo_cliente') or '—')}</div>
            <p><a href="/panel/cliente/{quote(phone_number)}">Ver ficha completa →</a></p>
        </section>
        """
    else:
        ficha = '<section><p>Este número no corresponde a ningún cliente dado de alta todavía.</p></section>'

    cuerpo = f"""
    <a class="volver" href="/panel/conversaciones">← Volver a conversaciones</a>
    {ficha}
    <section>
        <h2>Historial completo ({len(mensajes)} mensajes)</h2>
        {burbujas}
    </section>
    """
    return _layout(f"Conversación — {phone_number}", "Historial completo de mensajes", cuerpo, activo="/conversaciones")


# ---------------------------------------------------------------------------
# Clientes
# ---------------------------------------------------------------------------

@router.get("/clientes", response_class=HTMLResponse)
async def ver_clientes(tipo: str = None, autorizado: bool = Depends(_verificar_acceso)):
    conn = database.get_connection()
    c = conn.cursor()
    if tipo:
        c.execute(f"""
            SELECT phone_number, nombre, tipo_cliente, numero_expediente, ultima_visita, total_conversaciones
            FROM clientes WHERE tipo_cliente = ? ORDER BY ultima_visita DESC LIMIT {LIMITE_FILAS}
        """, (tipo,))
    else:
        c.execute(f"""
            SELECT phone_number, nombre, tipo_cliente, numero_expediente, ultima_visita, total_conversaciones
            FROM clientes ORDER BY ultima_visita DESC LIMIT {LIMITE_FILAS}
        """)
    filas = c.fetchall()
    conn.close()

    filas_html = "".join(f"""
        <tr>
            <td><a href="/panel/cliente/{quote(tel)}">{html.escape(tel)}</a></td>
            <td>{html.escape(nombre or '—')}</td>
            <td>{html.escape(tipo_c or '—')}</td>
            <td>{html.escape(exp or '—')}</td>
            <td>{html.escape(ultima or '')}</td>
            <td>{total}</td>
        </tr>""" for tel, nombre, tipo_c, exp, ultima, total in filas) or _tabla_vacia(6)

    def _filtro(valor, etiqueta):
        activo = " activo" if tipo == valor else ""
        href = "/panel/clientes" + (f"?tipo={quote(valor)}" if valor else "")
        return f'<a href="{href}" class="{activo.strip()}">{html.escape(etiqueta)}</a>'

    filtros = f"""<div class="filtros">{_filtro(None, "Todos")}{_filtro("nuevo", "Nuevos")}{_filtro("activo", "Activos")}</div>"""

    cuerpo = f"""
    {filtros}
    <section>
        <div class="overflow">
        <table>
            <thead><tr><th>Teléfono</th><th>Nombre</th><th>Tipo</th><th>Expediente</th><th>Última visita</th><th>Nº conversaciones</th></tr></thead>
            <tbody>{filas_html}</tbody>
        </table>
        </div>
    </section>
    """
    return _layout("Clientes", f"{len(filas)} clientes (máx. {LIMITE_FILAS})", cuerpo, activo="/clientes")


@router.get("/cliente/{phone_number}", response_class=HTMLResponse)
async def ver_cliente(phone_number: str, autorizado: bool = Depends(_verificar_acceso)):
    cliente = database.get_cliente_by_phone(phone_number)
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    expedientes = database.get_expedientes_by_phone(phone_number)
    filas_expedientes = "".join(f"""
        <tr>
            <td>{html.escape(e.get('titulo') or '')}</td>
            <td>{html.escape(e.get('tipo') or '')}</td>
            <td><span class="estado estado-{html.escape(e.get('estado') or '')}">{html.escape(e.get('estado') or '')}</span></td>
            <td>{html.escape(e.get('creado_en') or '')}</td>
        </tr>""" for e in expedientes) or _tabla_vacia(4, "Sin expedientes registrados.")

    campos = [
        ("Nombre", cliente.get("nombre")),
        ("Empresa", cliente.get("empresa")),
        ("Email", cliente.get("email")),
        ("NIF/CIF", cliente.get("nif_cif")),
        ("Expediente principal", cliente.get("numero_expediente")),
        ("Tipo de cliente", cliente.get("tipo_cliente")),
        ("Idioma preferido", cliente.get("idioma_preferido")),
        ("Gestor asignado", cliente.get("gestor_asignado")),
        ("Primera visita", cliente.get("primera_visita")),
        ("Última visita", cliente.get("ultima_visita")),
        ("Total conversaciones", cliente.get("total_conversaciones")),
        ("Notas", cliente.get("notas")),
    ]
    campos_html = "".join(
        f'<div class="campo"><span class="etiqueta">{html.escape(k)}</span>{html.escape(str(v) or "—")}</div>'
        for k, v in campos
    )

    cuerpo = f"""
    <a class="volver" href="/panel/clientes">← Volver a clientes</a>
    <section>
        <h2>Ficha</h2>
        {campos_html}
        <p><a href="/panel/conversacion/{quote(phone_number)}">Ver conversación completa →</a></p>
    </section>
    <section>
        <h2>Expedientes</h2>
        <div class="overflow">
        <table>
            <thead><tr><th>Título</th><th>Tipo</th><th>Estado</th><th>Creado</th></tr></thead>
            <tbody>{filas_expedientes}</tbody>
        </table>
        </div>
    </section>
    """
    return _layout(cliente.get("nombre") or phone_number, phone_number, cuerpo, activo="/clientes")


@router.get("/pendientes_telefono", response_class=HTMLResponse)
async def ver_pendientes_telefono(autorizado: bool = Depends(_verificar_acceso)):
    pendientes = database.listar_clientes_pendientes(solo_no_promovidos=True)

    filas_html = "".join(f"""
        <tr>
            <td>{html.escape(p.get('nombre') or '')}</td>
            <td>{html.escape(p.get('nif_cif') or '—')}</td>
            <td>{html.escape(p.get('numero_expediente') or '—')}</td>
            <td>{html.escape(p.get('tipo_cliente') or '—')}</td>
            <td>{html.escape(p.get('creado_en') or '')}</td>
        </tr>""" for p in pendientes) or _tabla_vacia(5, "No hay clientes pendientes de vincular teléfono.")

    cuerpo = f"""
    <a class="volver" href="/panel">← Volver al resumen</a>
    <section>
        <p>Clientes reales importados sin número de WhatsApp todavía. Cuando alguien nuevo escribe y da su nombre, Maira intenta enlazarlo aquí automáticamente (con confirmación).</p>
        <div class="overflow">
        <table>
            <thead><tr><th>Nombre</th><th>NIF/CIF</th><th>Expediente</th><th>Tipo</th><th>Importado</th></tr></thead>
            <tbody>{filas_html}</tbody>
        </table>
        </div>
    </section>
    """
    return _layout("Pendientes de teléfono", f"{len(pendientes)} clientes en espera", cuerpo, activo="/clientes")


# ---------------------------------------------------------------------------
# Capturas estructuradas
# ---------------------------------------------------------------------------

@router.get("/capturas", response_class=HTMLResponse)
async def ver_capturas(estado: str = None, autorizado: bool = Depends(_verificar_acceso)):
    conn = database.get_connection()
    c = conn.cursor()
    if estado == "pendientes":
        c.execute(f"""
            SELECT id, phone_number, canal, cliente_probable, area_probable, asunto, urgencia,
                   servicio_sugerido, expediente_probable, confianza, mensaje_original, creado_en
            FROM capturas_estructuradas WHERE revisado = 0 ORDER BY creado_en DESC LIMIT {LIMITE_FILAS}
        """)
    else:
        c.execute(f"""
            SELECT id, phone_number, canal, cliente_probable, area_probable, asunto, urgencia,
                   servicio_sugerido, expediente_probable, confianza, mensaje_original, creado_en
            FROM capturas_estructuradas ORDER BY creado_en DESC LIMIT {LIMITE_FILAS}
        """)
    filas = c.fetchall()
    conn.close()

    filas_html = "".join(f"""
        <tr>
            <td>{html.escape(creado or '')}</td>
            <td>{_enlace_cliente(tel)}</td>
            <td>{html.escape(canal or '')}</td>
            <td>{html.escape(cliente_p or '—')}</td>
            <td>{html.escape(area or '—')}</td>
            <td title="{html.escape(mensaje_orig or '')}">{html.escape(_truncar(asunto, 60))}</td>
            <td><span class="estado urgencia-{html.escape(urg or '')}">{html.escape(urg or '—')}</span></td>
            <td>{html.escape(exp or '—')}</td>
            <td>{conf if conf is not None else '—'}</td>
        </tr>""" for id_, tel, canal, cliente_p, area, asunto, urg, serv, exp, conf, mensaje_orig, creado in filas) or _tabla_vacia(9)

    filtros = f"""<div class="filtros">
        <a href="/panel/capturas" class="{'activo' if not estado else ''}">Todas</a>
        <a href="/panel/capturas?estado=pendientes" class="{'activo' if estado == 'pendientes' else ''}">Sin revisar</a>
    </div>"""

    cuerpo = f"""
    {filtros}
    <section>
        <div class="overflow">
        <table>
            <thead><tr><th>Fecha</th><th>Cliente</th><th>Canal</th><th>Cliente probable</th><th>Área</th><th>Asunto</th><th>Urgencia</th><th>Expediente</th><th>Confianza</th></tr></thead>
            <tbody>{filas_html}</tbody>
        </table>
        </div>
    </section>
    """
    return _layout("Capturas estructuradas", f"{len(filas)} capturas (máx. {LIMITE_FILAS})", cuerpo, activo="/capturas")


# ---------------------------------------------------------------------------
# Escalados
# ---------------------------------------------------------------------------

@router.get("/escalados", response_class=HTMLResponse)
async def ver_escalados(estado: str = None, autorizado: bool = Depends(_verificar_acceso)):
    conn = database.get_connection()
    c = conn.cursor()
    if estado == "pendientes":
        c.execute(f"""
            SELECT phone_number, mensaje_cliente, respuesta_maira, estado, fecha_creacion, fecha_resolucion
            FROM tickets_escalados WHERE estado != 'resuelto' ORDER BY fecha_creacion DESC LIMIT {LIMITE_FILAS}
        """)
    else:
        c.execute(f"""
            SELECT phone_number, mensaje_cliente, respuesta_maira, estado, fecha_creacion, fecha_resolucion
            FROM tickets_escalados ORDER BY fecha_creacion DESC LIMIT {LIMITE_FILAS}
        """)
    filas = c.fetchall()
    conn.close()

    filas_html = "".join(f"""
        <tr>
            <td>{html.escape(creado or '')}</td>
            <td>{_enlace_cliente(tel)}</td>
            <td title="{html.escape(msg or '')}">{html.escape(_truncar(msg, 70))}</td>
            <td><span class="estado estado-{html.escape(est or '')}">{html.escape(est or '')}</span></td>
        </tr>""" for tel, msg, resp, est, creado, resuelto in filas) or _tabla_vacia(4, "Sin escalados todavía.")

    filtros = f"""<div class="filtros">
        <a href="/panel/escalados" class="{'activo' if not estado else ''}">Todos</a>
        <a href="/panel/escalados?estado=pendientes" class="{'activo' if estado == 'pendientes' else ''}">Pendientes</a>
    </div>"""

    cuerpo = f"""
    {filtros}
    <section>
        <div class="overflow">
        <table>
            <thead><tr><th>Fecha</th><th>Cliente</th><th>Mensaje del cliente</th><th>Estado</th></tr></thead>
            <tbody>{filas_html}</tbody>
        </table>
        </div>
    </section>
    """
    return _layout("Escalados a humano", f"{len(filas)} escalados (máx. {LIMITE_FILAS})", cuerpo, activo="/escalados")


# ---------------------------------------------------------------------------
# Documentos (carpeta puente)
# ---------------------------------------------------------------------------

@router.get("/documentos", response_class=HTMLResponse)
async def ver_documentos(autorizado: bool = Depends(_verificar_acceso)):
    conn = database.get_connection()
    c = conn.cursor()
    c.execute(f"""
        SELECT phone_number, direccion, nombre_archivo, mime_type, creado_en
        FROM documentos_puente ORDER BY creado_en DESC LIMIT {LIMITE_FILAS}
    """)
    filas = c.fetchall()
    conn.close()

    filas_html = "".join(f"""
        <tr>
            <td>{html.escape(creado or '')}</td>
            <td>{_enlace_cliente(tel)}</td>
            <td>{'Cliente → Claudia' if direccion == 'entrada' else 'Claudia → Cliente'}</td>
            <td>{html.escape(nombre or '')}</td>
            <td>{html.escape(mime or '—')}</td>
        </tr>""" for tel, direccion, nombre, mime, creado in filas) or _tabla_vacia(5)

    cuerpo = f"""
    <section>
        <div class="overflow">
        <table>
            <thead><tr><th>Fecha</th><th>Cliente</th><th>Dirección</th><th>Archivo</th><th>Tipo</th></tr></thead>
            <tbody>{filas_html}</tbody>
        </table>
        </div>
    </section>
    """
    return _layout("Documentos — carpeta puente", f"{len(filas)} documentos (máx. {LIMITE_FILAS})", cuerpo, activo="/documentos")
