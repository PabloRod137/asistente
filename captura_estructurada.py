import os
import json
import logging
import asyncio
from google import genai
from google.genai import types

import database
from gemini_limiter import limiter

logger = logging.getLogger(__name__)

CAMPOS_CAPTURA = [
    "cliente_probable", "area_probable", "asunto", "urgencia", "solicitud",
    "documentos_mencionados", "servicio_sugerido", "expediente_probable", "confianza"
]

PROMPT_CAPTURA = """Eres la capa de entrada de un asistente virtual de un despacho de asesoría/gestoría legal, fiscal y laboral.
Tu única tarea es leer el mensaje de un cliente y estructurarlo — NO debes responder al cliente, NO debes inventar
información que no esté en el mensaje, y NO debes proponer ninguna actuación ni documento.

Extrae del mensaje siguiente, si están presentes:
- cliente_probable: nombre de persona o empresa mencionado, si lo hay.
- area_probable: área del despacho a la que pertenece (fiscal, laboral, mercantil, civil, compliance, comunidades, general).
- asunto: resumen muy breve (una frase) de qué trata la consulta.
- urgencia: "alta", "media" o "baja" según el tono y contenido del mensaje.
- solicitud: qué está pidiendo concretamente el cliente que se haga.
- documentos_mencionados: documentos que el cliente menciona haber enviado o tener (ej. "fotografías", "DNI"), o null si no menciona ninguno.
- servicio_sugerido: qué servicio del despacho encaja mejor con la consulta.
- expediente_probable: número o referencia de expediente si el cliente lo menciona explícitamente, o null.
- confianza: un entero de 0 a 100 indicando cuánta seguridad tienes en esta clasificación en conjunto.

Si un campo no se puede determinar con la información disponible, devuelve null para ese campo (no inventes datos).

Devuelve ÚNICAMENTE un JSON válido con esta estructura exacta:
{{
    "cliente_probable": "..." | null,
    "area_probable": "..." | null,
    "asunto": "..." | null,
    "urgencia": "alta" | "media" | "baja" | null,
    "solicitud": "..." | null,
    "documentos_mencionados": "..." | null,
    "servicio_sugerido": "..." | null,
    "expediente_probable": "..." | null,
    "confianza": 0-100 | null
}}

MENSAJE DEL CLIENTE:
\"\"\"{mensaje}\"\"\"
"""


async def generar_captura_estructurada(phone_number: str, mensaje: str, canal: str) -> dict | None:
    """
    Genera y persiste la captura estructurada (Fase 8.1) de un mensaje entrante, en el formato
    fijo pedido por el cliente (cliente probable, área probable, asunto, urgencia, solicitud,
    documentos mencionados, servicio sugerido, expediente probable, confianza).

    Pensado para lanzarse en segundo plano DESPUÉS de responder al cliente (no debe añadir
    latencia a la respuesta que ve el cliente). Si falla, se registra el error y no se persiste
    nada — nunca debe interrumpir el flujo de conversación principal.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.warning("Falta GEMINI_API_KEY, no se puede generar la captura estructurada.")
        return None

    try:
        def _call_gemini_captura():
            client = genai.Client(api_key=api_key)
            prompt = PROMPT_CAPTURA.format(mensaje=mensaje)
            respuesta = client.models.generate_content(
                model='gemini-flash-latest',
                contents=[prompt],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json"
                )
            )
            return json.loads(respuesta.text.strip())

        async with limiter:
            datos = await asyncio.to_thread(_call_gemini_captura)

        datos_normalizados = {campo: datos.get(campo) for campo in CAMPOS_CAPTURA}
        database.guardar_captura_estructurada(phone_number, canal, mensaje, datos_normalizados)
        return datos_normalizados
    except Exception as e:
        logger.error(f"Error generando captura estructurada para {phone_number}: {e}")
        return None


async def transcribir_audio(audio_path: str, mime_type: str = "audio/ogg") -> str | None:
    """
    Transcribe un audio (ej. nota de voz de WhatsApp) a texto en español usando el modelo
    multimodal de Gemini, con el mismo patrón ya probado en modulos/triaje.py y
    modulos/tickets.py para imágenes (types.Part.from_bytes), aplicado a audio.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.warning("Falta GEMINI_API_KEY, no se puede transcribir el audio.")
        return None

    if not os.path.exists(audio_path):
        logger.error(f"El archivo de audio a transcribir no existe: {audio_path}")
        return None

    try:
        def _call_gemini_transcripcion():
            client = genai.Client(api_key=api_key)
            with open(audio_path, 'rb') as f:
                audio_bytes = f.read()
            part = types.Part.from_bytes(data=audio_bytes, mime_type=mime_type)
            prompt = (
                "Transcribe literalmente a texto en español lo que se dice en este audio. "
                "Devuelve únicamente la transcripción, sin comentarios ni formato adicional."
            )
            respuesta = client.models.generate_content(
                model='gemini-flash-latest',
                contents=[part, prompt]
            )
            return respuesta.text.strip()

        async with limiter:
            transcripcion = await asyncio.to_thread(_call_gemini_transcripcion)
        return transcripcion or None
    except Exception as e:
        logger.error(f"Error transcribiendo audio {audio_path}: {e}")
        return None
