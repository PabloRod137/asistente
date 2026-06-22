import sqlite3
import os

DB_PATH = os.getenv("DB_PATH", "chatbot.db")

def init_db():
    db_path_dynamic = os.getenv("DB_PATH", "chatbot.db")
    conn = sqlite3.connect(db_path_dynamic)
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
            total_conversaciones INTEGER DEFAULT 1
        )
    ''')

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
    
    conn.commit()
    conn.close()

def save_message(phone_number: str, role: str, content: str):
    db_path_dynamic = os.getenv("DB_PATH", "chatbot.db")
    conn = sqlite3.connect(db_path_dynamic)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO messages (phone_number, role, content)
        VALUES (?, ?, ?)
    ''', (phone_number, role, content))
    conn.commit()
    conn.close()

def get_history(phone_number: str, limit: int = 10) -> list:
    max_limit = min(limit, 10)
    db_path_dynamic = os.getenv("DB_PATH", "chatbot.db")
    conn = sqlite3.connect(db_path_dynamic)
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
    db_path_dynamic = os.getenv("DB_PATH", "chatbot.db")
    conn = sqlite3.connect(db_path_dynamic)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO citas (phone_number, event_id, fecha, servicio, estado)
        VALUES (?, ?, ?, ?, ?)
    ''', (phone_number, event_id, fecha, servicio, estado))
    conn.commit()
    conn.close()

def get_active_cita(phone_number: str):
    db_path_dynamic = os.getenv("DB_PATH", "chatbot.db")
    conn = sqlite3.connect(db_path_dynamic)
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
    db_path_dynamic = os.getenv("DB_PATH", "chatbot.db")
    conn = sqlite3.connect(db_path_dynamic)
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE citas SET estado = ? WHERE event_id = ?
    ''', (estado, event_id))
    conn.commit()
    conn.close()

# Funciones de utilidad para facturas
def get_next_factura_numero() -> int:
    db_path_dynamic = os.getenv("DB_PATH", "chatbot.db")
    conn = sqlite3.connect(db_path_dynamic)
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM facturas')
    count = cursor.fetchone()[0]
    conn.close()
    return count + 1

def save_factura(destinatario: str, cif: str, concepto: str, importe: float) -> int:
    db_path_dynamic = os.getenv("DB_PATH", "chatbot.db")
    conn = sqlite3.connect(db_path_dynamic)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO facturas (destinatario, cif, concepto, importe)
        VALUES (?, ?, ?, ?)
    ''', (destinatario, cif, concepto, importe))
    factura_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return factura_id
