import os
import sys
import shutil
import sqlite3
import logging

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_fase3_1_db")

def test_db_migration():
    import database
    
    # 1. Probar init_db en la BD actual
    logger.info("--- Probando init_db en la base de datos principal ---")
    database.init_db()
    
    cliente_info = database.get_cliente_by_phone("34600000000")
    logger.info(f"Retorno de get_cliente_by_phone (no existente): {cliente_info}")
    assert cliente_info is None, "Debería retornar None para teléfono no existente"
    
    # 2. Probar migración con chatbot.db.bak si existe
    bak_path = "chatbot.db.bak"
    temp_test_db = "scratch/temp_test_bak.db"
    
    if os.path.exists(bak_path):
        logger.info(f"--- Probando migración sobre copia de {bak_path} ---")
        shutil.copyfile(bak_path, temp_test_db)
        
        # Conectar a la BD temp e invocar las migraciones
        conn = database.get_connection()
        # Forzar database.DB_PATH temporalmente
        orig_db_path = os.getenv("DB_PATH", "chatbot.db")
        os.environ["DB_PATH"] = temp_test_db
        try:
            database.init_db()
            logger.info("Migración ejecutada con éxito sobre BD previa (bak).")
            
            # Verificar columnas con PRAGMA table_info
            conn_test = database.get_connection()
            c = conn_test.cursor()
            c.execute("PRAGMA table_info(clientes)")
            cols = [row[1] for row in c.fetchall()]
            conn_test.close()
            logger.info(f"Columnas en clientes tras migración: {cols}")
            
            expected_cols = ["numero_expediente", "tipo_cliente", "nif_cif", "fecha_alta", "gestor_asignado"]
            for col in expected_cols:
                assert col in cols, f"La columna {col} no fue agregada por la migración!"
            logger.info("¡Todas las columnas esperadas existen en la tabla clientes!")
            
        finally:
            os.environ["DB_PATH"] = orig_db_path
            if os.path.exists(temp_test_db):
                os.remove(temp_test_db)
    else:
        logger.info(f"No se encontró {bak_path}, se omite la prueba sobre backup.")

    logger.info("¡Fase 3.1: Prueba de migración completada con ÉXITO!")
    return True

if __name__ == "__main__":
    success = test_db_migration()
    sys.exit(0 if success else 1)
