import sqlite3
import os
import logging
from datetime import datetime

logger = logging.getLogger("asistente.database")

DB_PATH = os.getenv("DB_PATH", "chatbot.db")

def get_connection():
    """
    Retorna una nueva conexión SQLite3 configurada con modo WAL y busy_timeout.
    Se utiliza una conexión nueva por llamada/hilo para evitar condiciones de carrera.
    """
    db_path_dynamic = os.getenv("DB_PATH", "chatbot.db")
    conn = sqlite3.connect(db_path_dynamic)
    # Habilitar Write-Ahead Logging (WAL) para permitir lecturas concurrentes sin bloquear escrituras
    conn.execute("PRAGMA journal_mode=WAL;")
    # Esperar hasta 5000 ms en caso de bloqueo antes de lanzar excepción
    conn.execute("PRAGMA busy_timeout=5000;")
    return conn

def migrar_facturas_autoincrement(conn):
    """
    Comprueba si la tabla 'facturas' existe y si su id tiene AUTOINCREMENT.
    Si no lo tiene, migra la tabla de forma segura e idempotente.
    """
    cursor = conn.cursor()
    cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='facturas'")
    row = cursor.fetchone()
    if row:
        sql_schema = row[0]
        if "autoincrement" not in sql_schema.lower():
            logger.info("Migrando la tabla 'facturas' para habilitar AUTOINCREMENT...")
            cursor.execute("ALTER TABLE facturas RENAME TO facturas_old;")
            cursor.execute('''
                CREATE TABLE facturas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    destinatario TEXT NOT NULL,
                    cif TEXT NOT NULL,
                    concepto TEXT NOT NULL,
                    importe REAL NOT NULL,
                    fecha DATETIME DEFAULT CURRENT_TIMESTAMP
                );
            ''')
            cursor.execute('''
                INSERT INTO facturas (id, destinatario, cif, concepto, importe, fecha)
                SELECT id, destinatario, cif, concepto, importe, fecha FROM facturas_old;
            ''')
            cursor.execute("DROP TABLE facturas_old;")
            conn.commit()
            logger.info("Migración de 'facturas' completada con éxito.")

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    
    # Tabla de mensajes
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone_number TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Tabla de citas (Agenda)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS citas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone_number TEXT NOT NULL,
            event_id TEXT NOT NULL,
            fecha TEXT NOT NULL,
            servicio TEXT,
            estado TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Tabla de facturas
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS facturas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            destinatario TEXT NOT NULL,
            cif TEXT NOT NULL,
            concepto TEXT NOT NULL,
            importe REAL NOT NULL,
            fecha DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Tabla de conversaciones
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS conversaciones (
            phone_number TEXT PRIMARY KEY,
            inicio DATETIME DEFAULT CURRENT_TIMESTAMP,
            ultimo_mensaje DATETIME DEFAULT CURRENT_TIMESTAMP,
            resumen_enviado INTEGER DEFAULT 0
        )
    ''')
    
    # Intentar añadir la columna resumen_texto a la tabla conversaciones si no existe
    try:
        cursor.execute("ALTER TABLE conversaciones ADD COLUMN resumen_texto TEXT")
    except sqlite3.OperationalError:
        pass

    # Tabla de clientes
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS clientes (
            phone_number TEXT PRIMARY KEY,
            nombre TEXT,
            empresa TEXT,
            email TEXT,
            notas TEXT,
            primera_visita DATETIME DEFAULT CURRENT_TIMESTAMP,
            ultima_visita DATETIME DEFAULT CURRENT_TIMESTAMP,
            total_conversaciones INTEGER DEFAULT 1,
            numero_expediente TEXT,
            tipo_cliente TEXT DEFAULT 'nuevo',
            nif_cif TEXT,
            fecha_alta DATE,
            gestor_asignado TEXT,
            carpeta_sharepoint TEXT,
            idioma_preferido TEXT DEFAULT 'es'
        )
    ''')

    # Migraciones para la tabla clientes
    columnas_clientes = [
        ("numero_expediente", "TEXT"),
        ("tipo_cliente", "TEXT DEFAULT 'nuevo'"),
        ("nif_cif", "TEXT"),
        ("fecha_alta", "DATE"),
        ("gestor_asignado", "TEXT"),
        ("carpeta_sharepoint", "TEXT"),
        ("idioma_preferido", "TEXT DEFAULT 'es'")
    ]
    for col_name, col_def in columnas_clientes:
        try:
            cursor.execute(f"ALTER TABLE clientes ADD COLUMN {col_name} {col_def}")
        except sqlite3.OperationalError:
            pass

    # Tabla de tickets_escalados
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tickets_escalados (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone_number TEXT,
            mensaje_cliente TEXT,
            respuesta_maira TEXT,
            estado TEXT DEFAULT 'pendiente',
            fecha_creacion DATETIME DEFAULT CURRENT_TIMESTAMP,
            fecha_resolucion DATETIME
        )
    ''')

    # Tabla agenda_interna
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS agenda_interna (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo TEXT NOT NULL,
            titulo TEXT NOT NULL,
            descripcion TEXT,
            fecha DATE,
            hora TIME,
            completado INTEGER DEFAULT 0,
            creado_en DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Tabla plazos_fiscales
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS plazos_fiscales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            modelo TEXT NOT NULL,
            descripcion TEXT,
            cliente TEXT,
            fecha_limite DATE NOT NULL,
            completado INTEGER DEFAULT 0,
            phone_number TEXT,
            recordatorio_enviado INTEGER DEFAULT 0
        )
    ''')

    # Migraciones para plazos_fiscales
    columnas_plazos = [
        ("phone_number", "TEXT"),
        ("recordatorio_enviado", "INTEGER DEFAULT 0")
    ]
    for col_name, col_def in columnas_plazos:
        try:
            cursor.execute(f"ALTER TABLE plazos_fiscales ADD COLUMN {col_name} {col_def}")
        except sqlite3.OperationalError:
            pass

    # Tabla documentos_pendientes
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS documentos_pendientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone_number TEXT NOT NULL,
            descripcion TEXT NOT NULL,
            fecha_solicitud DATE NOT NULL,
            fecha_limite DATE,
            veces_recordado INTEGER DEFAULT 0,
            ultimo_recordatorio_fecha DATE,
            estado TEXT DEFAULT 'pendiente',
            creado_en DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Tabla gastos_tickets
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS gastos_tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone_number TEXT NOT NULL,
            cif_emisor TEXT,
            emisor TEXT NOT NULL,
            fecha TEXT,
            base_imponible REAL NOT NULL,
            porcentaje_iva REAL NOT NULL,
            cuota_iva REAL NOT NULL,
            total REAL NOT NULL,
            ruta_imagen TEXT,
            creado_en DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Tabla sesiones_activas (Fase 5.2 - Persistencia de sesiones en SQLite)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sesiones_activas (
            phone_number TEXT NOT NULL,
            tipo_sesion TEXT NOT NULL,
            datos_json TEXT NOT NULL,
            actualizado_en DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (phone_number, tipo_sesion)
        )
    ''')

    # Tabla expedientes (Fase 7.1)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS expedientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone_number TEXT NOT NULL,
            tipo TEXT NOT NULL,              -- 'fiscal' | 'laboral' | 'mercantil' | 'civil' | 'compliance' | 'general'
            titulo TEXT NOT NULL,
            estado TEXT DEFAULT 'recibido',  -- 'recibido' | 'en_gestion' | 'resuelto'
            gestor_asignado TEXT,
            ruta_sharepoint TEXT,
            creado_en DATETIME DEFAULT CURRENT_TIMESTAMP,
            actualizado_en DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Tabla clientes_importados_pendientes (Fase 9.1 - clientes reales importados sin teléfono,
    # a la espera de que escriban a Maira alguna vez para completarse solos)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS clientes_importados_pendientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            nif_cif TEXT,
            numero_expediente TEXT,
            notas TEXT,
            carpeta_sharepoint TEXT,
            tipo_cliente TEXT DEFAULT 'activo',
            idioma_preferido TEXT DEFAULT 'es',
            promovido INTEGER DEFAULT 0,
            telefono_asignado TEXT,
            creado_en DATETIME DEFAULT CURRENT_TIMESTAMP,
            promovido_en DATETIME
        )
    ''')

    # Tabla capturas_estructuradas (Fase 8.1 - captura estructurada universal de Maira)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS capturas_estructuradas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone_number TEXT NOT NULL,
            canal TEXT NOT NULL,             -- 'whatsapp_texto' | 'whatsapp_audio' | 'chat_web'
            cliente_probable TEXT,
            area_probable TEXT,
            asunto TEXT,
            urgencia TEXT,
            solicitud TEXT,
            documentos_mencionados TEXT,
            servicio_sugerido TEXT,
            expediente_probable TEXT,
            confianza INTEGER,
            mensaje_original TEXT,
            revisado INTEGER DEFAULT 0,
            creado_en DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Tabla documentos_puente (carpeta puente Maira <-> Claudia <-> Alberto): registra cada
    # documento que entra (cliente -> Claudia) o sale (Claudia -> cliente) de la carpeta puente.
    # UNIQUE en ruta_logica: sirve como mecanismo de idempotencia para el job periódico que
    # revisa la carpeta de salida, para no reenviar dos veces el mismo archivo al cliente.
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS documentos_puente (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone_number TEXT NOT NULL,
            direccion TEXT NOT NULL,         -- 'entrada' (cliente -> Claudia) | 'salida' (Claudia -> cliente)
            ruta_logica TEXT NOT NULL UNIQUE,
            nombre_archivo TEXT NOT NULL,
            mime_type TEXT,
            creado_en DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    conn.commit()
    
    # Ejecutar la migración de autoincrement sobre la tabla facturas si fuese necesario
    migrar_facturas_autoincrement(conn)
    
    conn.close()

def save_message(phone_number: str, role: str, content: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO messages (phone_number, role, content)
        VALUES (?, ?, ?)
    ''', (phone_number, role, content))
    conn.commit()
    conn.close()

def actualizar_ultimo_mensaje_usuario(phone_number: str, nuevo_contenido: str):
    """
    Sustituye el contenido del último mensaje 'user' guardado para este teléfono. Se usa tras
    transcribir una nota de voz: al llegar el audio se guarda un placeholder tipo
    '[Envía Nota de Voz]' (no se conoce el texto todavía), y en cuanto se obtiene la
    transcripción real se reemplaza aquí — así el historial de conversación conserva el
    contenido real para turnos futuros en vez del placeholder.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE messages SET content = ?
        WHERE id = (
            SELECT id FROM messages
            WHERE phone_number = ? AND role = 'user'
            ORDER BY id DESC LIMIT 1
        )
    ''', (nuevo_contenido, phone_number))
    conn.commit()
    conn.close()

def get_history(phone_number: str, limit: int = 10) -> list:
    max_limit = min(limit, 10)
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT role, content FROM messages
        WHERE phone_number = ?
        ORDER BY timestamp DESC
        LIMIT ?
    ''', (phone_number, max_limit))
    rows = cursor.fetchall()
    conn.close()
    
    rows.reverse()
    return [{"role": row[0], "content": row[1]} for row in rows]

# Funciones de utilidad para citas (Agenda)
def save_cita(phone_number: str, event_id: str, fecha: str, servicio: str, estado: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO citas (phone_number, event_id, fecha, servicio, estado)
        VALUES (?, ?, ?, ?, ?)
    ''', (phone_number, event_id, fecha, servicio, estado))
    conn.commit()
    conn.close()

def get_active_cita(phone_number: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT event_id, fecha, servicio, estado FROM citas
        WHERE phone_number = ? AND estado = 'confirmada'
        ORDER BY timestamp DESC LIMIT 1
    ''', (phone_number,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"event_id": row[0], "fecha": row[1], "servicio": row[2], "estado": row[3]}
    return None

def update_cita_estado(event_id: str, estado: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE citas SET estado = ? WHERE event_id = ?
    ''', (estado, event_id))
    conn.commit()
    conn.close()

# Funciones de utilidad para facturas
def get_next_factura_numero() -> int:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM facturas')
    count = cursor.fetchone()[0]
    conn.close()
    return count + 1

def save_factura(destinatario: str, cif: str, concepto: str, importe: float) -> int:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO facturas (destinatario, cif, concepto, importe)
        VALUES (?, ?, ?, ?)
    ''', (destinatario, cif, concepto, importe))
    factura_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return factura_id

# Funciones de utilidad para gastos (Tickets)
def save_gasto(phone_number: str, emisor: str, cif_emisor: str, fecha: str, base_imponible: float, porcentaje_iva: int, cuota_iva: float, total: float, ruta_imagen: str) -> int:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO gastos_tickets (phone_number, emisor, cif_emisor, fecha, base_imponible, porcentaje_iva, cuota_iva, total, ruta_imagen)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (phone_number, emisor, cif_emisor, fecha, base_imponible, porcentaje_iva, cuota_iva, total, ruta_imagen))
    gasto_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return gasto_id

def get_gastos_by_cif(cif_emisor: str, limit: int = 1000) -> list:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT emisor, cif_emisor, fecha, base_imponible, porcentaje_iva, cuota_iva, total, ruta_imagen, creado_en FROM gastos_tickets
        WHERE UPPER(cif_emisor) = ?
        ORDER BY fecha DESC, creado_en DESC
        LIMIT ?
    ''', (cif_emisor.strip().upper(), limit))
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "emisor": row[0],
            "cif_emisor": row[1],
            "fecha": row[2],
            "base_imponible": row[3],
            "porcentaje_iva": row[4],
            "cuota_iva": row[5],
            "total": row[6],
            "ruta_imagen": row[7],
            "creado_en": row[8]
        }
        for row in rows
    ]

# Funciones de utilidad para clientes (CRM)
def get_cliente_by_phone(phone_number: str) -> dict | None:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT phone_number, nombre, empresa, email, notas, primera_visita, ultima_visita,
               total_conversaciones, numero_expediente, tipo_cliente, nif_cif, fecha_alta, gestor_asignado,
               carpeta_sharepoint, idioma_preferido
        FROM clientes WHERE phone_number = ?
    ''', (phone_number,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {
            "phone_number": row[0],
            "nombre": row[1],
            "empresa": row[2],
            "email": row[3],
            "notas": row[4],
            "primera_visita": row[5],
            "ultima_visita": row[6],
            "total_conversaciones": row[7],
            "numero_expediente": row[8],
            "tipo_cliente": row[9] or "nuevo",
            "nif_cif": row[10],
            "fecha_alta": row[11],
            "gestor_asignado": row[12],
            "carpeta_sharepoint": row[13],
            "idioma_preferido": row[14] or "es"
        }
    return None

def get_clientes_nuevos() -> list:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT phone_number, nombre, empresa, email, nif_cif, fecha_alta, primera_visita, ultima_visita
        FROM clientes
        WHERE (tipo_cliente IS NULL OR tipo_cliente = 'nuevo') AND (nombre IS NOT NULL AND nombre != '')
        ORDER BY ultima_visita DESC
    ''')
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "phone_number": row[0],
            "nombre": row[1],
            "empresa": row[2],
            "email": row[3],
            "nif_cif": row[4],
            "fecha_alta": row[5],
            "primera_visita": row[6],
            "ultima_visita": row[7]
        }
        for row in rows
    ]

def activar_cliente(phone_number: str, numero_expediente: str, nombre_opcional: str = None, gestor_asignado: str = None) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT nombre FROM clientes WHERE phone_number = ?", (phone_number,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return False
        
    current_nombre = row[0]
    nuevo_nombre = nombre_opcional if nombre_opcional else current_nombre
    
    cursor.execute('''
        UPDATE clientes
        SET tipo_cliente = 'activo',
            numero_expediente = ?,
            nombre = COALESCE(?, nombre),
            gestor_asignado = COALESCE(?, gestor_asignado)
        WHERE phone_number = ?
    ''', (numero_expediente, nuevo_nombre, gestor_asignado, phone_number))
    
    conn.commit()
    conn.close()
    return True

def normalizar_telefono(phone_number: str) -> str:
    """
    Normaliza el número de teléfono eliminando espacios, guiones, paréntesis y signos +.
    Si tiene 9 dígitos (formato español), añade el prefijo '34'.
    """
    if not phone_number:
        return ""
    clean = "".join([c for c in phone_number if c.isdigit()])
    if len(clean) == 9 and clean[0] in ['6', '7', '8', '9']:
        clean = "34" + clean
    return clean

# Funciones de utilidad para clientes importados sin teléfono (Fase 9.1)
def insertar_cliente_pendiente(nombre: str, nif_cif: str = None, numero_expediente: str = None,
                                notas: str = None, carpeta_sharepoint: str = None,
                                tipo_cliente: str = "activo", idioma_preferido: str = "es") -> int:
    """
    Crea (o actualiza si ya existía sin promover) un cliente en la lista de espera. Es idempotente
    por nombre: reejecutar la importación con el mismo Excel (o una versión actualizada) no
    duplica filas — actualiza la existente. Sin esto, dos ejecuciones dejarían dos pendientes con
    el mismo nombre, y client_matching.buscar_coincidencia los trataría como un empate ambiguo,
    dejando de proponer la vinculación automática para ese cliente.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id FROM clientes_importados_pendientes WHERE promovido = 0 AND nombre = ?
    ''', (nombre,))
    existente = cursor.fetchone()

    if existente:
        pendiente_id = existente[0]
        cursor.execute('''
            UPDATE clientes_importados_pendientes
            SET nif_cif = ?, numero_expediente = ?, notas = ?, carpeta_sharepoint = ?,
                tipo_cliente = ?, idioma_preferido = ?
            WHERE id = ?
        ''', (nif_cif, numero_expediente, notas, carpeta_sharepoint, tipo_cliente, idioma_preferido, pendiente_id))
    else:
        cursor.execute('''
            INSERT INTO clientes_importados_pendientes
                (nombre, nif_cif, numero_expediente, notas, carpeta_sharepoint, tipo_cliente, idioma_preferido)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (nombre, nif_cif, numero_expediente, notas, carpeta_sharepoint, tipo_cliente, idioma_preferido))
        pendiente_id = cursor.lastrowid

    conn.commit()
    conn.close()
    return pendiente_id

def listar_clientes_pendientes(solo_no_promovidos: bool = True) -> list:
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    if solo_no_promovidos:
        cursor.execute('SELECT * FROM clientes_importados_pendientes WHERE promovido = 0')
    else:
        cursor.execute('SELECT * FROM clientes_importados_pendientes')
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def promover_cliente_pendiente(pendiente_id: int, phone_number: str) -> dict | None:
    """
    Traslada un cliente de la lista de espera a la tabla real 'clientes', ya con el teléfono
    que se acaba de confirmar por WhatsApp, y marca el registro de espera como promovido
    (se conserva para auditoría, no se borra). Devuelve la ficha final del cliente o None si
    el pendiente_id no existe o ya estaba promovido.

    La "reclamación" del pendiente (el UPDATE con WHERE promovido = 0) se hace ANTES de tocar
    la tabla clientes y sin commit intermedio, para que sea atómica: si dos peticiones casi
    simultáneas intentan promover el mismo pendiente_id, SQLite serializa la escritura y solo
    una de ellas verá rowcount = 1 — la otra ve 0 y aborta sin crear un cliente duplicado.
    """
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute('SELECT * FROM clientes_importados_pendientes WHERE id = ?', (pendiente_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return None
    pendiente = dict(row)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    fecha_alta = datetime.now().strftime("%Y-%m-%d")

    cursor.execute('''
        UPDATE clientes_importados_pendientes
        SET promovido = 1, telefono_asignado = ?, promovido_en = ?
        WHERE id = ? AND promovido = 0
    ''', (phone_number, now_str, pendiente_id))

    if cursor.rowcount == 0:
        conn.rollback()
        conn.close()
        logger.warning(f"Cliente pendiente #{pendiente_id} ya había sido promovido por otra petición concurrente.")
        return None

    cursor.execute('SELECT phone_number FROM clientes WHERE phone_number = ?', (phone_number,))
    ya_existe = cursor.fetchone() is not None

    if ya_existe:
        cursor.execute('''
            UPDATE clientes SET
                nombre = ?, nif_cif = ?, numero_expediente = ?, notas = ?, carpeta_sharepoint = ?,
                tipo_cliente = ?, idioma_preferido = ?, fecha_alta = ?, ultima_visita = ?
            WHERE phone_number = ?
        ''', (
            pendiente["nombre"], pendiente["nif_cif"], pendiente["numero_expediente"], pendiente["notas"],
            pendiente["carpeta_sharepoint"], pendiente["tipo_cliente"], pendiente["idioma_preferido"],
            fecha_alta, now_str, phone_number
        ))
    else:
        cursor.execute('''
            INSERT INTO clientes (
                phone_number, nombre, nif_cif, numero_expediente, notas, carpeta_sharepoint,
                tipo_cliente, idioma_preferido, fecha_alta, primera_visita, ultima_visita, total_conversaciones
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        ''', (
            phone_number, pendiente["nombre"], pendiente["nif_cif"], pendiente["numero_expediente"],
            pendiente["notas"], pendiente["carpeta_sharepoint"], pendiente["tipo_cliente"],
            pendiente["idioma_preferido"], fecha_alta, now_str, now_str
        ))

    conn.commit()

    cursor.execute('SELECT * FROM clientes WHERE phone_number = ?', (phone_number,))
    resultado = cursor.fetchone()
    conn.close()
    logger.info(f"Cliente pendiente #{pendiente_id} ({pendiente['nombre']}) promovido con teléfono {phone_number}.")
    return dict(resultado) if resultado else None

# Funciones de utilidad para documentos pendientes
def save_documento_pendiente(phone_number: str, descripcion: str, fecha_limite: str) -> int:
    phone_norm = normalizar_telefono(phone_number)
    conn = get_connection()
    cursor = conn.cursor()
    hoy_str = datetime.now().strftime("%Y-%m-%d")
    cursor.execute('''
        INSERT INTO documentos_pendientes (phone_number, descripcion, fecha_solicitud, fecha_limite, estado)
        VALUES (?, ?, ?, ?, 'pendiente')
    ''', (phone_norm, descripcion, hoy_str, fecha_limite))
    doc_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return doc_id

def marcar_documento_recibido(doc_id: int) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE documentos_pendientes SET estado = 'recibido' WHERE id = ?", (doc_id,))
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return affected > 0

def get_documentos_pendientes_a_recordar(dias_antes: int = 3) -> list:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, phone_number, descripcion, fecha_solicitud, fecha_limite, veces_recordado, ultimo_recordatorio_fecha
        FROM documentos_pendientes
        WHERE estado = 'pendiente'
          AND fecha_limite IS NOT NULL
          AND date(fecha_limite) >= date('now', 'start of day')
          AND date(fecha_limite) <= date('now', 'start of day', '+' || ? || ' days')
          AND (ultimo_recordatorio_fecha IS NULL OR date(ultimo_recordatorio_fecha) < date('now', 'start of day'))
    ''', (dias_antes,))
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "id": row[0],
            "phone_number": row[1],
            "descripcion": row[2],
            "fecha_solicitud": row[3],
            "fecha_limite": row[4],
            "veces_recordado": row[5],
            "ultimo_recordatorio_fecha": row[6]
        }
        for row in rows
    ]

def incrementar_recordatorio_documento(doc_id: int) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    hoy_str = datetime.now().strftime("%Y-%m-%d")
    cursor.execute('''
        UPDATE documentos_pendientes
        SET veces_recordado = veces_recordado + 1,
            ultimo_recordatorio_fecha = ?
        WHERE id = ?
    ''', (hoy_str, doc_id))
    conn.commit()
    conn.close()
    return True

def get_todos_documentos_pendientes() -> list:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT d.id, d.phone_number, d.descripcion, d.fecha_solicitud, d.fecha_limite, d.veces_recordado, d.ultimo_recordatorio_fecha, d.estado, c.nombre
        FROM documentos_pendientes d
        LEFT JOIN clientes c ON d.phone_number = c.phone_number
        WHERE d.estado = 'pendiente'
        ORDER BY d.fecha_limite ASC
    ''')
    rows = cursor.fetchall()
    conn.close()
    hoy_str = datetime.now().strftime("%Y-%m-%d")
    
    result = []
    for r in rows:
        fecha_lim = r[4]
        vencido = False
        if fecha_lim and fecha_lim < hoy_str:
            vencido = True
        result.append({
            "id": r[0],
            "phone_number": r[1],
            "descripcion": r[2],
            "fecha_solicitud": r[3],
            "fecha_limite": r[4],
            "veces_recordado": r[5],
            "ultimo_recordatorio_fecha": r[6],
            "estado": r[7],
            "cliente_nombre": r[8] or r[1],
            "vencido": vencido
        })
    return result

def get_plazos_fiscales_a_recordar_cliente(dias_antes: int = 7) -> list:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, modelo, descripcion, cliente, fecha_limite, phone_number
        FROM plazos_fiscales
        WHERE completado = 0
          AND phone_number IS NOT NULL AND phone_number != ''
          AND recordatorio_enviado = 0
          AND date(fecha_limite) >= date('now', 'start of day')
          AND date(fecha_limite) <= date('now', 'start of day', '+' || ? || ' days')
    ''', (dias_antes,))
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "id": row[0],
            "modelo": row[1],
            "descripcion": row[2] or "Sin descripción",
            "cliente": row[3] or "Cliente",
            "fecha_limite": row[4],
            "phone_number": row[5]
        }
        for row in rows
    ]

def marcar_plazo_fiscal_recordado(plazo_id: int) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE plazos_fiscales SET recordatorio_enviado = 1 WHERE id = ?", (plazo_id,))
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return affected > 0

# Funciones de utilidad para sesiones activas (Fase 5.2)
import json

def save_session(phone_number: str, tipo_sesion: str, data: dict):
    conn = get_connection()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    datos_str = json.dumps(data)
    cursor.execute('''
        INSERT INTO sesiones_activas (phone_number, tipo_sesion, datos_json, actualizado_en)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(phone_number, tipo_sesion) DO UPDATE SET
            datos_json = excluded.datos_json,
            actualizado_en = excluded.actualizado_en
    ''', (phone_number, tipo_sesion, datos_str, now_str))
    conn.commit()
    conn.close()

def get_session(phone_number: str, tipo_sesion: str) -> dict | None:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT datos_json FROM sesiones_activas
        WHERE phone_number = ? AND tipo_sesion = ?
    ''', (phone_number, tipo_sesion))
    row = cursor.fetchone()
    conn.close()
    if row:
        try:
            return json.loads(row[0])
        except Exception:
            return None
    return None

def delete_session(phone_number: str, tipo_sesion: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        DELETE FROM sesiones_activas
        WHERE phone_number = ? AND tipo_sesion = ?
    ''', (phone_number, tipo_sesion))
    conn.commit()
    conn.close()

def clear_expired_sessions(tipo_sesion: str = None, timeout_seconds: int = 900):
    conn = get_connection()
    cursor = conn.cursor()
    if tipo_sesion:
        cursor.execute('''
            DELETE FROM sesiones_activas
            WHERE tipo_sesion = ? AND strftime('%s', 'now') - strftime('%s', actualizado_en) > ?
        ''', (tipo_sesion, timeout_seconds))
    else:
        cursor.execute('''
            DELETE FROM sesiones_activas
            WHERE strftime('%s', 'now') - strftime('%s', actualizado_en) > ?
        ''', (timeout_seconds,))
    count = cursor.rowcount
    conn.commit()
    conn.close()
    if count > 0:
        logger.info(f"Purga de sesiones expiradas: eliminadas {count} sesión(es) antiguas.")
    return count

# --- Funciones de Gestión de Expedientes (Fase 7) ---
def crear_expediente(phone_number: str, tipo: str, titulo: str, gestor_asignado: str = None, ruta_sharepoint: str = None) -> int:
    conn = get_connection()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute('''
        INSERT INTO expedientes (phone_number, tipo, titulo, estado, gestor_asignado, ruta_sharepoint, creado_en, actualizado_en)
        VALUES (?, ?, ?, 'recibido', ?, ?, ?, ?)
    ''', (phone_number, tipo, titulo, gestor_asignado, ruta_sharepoint, now_str, now_str))
    new_id = cursor.lastrowid
    conn.commit()
    conn.close()
    logger.info(f"Expediente #{new_id} ({titulo}) creado para {phone_number}.")
    return new_id

def get_expedientes_by_phone(phone_number: str) -> list:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, phone_number, tipo, titulo, estado, gestor_asignado, ruta_sharepoint, creado_en, actualizado_en
        FROM expedientes WHERE phone_number = ?
        ORDER BY creado_en DESC
    ''', (phone_number,))
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "id": row[0],
            "phone_number": row[1],
            "tipo": row[2],
            "titulo": row[3],
            "estado": row[4],
            "gestor_asignado": row[5],
            "ruta_sharepoint": row[6],
            "creado_en": row[7],
            "actualizado_en": row[8]
        }
        for row in rows
    ]

def actualizar_estado_expediente(expediente_id: int, nuevo_estado: str) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute('''
        UPDATE expedientes
        SET estado = ?, actualizado_en = ?
        WHERE id = ?
    ''', (nuevo_estado, now_str, expediente_id))
    rows_affected = cursor.rowcount
    conn.commit()
    conn.close()
    if rows_affected > 0:
        logger.info(f"Estado del expediente #{expediente_id} actualizado a '{nuevo_estado}'.")
        return True
    return False

def get_expediente_by_id(expediente_id: int) -> dict | None:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, phone_number, tipo, titulo, estado, gestor_asignado, ruta_sharepoint, creado_en, actualizado_en
        FROM expedientes WHERE id = ?
    ''', (expediente_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {
            "id": row[0],
            "phone_number": row[1],
            "tipo": row[2],
            "titulo": row[3],
            "estado": row[4],
            "gestor_asignado": row[5],
            "ruta_sharepoint": row[6],
            "creado_en": row[7],
            "actualizado_en": row[8]
        }
    return None


def guardar_captura_estructurada(phone_number: str, canal: str, mensaje_original: str, datos: dict) -> int:
    """
    Persiste el resultado de la captura estructurada (Fase 8.1) generada por Gemini a partir
    de un mensaje entrante (texto o transcripción de audio), en el formato pedido por el cliente:
    cliente probable, área probable, asunto, urgencia, solicitud, documentos mencionados,
    servicio sugerido, expediente probable y confianza.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO capturas_estructuradas (
            phone_number, canal, cliente_probable, area_probable, asunto, urgencia,
            solicitud, documentos_mencionados, servicio_sugerido, expediente_probable,
            confianza, mensaje_original
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        phone_number, canal,
        datos.get("cliente_probable"), datos.get("area_probable"), datos.get("asunto"),
        datos.get("urgencia"), datos.get("solicitud"), datos.get("documentos_mencionados"),
        datos.get("servicio_sugerido"), datos.get("expediente_probable"),
        datos.get("confianza"), mensaje_original
    ))
    new_id = cursor.lastrowid
    conn.commit()
    conn.close()
    logger.info(f"Captura estructurada #{new_id} guardada para {phone_number} (canal={canal}).")
    return new_id

def get_capturas_pendientes(limit: int = 10) -> list:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, phone_number, canal, cliente_probable, area_probable, asunto, urgencia,
               solicitud, documentos_mencionados, servicio_sugerido, expediente_probable,
               confianza, creado_en
        FROM capturas_estructuradas
        WHERE revisado = 0
        ORDER BY creado_en DESC
        LIMIT ?
    ''', (limit,))
    rows = cursor.fetchall()
    conn.close()
    columnas = [
        "id", "phone_number", "canal", "cliente_probable", "area_probable", "asunto",
        "urgencia", "solicitud", "documentos_mencionados", "servicio_sugerido",
        "expediente_probable", "confianza", "creado_en"
    ]
    return [dict(zip(columnas, row)) for row in rows]

def marcar_captura_revisada(captura_id: int) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE capturas_estructuradas SET revisado = 1 WHERE id = ?", (captura_id,))
    rows_affected = cursor.rowcount
    conn.commit()
    conn.close()
    return rows_affected > 0


def registrar_documento_puente(phone_number: str, direccion: str, ruta_logica: str, nombre_archivo: str, mime_type: str = None) -> int | None:
    """
    Registra un documento de la carpeta puente (entrada o salida). Atómico e idempotente por
    ruta_logica: si ya existe un registro con esa ruta (p.ej. el job de revisión de salida lo
    encontró en una pasada anterior), no lo duplica y retorna None en vez de insertar de nuevo.
    """
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO documentos_puente (phone_number, direccion, ruta_logica, nombre_archivo, mime_type)
            VALUES (?, ?, ?, ?, ?)
        ''', (phone_number, direccion, ruta_logica, nombre_archivo, mime_type))
        new_id = cursor.lastrowid
        conn.commit()
        return new_id
    except sqlite3.IntegrityError:
        conn.rollback()
        return None
    finally:
        conn.close()


def get_documentos_puente_recientes(limit: int = 15) -> list:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, phone_number, direccion, ruta_logica, nombre_archivo, mime_type, creado_en
        FROM documentos_puente
        ORDER BY creado_en DESC
        LIMIT ?
    ''', (limit,))
    rows = cursor.fetchall()
    conn.close()
    columnas = ["id", "phone_number", "direccion", "ruta_logica", "nombre_archivo", "mime_type", "creado_en"]
    return [dict(zip(columnas, row)) for row in rows]


