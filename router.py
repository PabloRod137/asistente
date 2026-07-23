import os
import httpx
import logging

logger = logging.getLogger(__name__)

async def detectar_intencion(message: str) -> str:
    """
    Clasifica el mensaje entrante del usuario en una de las intenciones soportadas:
    AGENDA, TICKET, FACTURA, TRIAJE, COBRADOR, CHAT de forma asíncrona.
    """
    # Reglas duras (heurísticas rápidas) para optimización y robustez ante fallos de la API
    if message:
        msg_lower = message.lower().strip()
        if "cita" in msg_lower or "reservar" in msg_lower or "agendar" in msg_lower:
            if os.getenv("MODULO_AGENDA", "true").strip().lower() != "false":
                logger.info("Heurística de intención detectada: AGENDA")
                return "AGENDA"
        if "factura" in msg_lower:
            if os.getenv("MODULO_FACTURAS", "true").strip().lower() != "false":
                logger.info("Heurística de intención detectada: FACTURA")
                return "FACTURA"
        if "ticket" in msg_lower or "gasto" in msg_lower:
            if os.getenv("MODULO_TICKETS", "true").strip().lower() != "false":
                logger.info("Heurística de intención detectada: TICKET")
                return "TICKET"
        if "averia" in msg_lower or "avería" in msg_lower or "presupuesto" in msg_lower:
            if os.getenv("MODULO_TRIAJE", "true").strip().lower() != "false":
                logger.info("Heurística de intención detectada: TRIAJE")
                return "TRIAJE"

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.warning("Falta GEMINI_API_KEY. Router devuelve CHAT por defecto.")
        return "CHAT"

    # Si es un mensaje vacío o muy corto, no gastamos llamada
    if not message or len(message.strip()) < 2:
        return "CHAT"

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
    
    prompt = f"""
    Clasifica el siguiente mensaje de un cliente en exactamente una de estas categorías en mayúsculas:
    - AGENDA: Quiere reservar, ver disponibilidad, cambiar o cancelar una cita/reserva.
    - TICKET: Indica que está enviando un ticket, factura de gasto recibida, recibo, o que quiere registrar un gasto (ej: "te paso el ticket", "aquí tienes la factura").
    - FACTURA: Quiere crear, emitir o generar una factura para cobrar a un cliente (ej: "factura a Juan García", "hazme una factura por...").
    - TRIAJE: Solicita un presupuesto, reporta una avería o un trabajo para realizar (ej: "tengo una gotera", "presupuesto para pintar").
    - CHAT: Conversación general, saludos, preguntas sobre el negocio, precios, horarios, etc.

    Regla: Responde ÚNICAMENTE con la palabra de la categoría (AGENDA, TICKET, FACTURA, TRIAJE, CHAT). Nada más.
    Mensaje: "{message}"
    """

    payload = {
        "contents": [{
            "parts": [{"text": prompt}]
        }],
        "generationConfig": {
            "maxOutputTokens": 10,
            "temperature": 0.0
        }
    }

    from gemini_limiter import limiter
    try:
        async with limiter:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(url, json=payload, headers={'Content-Type': 'application/json'})
                response.raise_for_status()
            data = response.json()
            
            parts = data["candidates"][0]["content"].get("parts", [])
            text_parts = [p["text"] for p in parts if "text" in p]
            if not text_parts:
                logger.warning("Gemini no devolvió texto en ninguna part. Usando CHAT.")
                return "CHAT"
            intent = text_parts[-1].strip().upper()
            
            valid_intents = {"AGENDA", "TICKET", "FACTURA", "TRIAJE", "CHAT"}
            matched_intent = "CHAT"
            for i in valid_intents:
                if i in intent:
                    matched_intent = i
                    break
                    
            env_mapping = {
                "AGENDA": "MODULO_AGENDA",
                "TICKET": "MODULO_TICKETS",
                "FACTURA": "MODULO_FACTURAS",
                "TRIAJE": "MODULO_TRIAJE"
            }
            
            if matched_intent in env_mapping:
                env_var = env_mapping[matched_intent]
                if os.getenv(env_var, "true").strip().lower() == "false":
                    logger.info(f"Intención {matched_intent} detectada pero el módulo está inactivo. Desviando a CHAT.")
                    return "CHAT"
                    
            logger.info(f"Intención detectada: {matched_intent}")
            return matched_intent
            
    except Exception as e:
        logger.error(f"Error clasificando intención con Gemini: {e}")
        return "CHAT"
