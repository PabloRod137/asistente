import os
import sys
import logging
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_storage")

def run_test():
    import storage_adapter
    
    # 1. Test normal write and read
    test_content = b"Prueba de contenido para almacenamiento"
    test_path = "facturas_emitidas/factura_test_123.txt"
    
    logger.info("--- Probando escritura normal ---")
    try:
        saved_path = storage_adapter.guardar_archivo(test_path, test_content)
        logger.info(f"Guardado exitoso. Ruta de retorno: {saved_path}")
        
        logger.info("--- Probando lectura ---")
        read_content = storage_adapter.leer_archivo(test_path)
        logger.info(f"Leido exitoso. Contenido: {read_content}")
        assert read_content == test_content, "El contenido leido no coincide con el guardado"
        
        logger.info("--- Probando listado ---")
        archivos = storage_adapter.listar_archivos("facturas_emitidas")
        logger.info(f"Archivos en facturas_emitidas: {archivos}")
        
    except Exception as e:
        logger.error(f"Fallo durante las pruebas de almacenamiento: {e}", exc_info=True)
        return False

    # 2. Test fallback: Corromper temporalmente secretos de Microsoft Graph
    logger.info("--- Probando fallback de almacenamiento ---")
    
    original_tipo = os.getenv("STORAGE_TIPO")
    original_secret = os.getenv("MS_CLIENT_SECRET")
    
    # Forzar modo sharepoint con secret incorrecto
    os.environ["STORAGE_TIPO"] = "sharepoint"
    os.environ["MS_CLIENT_SECRET"] = "secret_invalido_de_prueba"
    
    fallback_content = b"Contenido de contingencia local"
    fallback_path = "facturas_emitidas/factura_fallback.txt"
    
    try:
        # Esto debería fallar en SharePoint y caer automáticamente a LocalStorageAdapter
        # con una advertencia en los logs
        logger.info("Intentando guardar con credenciales corruptas (debería emitir warning y completarse)...")
        saved_path = storage_adapter.guardar_archivo(fallback_path, fallback_content)
        logger.info(f"Retorno tras fallback: {saved_path}")
        
        # Verificar que se puede leer (cae a local y lo encuentra)
        read_content = storage_adapter.leer_archivo(fallback_path)
        logger.info(f"Leido tras fallback: {read_content}")
        assert read_content == fallback_content, "El contenido de fallback leido no coincide"
        
        # Validar que existe físicamente en el disco local bajo storage/temp o storage/facturas_emitidas
        local_ruta = os.getenv("STORAGE_RUTA", "./storage")
        physical_local_path = os.path.join(local_ruta, "facturas_emitidas", "factura_fallback.txt")
        logger.info(f"Comprobando presencia física local en {physical_local_path}...")
        assert os.path.exists(physical_local_path), f"El archivo no se guardó físicamente en local: {physical_local_path}"
        logger.info("¡Verificación de fallback exitosa! El archivo está en el disco local.")
        
    except Exception as e:
        logger.error(f"Fallo durante la prueba de fallback: {e}", exc_info=True)
        return False
    finally:
        # Restaurar variables
        if original_tipo is not None:
            os.environ["STORAGE_TIPO"] = original_tipo
        else:
            del os.environ["STORAGE_TIPO"]
            
        if original_secret is not None:
            os.environ["MS_CLIENT_SECRET"] = original_secret
        else:
            del os.environ["MS_CLIENT_SECRET"]
            
    return True

if __name__ == "__main__":
    success = run_test()
    sys.exit(0 if success else 1)
