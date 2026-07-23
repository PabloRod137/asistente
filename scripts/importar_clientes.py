import os
import sys
import unicodedata
import logging
import sqlite3
from datetime import datetime
import openpyxl

# Configurar logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("importador_clientes")

# Añadir el directorio raíz al path para poder importar database.py
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import database

def normalizar_cabecera(val):
    if val is None:
        return ""
    # Minúsculas, remover espacios extra y quitar acentos
    s = str(val).strip().lower()
    s = "".join(
        c for c in unicodedata.normalize('NFD', s)
        if unicodedata.category(c) != 'Mn'
    )
    return s

def parsear_fecha(val):
    if val is None:
        return datetime.now().strftime("%Y-%m-%d")
    if isinstance(val, datetime):
        return val.strftime("%Y-%m-%d")
    s = str(val).strip()
    # Intentar parsear varios formatos comunes
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    # Si no coincide con ninguno, retornar la fecha actual
    return datetime.now().strftime("%Y-%m-%d")

def importar(excel_path):
    if not os.path.exists(excel_path):
        print(f"Error: El archivo '{excel_path}' no existe.")
        sys.exit(1)

    print(f"Cargando archivo Excel: {excel_path}...")
    try:
        wb = openpyxl.load_workbook(excel_path, data_only=True)
    except Exception as e:
        print(f"Error al abrir el archivo Excel: {e}")
        sys.exit(1)

    if "Clientes" not in wb.sheetnames:
        print("Error: El archivo Excel no contiene la hoja obligatoria 'Clientes'.")
        sys.exit(1)

    sheet = wb["Clientes"]
    if sheet.max_row < 1:
        print("Error: La hoja 'Clientes' está vacía.")
        sys.exit(1)

    # 1. Mapear cabeceras a índices
    cabeceras_fila = [cell.value for cell in sheet[1]]
    cabeceras_mapeadas = {}
    for idx, val in enumerate(cabeceras_fila):
        norm = normalizar_cabecera(val)
        if norm:
            cabeceras_mapeadas[norm] = idx + 1  # 1-based index para openpyxl

    # 2. Validar columnas obligatorias
    obligatorias = {
        "nombre completo": "Nombre completo",
        "telefono (whatsapp)": "Teléfono (WhatsApp)",
        "nif/cif": "NIF/CIF",
        "numero de expediente": "Número de expediente"
    }

    faltantes = [user_label for norm_key, user_label in obligatorias.items() if norm_key not in cabeceras_mapeadas]
    if faltantes:
        print(f"Error: Faltan las siguientes columnas obligatorias en el Excel: {', '.join(faltantes)}")
        sys.exit(1)

    # Inicializar contadores e informe de errores
    procesados = 0
    actualizados = 0
    omitidos = 0
    errores = []

    conn = database.get_connection()
    cursor = conn.cursor()

    # Mapeo de columnas opcionales
    opcionales = {
        "tipo_cliente": cabeceras_mapeadas.get("tipo de cliente"),
        "email": cabeceras_mapeadas.get("email"),
        "empresa": cabeceras_mapeadas.get("empresa"),
        "carpeta_sharepoint": cabeceras_mapeadas.get("carpeta sharepoint"),
        "gestor_asignado": cabeceras_mapeadas.get("gestor asignado"),
        "idioma_preferido": cabeceras_mapeadas.get("idioma preferido"),
        "fecha_alta": cabeceras_mapeadas.get("fecha de alta"),
        "notas": cabeceras_mapeadas.get("notas")
    }

    print("Iniciando procesamiento de filas (saltando cabecera y ejemplo)...")

    # Empezar en la fila 3 (saltando fila 1 de cabeceras y fila 2 de ejemplo)
    for r_idx in range(3, sheet.max_row + 1):
        # Comprobar si toda la fila está vacía
        row_cells = [sheet.cell(row=r_idx, column=c_idx).value for c_idx in range(1, len(cabeceras_fila) + 1)]
        if all(val is None or str(val).strip() == "" for val in row_cells):
            continue  # Fila vacía, saltar silenciosamente

        # Extraer valores obligatorios
        nombre = sheet.cell(row=r_idx, column=cabeceras_mapeadas["nombre completo"]).value
        telefono_raw = sheet.cell(row=r_idx, column=cabeceras_mapeadas["telefono (whatsapp)"]).value
        nif_cif_raw = sheet.cell(row=r_idx, column=cabeceras_mapeadas["nif/cif"]).value
        num_expediente = sheet.cell(row=r_idx, column=cabeceras_mapeadas["numero de expediente"]).value

        # Validaciones de campos obligatorios
        errores_fila = []
        if not nombre or str(nombre).strip() == "":
            errores_fila.append("Nombre completo vacío")
        if not telefono_raw or str(telefono_raw).strip() == "":
            errores_fila.append("Teléfono (WhatsApp) vacío")
        if not nif_cif_raw or str(nif_cif_raw).strip() == "":
            errores_fila.append("NIF/CIF vacío")
        if not num_expediente or str(num_expediente).strip() == "":
            errores_fila.append("Número de expediente vacío")

        if errores_fila:
            omitidos += 1
            err_msg = f"Fila {r_idx}: Saltada debido a: {', '.join(errores_fila)}"
            print(f"⚠️ {err_msg}")
            errores.append(err_msg)
            continue

        # Normalizar teléfono
        telefono_norm = database.normalizar_telefono(str(telefono_raw).strip())
        if not telefono_norm:
            omitidos += 1
            err_msg = f"Fila {r_idx}: Teléfono inválido tras normalización ('{telefono_raw}')"
            print(f"⚠️ {err_msg}")
            errores.append(err_msg)
            continue

        # Normalizar NIF/CIF
        nif_cif = str(nif_cif_raw).strip().upper()

        # Extraer campos opcionales
        def read_opt(key, default=None):
            col_idx = opcionales[key]
            if col_idx is None:
                return default
            val = sheet.cell(row=r_idx, column=col_idx).value
            return str(val).strip() if val is not None else default

        tipo_cliente = read_opt("tipo_cliente", "activo")
        if not tipo_cliente or tipo_cliente.strip() == "":
            tipo_cliente = "activo"
            
        email = read_opt("email")
        empresa = read_opt("empresa")
        carpeta_sharepoint = read_opt("carpeta_sharepoint")
        gestor_asignado = read_opt("gestor_asignado")
        
        idioma_preferido = read_opt("idioma_preferido", "es")
        if not idioma_preferido or idioma_preferido.strip() == "":
            idioma_preferido = "es"

        fecha_alta_raw = sheet.cell(row=r_idx, column=opcionales["fecha_alta"]).value if opcionales["fecha_alta"] is not None else None
        fecha_alta = parsear_fecha(fecha_alta_raw)
        
        notas = read_opt("notas")

        # Comprobar si el cliente ya existe en la base de datos
        try:
            cursor.execute("SELECT phone_number FROM clientes WHERE phone_number = ?", (telefono_norm,))
            existe = cursor.fetchone() is not None

            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            if existe:
                # Upsert: Actualizar cliente existente
                cursor.execute("""
                    UPDATE clientes
                    SET nombre = ?,
                        empresa = ?,
                        email = ?,
                        notas = ?,
                        ultima_visita = ?,
                        numero_expediente = ?,
                        tipo_cliente = ?,
                        nif_cif = ?,
                        fecha_alta = ?,
                        gestor_asignado = ?,
                        carpeta_sharepoint = ?,
                        idioma_preferido = ?
                    WHERE phone_number = ?
                """, (
                    nombre, empresa, email, notas, now_str, num_expediente, 
                    tipo_cliente, nif_cif, fecha_alta, gestor_asignado, 
                    carpeta_sharepoint, idioma_preferido, telefono_norm
                ))
                actualizados += 1
                print(f"🔄 Fila {r_idx}: Cliente actualizado ({telefono_norm} - {nombre})")
            else:
                # Insertar nuevo cliente
                cursor.execute("""
                    INSERT INTO clientes (
                        phone_number, nombre, empresa, email, notas, primera_visita, ultima_visita,
                        total_conversaciones, numero_expediente, tipo_cliente, nif_cif, fecha_alta,
                        gestor_asignado, carpeta_sharepoint, idioma_preferido
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    telefono_norm, nombre, empresa, email, notas, now_str, now_str,
                    num_expediente, tipo_cliente, nif_cif, fecha_alta,
                    gestor_asignado, carpeta_sharepoint, idioma_preferido
                ))
                procesados += 1
                print(f"📥 Fila {r_idx}: Cliente insertado ({telefono_norm} - {nombre})")

            conn.commit()

        except sqlite3.Error as db_err:
            conn.rollback()
            omitidos += 1
            err_msg = f"Fila {r_idx}: Error de base de datos al guardar ({db_err})"
            print(f"❌ {err_msg}")
            errores.append(err_msg)

    conn.close()

    # Imprimir resumen de la importación
    print("\n" + "="*50)
    print("           RESUMEN DE LA IMPORTACIÓN")
    print("="*50)
    print(f"Clientes nuevos insertados: {procesados}")
    print(f"Clientes existentes actualizados: {actualizados}")
    print(f"Filas omitidas / con errores: {omitidos}")
    print(f"Total filas de datos leídas: {procesados + actualizados + omitidos}")
    print("="*50)
    
    if errores:
        print("\nDetalle de filas omitidas/errores:")
        for err in errores:
            print(f" - {err}")
    print("="*50 + "\n")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python scripts/importar_clientes.py {ruta_archivo_excel}")
        sys.exit(1)
    importar(sys.argv[1])
