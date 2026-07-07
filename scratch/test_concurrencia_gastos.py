import os
import sys
import shutil
import threading
import logging
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_concurrencia_gastos")

def run_single_test_round(round_num: int):
    import database
    from modulos import tickets
    
    # Asegurar que las tablas estén inicializadas
    database.init_db()
    
    # Crear algunas imágenes temporales ficticias
    temp_dir = "./storage/temp"
    os.makedirs(temp_dir, exist_ok=True)
    
    threads = []
    num_threads = 5
    
    # Limpiar conteo inicial
    conn = database.get_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM gastos_tickets")
    initial_count = c.fetchone()[0]
    conn.close()
    
    logger.info(f"Ronda {round_num}: Iniciando con {initial_count} registros en la base de datos.")
    
    errors = []
    
    def worker(phone: str, index: int):
        temp_img_path = os.path.join(temp_dir, f"temp_gasto_{phone}.jpg")
        with open(temp_img_path, "wb") as f:
            f.write(b"fake jpeg data")
            
        datos_gasto = {
            "emisor": f"Emisor_{round_num}_{index}",
            "cif_emisor": f"A1234567{index}",
            "fecha": "2026-07-07",
            "base_imponible": 100.0 + index,
            "porcentaje_iva": 21,
            "cuota_iva": (100.0 + index) * 0.21,
            "total": (100.0 + index) * 1.21
        }
        
        try:
            tickets.guardar_registro_gasto(phone, temp_img_path, datos_gasto)
            logger.info(f"Thread-{index} completado con éxito para teléfono {phone}")
        except Exception as e:
            logger.error(f"Thread-{index} falló: {e}", exc_info=True)
            errors.append(e)
            
    for i in range(num_threads):
        # Números de teléfono distintos para evitar serializaciones conversacionales
        phone = f"3460000{round_num}{i}"
        t = threading.Thread(target=worker, args=(phone, i))
        threads.append(t)
        t.start()
        
    for t in threads:
        t.join()
        
    # Verificar recuento en BD
    conn = database.get_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM gastos_tickets")
    final_count = c.fetchone()[0]
    conn.close()
    
    expected_count = initial_count + num_threads
    logger.info(f"Ronda {round_num}: Esperados={expected_count}, Obtenidos={final_count}")
    
    assert len(errors) == 0, f"Se produjeron {len(errors)} errores en la ronda {round_num}!"
    assert final_count == expected_count, f"Inconsistencia en el conteo de gastos! Esperados {expected_count}, obtenidos {final_count}."
    
    logger.info(f"Ronda {round_num} completada con éxito.")

def run_tests():
    # Repetir el test de concurrencia al menos 4 veces consecutivas
    for round_num in range(1, 5):
        logger.info(f"\n================ INICIANDO RONDA {round_num} DE CONCURRENCIA ================")
        run_single_test_round(round_num)
        
    # Probar la exportación a Excel
    logger.info("\n================ PROBANDO EXPORTACIÓN A EXCEL ================")
    import gestor_mode
    # Exportar para uno de los CIFs que acabamos de registrar
    cif_test = "A12345671"
    res = gestor_mode.procesar_comando("34612345678", f"/exportar_gastos {cif_test}")
    logger.info(f"Resultado de exportación: {res}")
    assert "exportado con éxito" in res, f"Fallo al exportar gastos: {res}"
    logger.info("¡Prueba de concurrencia y exportación completada con éxito absoluto!")

if __name__ == "__main__":
    try:
        run_tests()
        sys.exit(0)
    except Exception as ex:
        logger.error(f"Fallo crítico en el test de concurrencia: {ex}", exc_info=True)
        sys.exit(1)
