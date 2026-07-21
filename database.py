import sqlite3
import os
import logging

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
            gestor_asignado TEXT
        )
    ''')

    # Migraciones para la tabla clientes
    columnas_clientes = [
        ("numero_expediente", "TEXT"),
        ("tipo_cliente", "TEXT DEFAULT 'nuevo'"),
        ("nif_cif", "TEXT"),
        ("fecha_alta", "DATE"),
        ("gestor_asignado", "TEXT")
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
            completado INTEGER DEFAULT 0
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
               total_conversaciones, numero_expediente, tipo_cliente, nif_cif, fecha_alta, gestor_asignado
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
            "gestor_asignado": row[12]
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
