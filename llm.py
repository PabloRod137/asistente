import os
import requests
import logging

logger = logging.getLogger(__name__)

def get_system_prompt() -> str:
    prompt_path = os.path.join(os.path.dirname(__file__), "system_prompt.txt")
    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        logger.warning("No se encontró system_prompt.txt. Usando fallback genérico.")
        return "Eres un asistente comercial amable. Ayuda al cliente en español."

def generate_response(message: str, history: list, phone_number: str = "web_user") -> str:
    """
    Genera la respuesta conversacional usando la API de Gemini 2.5 Flash.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return "Lo siento, el servicio de IA no está configurado."

    system_prompt = get_system_prompt()

    # Cargar conocimiento dinámico del negocio
    import knowledge_base
    knowledge = knowledge_base.cargar_conocimiento()
    if knowledge:
        system_content = system_prompt + "\n\n=== BASE DE CONOCIMIENTO ADICIONAL ===\n" + knowledge
    else:
        system_content = system_prompt

    # Cargar memoria del cliente si está habilitado
    if os.getenv("MODULO_MEMORIA", "true").strip().lower() != "false":
        import client_memory
        cliente = client_memory.get_cliente(phone_number)
        if cliente and cliente.get("nombre"):
            nombre = cliente.get("nombre")
            empresa = cliente.get("empresa") or "No indicada"
            primera_visita = cliente.get("primera_visita") or "No indicada"
            total_conversaciones = cliente.get("total_conversaciones") or 1
            notas = cliente.get("notas") or "Sin notas"
            
            system_content += f"""

=== MEMORIA DEL CLIENTE ===
Este cliente ya nos ha contactado antes.
Nombre: {nombre}
Empresa: {empresa}
Primera visita: {primera_visita}
Total conversaciones: {total_conversaciones}
Notas: {notas}

Si sabes su nombre, úsalo al saludar. Si es su primera visita, no menciones que lo conoces."""

    # URL de Gemini REST API
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    
    # Construir historial en el formato esperado por Gemini API
    contents = []
    for msg in history:
        role = "user" if msg["role"] == "user" else "model"
        contents.append({
            "role": role,
            "parts": [{"text": msg["content"]}]
        })
        
    # Añadir mensaje actual
    contents.append({
        "role": "user",
        "parts": [{"text": message}]
    })

    payload = {
        "system_instruction": {
            "parts": [{"text": system_content}]
        },
        "contents": contents
    }

    try:
        response = requests.post(url, json=payload, headers={'Content-Type': 'application/json'}, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        return data["candidates"][0]["content"]["parts"][0]["text"]
        
    except Exception as e:
        logger.error(f"Error conectando con Gemini en llm.py: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"Detalles: {e.response.text}")
        return "Lo siento, ha ocurrido un error procesando tu mensaje. Inténtalo de nuevo."
