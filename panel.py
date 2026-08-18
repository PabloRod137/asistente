import os
import html
import secrets
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import HTMLResponse

import database

logger = logging.getLogger("asistente.panel")

router = APIRouter()
security = HTTPBasic()


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


def _tarjeta(titulo: str, valor, subtitulo: str = "") -> str:
    return f"""
    <div class="tarjeta">
        <div class="tarjeta-valor">{html.escape(str(valor))}</div>
        <div class="tarjeta-titulo">{html.escape(titulo)}</div>
        {f'<div class="tarjeta-subtitulo">{html.escape(subtitulo)}</div>' if subtitulo else ''}
    </div>"""


def _fila_documento(phone_number: str, direccion: str, nombre_archivo: str, creado_en: str) -> str:
    flecha = "Cliente → Claudia" if direccion == "entrada" else "Claudia → Cliente"
    return f"""
    <tr>
        <td>{html.escape(creado_en or '')}</td>
        <td>{html.escape(phone_number or '')}</td>
        <td>{html.escape(flecha)}</td>
        <td>{html.escape(nombre_archivo or '')}</td>
    </tr>"""


def _fila_escalado(phone_number: str, estado: str, fecha_creacion: str) -> str:
    return f"""
    <tr>
        <td>{html.escape(fecha_creacion or '')}</td>
        <td>{html.escape(phone_number or '')}</td>
        <td><span class="estado estado-{html.escape(estado or '')}">{html.escape(estado or '')}</span></td>
    </tr>"""


def _render_html(stats: dict) -> str:
    urgencia_str = ", ".join(
        f"{html.escape(str(k))}: {v}" for k, v in stats["capturas_por_urgencia"].items()
    ) or "sin datos todavía"

    filas_documentos = "".join(
        _fila_documento(*fila) for fila in stats["documentos_recientes"]
    ) or '<tr><td colspan="4">Sin actividad todavía.</td></tr>'

    filas_escalados = "".join(
        _fila_escalado(*fila) for fila in stats["escalados_recientes"]
    ) or '<tr><td colspan="3">Sin escalados todavía.</td></tr>'

    tasa_str = f"{stats['tasa_autoresolucion']}%" if stats["tasa_autoresolucion"] is not None else "—"

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Panel Maira — LexGuardian</title>
<style>
    :root {{ color-scheme: light; }}
    * {{ box-sizing: border-box; }}
    body {{
        font-family: -apple-system, "Segoe UI", Roboto, Arial, sans-serif;
        background: #f4f5f7; color: #1f2430; margin: 0; padding: 32px;
    }}
    h1 {{ font-size: 22px; margin: 0 0 4px; }}
    .subtitulo {{ color: #6b7280; margin: 0 0 28px; font-size: 14px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-bottom: 32px; }}
    .tarjeta {{
        background: #fff; border-radius: 10px; padding: 18px 20px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.08); border: 1px solid #e5e7eb;
    }}
    .tarjeta-valor {{ font-size: 28px; font-weight: 700; color: #111827; }}
    .tarjeta-titulo {{ font-size: 13px; color: #4b5563; margin-top: 4px; }}
    .tarjeta-subtitulo {{ font-size: 12px; color: #9ca3af; margin-top: 2px; }}
    section {{ background: #fff; border-radius: 10px; padding: 20px; margin-bottom: 24px; border: 1px solid #e5e7eb; }}
    section h2 {{ font-size: 15px; margin: 0 0 14px; color: #111827; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ text-align: left; padding: 8px 10px; border-bottom: 1px solid #f0f1f3; }}
    th {{ color: #6b7280; font-weight: 600; }}
    .estado {{ padding: 2px 8px; border-radius: 999px; font-size: 12px; }}
    .estado-pendiente {{ background: #fef3c7; color: #92400e; }}
    .estado-en_gestion {{ background: #dbeafe; color: #1e40af; }}
    .estado-resuelto {{ background: #d1fae5; color: #065f46; }}
    .overflow {{ overflow-x: auto; }}
</style>
</head>
<body>
    <h1>Panel Maira</h1>
    <p class="subtitulo">LexGuardian — resumen de actividad del asistente</p>

    <div class="grid">
        {_tarjeta("Conversaciones totales", stats["total_conversaciones"])}
        {_tarjeta("Conversaciones hoy", stats["conversaciones_hoy"])}
        {_tarjeta("Conversaciones últimos 7 días", stats["conversaciones_semana"])}
        {_tarjeta("Tasa de autoresolución", tasa_str, "conversaciones que no necesitaron escalado")}
        {_tarjeta("Clientes totales", stats["total_clientes"])}
        {_tarjeta("Clientes nuevos", stats["clientes_nuevos"])}
        {_tarjeta("Pendientes de teléfono", stats["clientes_pendientes_telefono"], "clientes reales sin WhatsApp vinculado")}
        {_tarjeta("Capturas estructuradas", stats["total_capturas"])}
        {_tarjeta("Capturas sin revisar", stats["capturas_pendientes"])}
        {_tarjeta("Escalados a humano", stats["total_escalados"])}
        {_tarjeta("Escalados pendientes", stats["escalados_pendientes"])}
        {_tarjeta("Documentos (carpeta puente)", stats["docs_entrada"] + stats["docs_salida"], f"{stats['docs_entrada']} de clientes, {stats['docs_salida']} de Claudia")}
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
</body>
</html>"""


@router.get("/panel", response_class=HTMLResponse)
async def ver_panel(autorizado: bool = Depends(_verificar_acceso)):
    stats = _obtener_estadisticas()
    return _render_html(stats)
