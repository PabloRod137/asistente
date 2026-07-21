import os
import logging
import httpx
import asyncio
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Fallback in-memory store for simulation if real APIs aren't connected
_simulated_events = {}

def _get_google_client():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if not creds_json or not os.path.exists(creds_json):
        raise ValueError(f"Google credentials file not found: {creds_json}")
        
    scopes = ['https://www.googleapis.com/auth/calendar']
    creds = service_account.Credentials.from_service_account_file(creds_json, scopes=scopes)
    service = build('calendar', 'v3', credentials=creds)
    return service

async def _get_outlook_events(date_str: str) -> list:
    import graph_auth
    email_emisor = os.getenv("EMAIL_EMISOR")
    if not email_emisor:
        raise ValueError("Falta configurar EMAIL_EMISOR para obtener eventos de calendario.")
        
    token = await graph_auth.get_access_token()
    
    start_dt = f"{date_str}T00:00:00"
    end_dt = f"{date_str}T23:59:59"
    
    url = f"https://graph.microsoft.com/v1.0/users/{email_emisor}/calendar/calendarView"
    params = {
        "startDateTime": start_dt,
        "endDateTime": end_dt,
        "$select": "subject,start,end",
        "$top": 1000
    }
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Prefer": 'outlook.timezone="Europe/Madrid"'
    }
    
    logger.info(f"Obteniendo calendarView de Graph para {date_str}...")
    async with httpx.AsyncClient(timeout=15.0) as client:
        res = await client.get(url, headers=headers, params=params)
        res.raise_for_status()
        
        events = []
        for item in res.json().get("value", []):
            start_val = item["start"]["dateTime"]
            end_val = item["end"]["dateTime"]
            try:
                clean_start = start_val.split('.')[0]
                clean_end = end_val.split('.')[0]
                dt_start = datetime.fromisoformat(clean_start)
                dt_end = datetime.fromisoformat(clean_end)
                events.append((dt_start, dt_end))
            except Exception as e:
                logger.warning(f"Error parseando fechas del evento de Outlook: {e}")
                
        return events

async def _create_outlook_event(title: str, start: str, end: str, attendee_email: str = None) -> str:
    import graph_auth
    email_emisor = os.getenv("EMAIL_EMISOR")
    if not email_emisor:
        raise ValueError("Falta configurar EMAIL_EMISOR para crear eventos en el calendario.")
        
    token = await graph_auth.get_access_token()
    url = f"https://graph.microsoft.com/v1.0/users/{email_emisor}/calendar/events"
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "subject": title,
        "start": {
            "dateTime": start,
            "timeZone": "Europe/Madrid"
        },
        "end": {
            "dateTime": end,
            "timeZone": "Europe/Madrid"
        }
    }
    
    if attendee_email:
        payload["attendees"] = [
            {
                "emailAddress": {
                    "address": attendee_email
                },
                "type": "required"
            }
        ]
        
    logger.info(f"Creando evento en el calendario de Outlook para {email_emisor}...")
    async with httpx.AsyncClient(timeout=15.0) as client:
        res = await client.post(url, headers=headers, json=payload)
        res.raise_for_status()
        return res.json().get("id")

async def _cancel_outlook_event(event_id: str) -> bool:
    import graph_auth
    email_emisor = os.getenv("EMAIL_EMISOR")
    if not email_emisor:
        raise ValueError("Falta configurar EMAIL_EMISOR para cancelar eventos en el calendario.")
        
    token = await graph_auth.get_access_token()
    url = f"https://graph.microsoft.com/v1.0/users/{email_emisor}/calendar/events/{event_id}"
    
    headers = {
        "Authorization": f"Bearer {token}"
    }
    
    logger.info(f"Cancelando evento de Outlook {event_id}...")
    async with httpx.AsyncClient(timeout=15.0) as client:
        res = await client.delete(url, headers=headers)
        res.raise_for_status()
        return True

async def get_free_slots(date_str: str, duration_minutes: int = 60) -> list:
    """
    date_str: Formato 'YYYY-MM-DD'
    Retorna una lista de diccionarios: [{'start': 'YYYY-MM-DDTHH:MM:SS', 'end': 'YYYY-MM-DDTHH:MM:SS'}]
    """
    calendar_tipo = os.getenv("CALENDAR_TIPO", "outlook").strip().lower()
    logger.info(f"Obteniendo huecos libres para {date_str} usando {calendar_tipo}")
    
    try:
        base_date = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        logger.error(f"Formato de fecha inválido: {date_str}")
        return []
        
    work_start_hour = 9
    work_end_hour = 18
    potential_slots = []
    
    current_time = base_date.replace(hour=work_start_hour, minute=0, second=0, microsecond=0)
    end_limit = base_date.replace(hour=work_end_hour, minute=0, second=0, microsecond=0)
    
    while current_time + timedelta(minutes=duration_minutes) <= end_limit:
        slot_start = current_time
        slot_end = current_time + timedelta(minutes=duration_minutes)
        potential_slots.append({
            "start": slot_start,
            "end": slot_end
        })
        current_time += timedelta(minutes=duration_minutes)

    events = []
    use_fallback = False
    
    if calendar_tipo == "google":
        try:
            def _get_google_events_sync():
                service = _get_google_client()
                time_min = f"{date_str}T00:00:00Z"
                time_max = f"{date_str}T23:59:59Z"
                events_result = service.events().list(
                    calendarId='primary', 
                    timeMin=time_min,
                    timeMax=time_max, 
                    singleEvents=True,
                    orderBy='startTime'
                ).execute()
                res_events = []
                for event in events_result.get('items', []):
                    start_str = event['start'].get('dateTime') or event['start'].get('date')
                    end_str = event['end'].get('dateTime') or event['end'].get('date')
                    try:
                        start_dt = datetime.fromisoformat(start_str.split('+')[0].split('Z')[0])
                        end_dt = datetime.fromisoformat(end_str.split('+')[0].split('Z')[0])
                        res_events.append((start_dt, end_dt))
                    except Exception as ex:
                        logger.warning(f"Error parseando fechas del evento Google: {ex}")
                return res_events

            events = await asyncio.to_thread(_get_google_events_sync)
        except Exception as e:
            logger.warning(f"Error conectando con Google Calendar: {e}. Usando simulación.")
            use_fallback = True
            
    elif calendar_tipo == "outlook":
        try:
            events = await _get_outlook_events(date_str)
        except Exception as e:
            logger.warning(
                f"FALLBACK CALENDARIO: Error conectando con Outlook Calendar vía Graph API (fecha '{date_str}'): {e}. "
                f"Cayendo automáticamente a simulación en memoria.", 
                exc_info=True
            )
            use_fallback = True
    else:
        use_fallback = True
 
    if use_fallback:
        for ev_id, ev_info in _simulated_events.items():
            ev_start = datetime.fromisoformat(ev_info["start"])
            ev_end = datetime.fromisoformat(ev_info["end"])
            if ev_start.date() == base_date.date():
                events.append((ev_start, ev_end))

    free_slots = []
    for slot in potential_slots:
        overlap = False
        for ev_start, ev_end in events:
            if slot["start"] < ev_end and slot["end"] > ev_start:
                overlap = True
                break
        if not overlap:
            free_slots.append({
                "start": slot["start"].isoformat(),
                "end": slot["end"].isoformat()
            })
            
    return free_slots

async def create_event(title: str, start: str, end: str, attendee_email: str = None) -> dict:
    """
    Crea un evento en el calendario.
    start / end en formato ISO 'YYYY-MM-DDTHH:MM:SS'
    """
    calendar_tipo = os.getenv("CALENDAR_TIPO", "outlook").strip().lower()
    logger.info(f"Creando evento '{title}' de {start} a {end} en {calendar_tipo}")
    
    use_fallback = False
    
    if calendar_tipo == "google":
        try:
            def _create_google_event_sync():
                service = _get_google_client()
                event_body = {
                    'summary': title,
                    'start': {'dateTime': f"{start}", 'timeZone': 'Europe/Madrid'},
                    'end': {'dateTime': f"{end}", 'timeZone': 'Europe/Madrid'}
                }
                if attendee_email:
                    event_body['attendees'] = [{'email': attendee_email}]
                created_event = service.events().insert(calendarId='primary', body=event_body).execute()
                return created_event.get("id")

            event_id = await asyncio.to_thread(_create_google_event_sync)
            return {
                "id": event_id,
                "status": "success",
                "tipo": "google"
            }
        except Exception as e:
            logger.warning(f"Error creando evento '{title}' en Google Calendar: {e}. Usando simulación.")
            use_fallback = True
            
    elif calendar_tipo == "outlook":
        try:
            event_id = await _create_outlook_event(title, start, end, attendee_email)
            return {
                "id": event_id,
                "status": "success",
                "tipo": "outlook"
            }
        except Exception as e:
            logger.warning(
                f"FALLBACK CALENDARIO: Error creando evento '{title}' en Outlook Calendar vía Graph API: {e}. "
                f"Cayendo automáticamente a simulación en memoria.", 
                exc_info=True
            )
            use_fallback = True
    else:
        use_fallback = True

    if use_fallback:
        import uuid
        event_id = f"sim_{uuid.uuid4().hex[:8]}"
        _simulated_events[event_id] = {
            "title": title,
            "start": start,
            "end": end,
            "attendee_email": attendee_email
        }
        return {
            "id": event_id,
            "status": "success",
            "tipo": "simulated"
        }

async def cancel_event(event_id: str) -> bool:
    """
    Cancela/elimina el evento con el ID indicado.
    """
    calendar_tipo = os.getenv("CALENDAR_TIPO", "outlook").strip().lower()
    logger.info(f"Cancelando evento {event_id} en {calendar_tipo}")
    
    if event_id.startswith("sim_"):
        if event_id in _simulated_events:
            del _simulated_events[event_id]
            logger.info(f"Evento simulado {event_id} cancelado con éxito.")
            return True
        return False
        
    if calendar_tipo == "google":
        try:
            def _cancel_google_event_sync():
                service = _get_google_client()
                service.events().delete(calendarId='primary', eventId=event_id).execute()
                return True
            return await asyncio.to_thread(_cancel_google_event_sync)
        except Exception as e:
            logger.error(f"Error cancelando evento en Google Calendar: {e}")
            return False
            
    elif calendar_tipo == "outlook":
        try:
            return await _cancel_outlook_event(event_id)
        except Exception as e:
            logger.error(f"Error cancelando evento en Outlook Calendar vía Graph API: {e}")
            return False
            
    return False
