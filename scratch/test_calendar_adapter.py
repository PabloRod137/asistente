import os
import sys
import logging
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_calendar")

def run_test():
    import calendar_adapter
    
    # 1. Test normal execution or simulated fallback depending on environment variables
    logger.info("--- Probando obtención de huecos libres ---")
    date_str = "2026-07-08"
    try:
        slots = calendar_adapter.get_free_slots(date_str)
        logger.info(f"Huecos libres obtenidos: {len(slots)} slots")
        if slots:
            logger.info(f"Primer slot: {slots[0]}")
            
        logger.info("--- Probando creación de evento ---")
        title = "Reunión de prueba"
        start_time = "2026-07-08T10:00:00"
        end_time = "2026-07-08T11:00:00"
        res = calendar_adapter.create_event(title, start_time, end_time, "cliente@test.com")
        logger.info(f"Resultado de creación de evento: {res}")
        assert res.get("status") == "success", "Fallo al crear evento"
        
        # Verificar que el evento aparece ocupando su slot
        slots_after = calendar_adapter.get_free_slots(date_str)
        logger.info(f"Huecos tras crear evento: {len(slots_after)} slots")
        
        # Cancelar el evento
        event_id = res.get("id")
        logger.info(f"--- Probando cancelación de evento {event_id} ---")
        cancelled = calendar_adapter.cancel_event(event_id)
        logger.info(f"Evento cancelado: {cancelled}")
        assert cancelled, "Fallo al cancelar evento"
        
    except Exception as e:
        logger.error(f"Fallo durante la prueba del calendario: {e}", exc_info=True)
        return False
        
    # 2. Test fallback: Forzar fallback a simulación
    logger.info("--- Probando fallback del calendario a simulación ---")
    original_tipo = os.getenv("CALENDAR_TIPO")
    original_secret = os.getenv("MS_CLIENT_SECRET")
    
    os.environ["CALENDAR_TIPO"] = "outlook"
    os.environ["MS_CLIENT_SECRET"] = "secret_invalido_de_prueba"
    
    try:
        # Debería emitir un warning y caer automáticamente a simulación
        logger.info("Solicitando slots con credenciales inválidas (debería dar warning de fallback)...")
        slots_fallback = calendar_adapter.get_free_slots("2026-07-09")
        logger.info(f"Huecos obtenidos tras fallback: {len(slots_fallback)} slots")
        
        logger.info("Creando evento con credenciales inválidas (debería dar warning de fallback)...")
        res_fallback = calendar_adapter.create_event(
            "Cita Fallback", "2026-07-09T12:00:00", "2026-07-09T13:00:00"
        )
        logger.info(f"Evento fallback creado: {res_fallback}")
        assert res_fallback["tipo"] == "simulated", "El tipo de evento creado no es 'simulated' tras fallback!"
        
        # Cancelar el evento de fallback simulado
        cancelled_fallback = calendar_adapter.cancel_event(res_fallback["id"])
        logger.info(f"Evento fallback simulado cancelado: {cancelled_fallback}")
        assert cancelled_fallback, "Fallo al cancelar evento simulado"
        logger.info("¡Verificación de fallback de calendario exitosa!")
        
    except Exception as e:
        logger.error(f"Fallo durante la prueba de fallback de calendario: {e}", exc_info=True)
        return False
    finally:
        # Restaurar variables
        if original_tipo is not None:
            os.environ["CALENDAR_TIPO"] = original_tipo
        else:
            del os.environ["CALENDAR_TIPO"]
            
        if original_secret is not None:
            os.environ["MS_CLIENT_SECRET"] = original_secret
        else:
            del os.environ["MS_CLIENT_SECRET"]
            
    return True

if __name__ == "__main__":
    success = run_test()
    sys.exit(0 if success else 1)
