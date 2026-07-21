import os
import sys
import asyncio
import logging
from datetime import datetime

# Añadir directorio raíz al path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Configurar variables de test
os.environ["MODO_TEST"] = "true"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_fase5_1")

async def test_jobs():
    logger.info("=== PROBANDO LOS 3 JOBS PROGRAMADOS CON ASYNCIOSCHEDULER ===")
    
    # Job 1: Recordatorios de Fase 4
    from modulos import recordatorios
    logger.info("Ejecutando Job 1: procesar_todos_los_recordatorios...")
    summary_rec = await recordatorios.procesar_todos_los_recordatorios()
    logger.info(f"Resultado Job 1: {summary_rec}")
    
    # Job 2: Briefing diario
    import secretaria
    logger.info("Ejecutando Job 2: generar_briefing_diario...")
    await secretaria.generar_briefing_diario()
    logger.info("Job 2 ejecutado correctamente.")
    
    # Job 3: Limpieza de temporales
    from modulos import triaje
    logger.info("Ejecutando Job 3: limpiar_archivos_temporales_antiguos...")
    await triaje.limpiar_archivos_temporales_antiguos()
    logger.info("Job 3 ejecutado correctamente.")

async def test_concurrency():
    logger.info("=== PROBANDO 10 SOLICITUDES SIMULTÁNEAS EN MAIN.PROCESAR_FLUJO_MENSAJE ===")
    import main
    import database
    database.init_db()

    promesas = []
    for i in range(10):
        phone = f"346001122{i:02d}"
        msg = f"Hola, me gustaría información sobre la gestoría {i}"
        promesas.append(main.procesar_flujo_mensaje(phone, msg, "text"))

    resultados = await asyncio.gather(*promesas)
    
    exitos = 0
    for i, res in enumerate(resultados):
        logger.info(f"Respuesta {i+1}: {res[:80]}...")
        if res and "error" not in res.lower() and "lo siento, ha ocurrido un error" not in res.lower():
            exitos += 1
            
    logger.info(f"Concurrencia completada: {exitos}/10 exitosas.")
    assert exitos == 10, f"Se esperaban 10 respuestas exitosas pero fueron {exitos}"

async def main_test():
    await test_jobs()
    await test_concurrency()
    logger.info("✅ TODAS LAS PRUEBAS DE LA FASE 5.1 PASADAS CORRECTAMENTE")

if __name__ == "__main__":
    asyncio.run(main_test())
