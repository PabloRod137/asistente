import os
import logging
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

def _get_outlook_account():
    from O365 import Account, MSOffice365Protocol
    
    tenant_id = os.getenv("O365_TENANT_ID")
    client_id = os.getenv("O365_CLIENT_ID")
    client_secret = os.getenv("O365_CLIENT_SECRET")
    
    if not tenant_id or not client_id or not client_secret:
        raise ValueError("Faltan credenciales de O365 (tenant_id, client_id, client_secret)")
        
    credentials = (client_id, client_secret)
    protocol = MSOffice365Protocol()
    account = Account(credentials, auth_flow_type='credentials', tenant_id=tenant_id, protocol=protocol)
    
    if not account.is_authenticated:
        if not account.authenticate():
            raise RuntimeError("Fallo en la autenticación de O365")
            
    return account

def get_free_slots(date_str: str, duration_minutes: int = 60) -> list:
    """
    date_str: Formato 'YYYY-MM-DD'
    Retorna una lista de diccionarios: [{'start': 'YYYY-MM-DDTHH:MM:SS', 'end': 'YYYY-MM-DDTHH:MM:SS'}]
    """
    calendar_tipo = os.getenv("CALENDAR_TIPO", "outlook").strip().lower()
    logger.info(f"Obteniendo huecos libres para {date_str} usando {calendar_tipo}")
    
    # 1. Definir los huecos de trabajo posibles (ej: de 09:00 a 18:00 cada 'duration_minutes')
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

    # 2. Intentar usar la API correspondiente o fallback
    events = []
    use_fallback = False
    
    if calendar_tipo == "google":
        try:
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
            
            for event in events_result.get('items', []):
                start_str = event['start'].get('dateTime') or event['start'].get('date')
                end_str = event['end'].get('dateTime') or event['end'].get('date')
                # Parsear fechas de Google (ej: '2026-05-28T10:00:00+02:00')
                # Simplificamos asumiendo la zona horaria local o cortando para comparar
                try:
                    start_dt = datetime.fromisoformat(start_str.split('+')[0].split('Z')[0])
                    end_dt = datetime.fromisoformat(end_str.split('+')[0].split('Z')[0])
                    events.append((start_dt, end_dt))
                except Exception as ex:
                    logger.warning(f"Error parseando fechas del evento Google: {ex}")
        except Exception as e:
            logger.warning(f"Error conectando con Google Calendar: {e}. Usando simulación.")
            use_fallback = True
            
    elif calendar_tipo == "outlook":
        try:
            account = _get_outlook_account()
            schedule = account.schedule()
            calendar = schedule.get_default_calendar()
            
            # Definir rango
            q = calendar.new_query()
            q.datetime_custom('start').greater_equal(base_date)
            q.datetime_custom('end').less_equal(base_date + timedelta(days=1))
            
            outlook_events = calendar.get_events(query=q, include_recurring=True)
            for event in outlook_events:
                # O365 datetime objects son timezone aware o naive dependiento de la config, los convertimos a naive locales
                start_dt = event.start.replace(tzinfo=None)
                end_dt = event.end.replace(tzinfo=None)
                events.append((start_dt, end_dt))
        except Exception as e:
            logger.warning(f"Error conectando con Outlook Calendar: {e}. Usando simulación.")
            use_fallback = True
    else:
        use_fallback = True

    if use_fallback:
        # Usar la lista de eventos simulados
        for ev_id, ev_info in _simulated_events.items():
            ev_start = datetime.fromisoformat(ev_info["start"])
            ev_end = datetime.fromisoformat(ev_info["end"])
            if ev_start.date() == base_date.date():
                events.append((ev_start, ev_end))

    # 3. Filtrar los slots potenciales eliminando los que se solapen con eventos
    free_slots = []
    for slot in potential_slots:
        overlap = False
        for ev_start, ev_end in events:
            # Comprobar solapamiento: (start1 < end2) and (end1 > start2)
            if slot["start"] < ev_end and slot["end"] > ev_start:
                overlap = True
                break
        if not overlap:
            free_slots.append({
                "start": slot["start"].isoformat(),
                "end": slot["end"].isoformat()
            })
            
    return free_slots

def create_event(title: str, start: str, end: str, attendee_email: str = None) -> dict:
    """
    Crea un evento en el calendario.
    start / end en formato ISO 'YYYY-MM-DDTHH:MM:SS'
    """
    calendar_tipo = os.getenv("CALENDAR_TIPO", "outlook").strip().lower()
    logger.info(f"Creando evento '{title}' de {start} a {end} en {calendar_tipo}")
    
    use_fallback = False
    
    if calendar_tipo == "google":
        try:
            service = _get_google_client()
            event_body = {
                'summary': title,
                'start': {
                    'dateTime': f"{start}",
                    'timeZone': 'Europe/Madrid',
                },
                'end': {
                    'dateTime': f"{end}",
                    'timeZone': 'Europe/Madrid',
                }
            }
            if attendee_email:
                event_body['attendees'] = [{'email': attendee_email}]
                
            created_event = service.events().insert(calendarId='primary', body=event_body).execute()
            return {
                "id": created_event.get("id"),
                "status": "success",
                "tipo": "google"
            }
        except Exception as e:
            logger.warning(f"Error creando evento en Google Calendar: {e}. Usando simulación.")
            use_fallback = True
            
    elif calendar_tipo == "outlook":
        try:
            account = _get_outlook_account()
            schedule = account.schedule()
            calendar = schedule.get_default_calendar()
            
            new_event = calendar.new_event()
            new_event.subject = title
            new_event.start = datetime.fromisoformat(start)
            new_event.end = datetime.fromisoformat(end)
            if attendee_email:
                new_event.attendees.add(attendee_email)
                
            new_event.save()
            return {
                "id": new_event.object_id,
                "status": "success",
                "tipo": "outlook"
            }
        except Exception as e:
            logger.warning(f"Error creando evento en Outlook Calendar: {e}. Usando simulación.")
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

def cancel_event(event_id: str) -> bool:
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
            service = _get_google_client()
            service.events().delete(calendarId='primary', eventId=event_id).execute()
            return True
        except Exception as e:
            logger.error(f"Error cancelando evento en Google Calendar: {e}")
            return False
            
    elif calendar_tipo == "outlook":
        try:
            account = _get_outlook_account()
            schedule = account.schedule()
            calendar = schedule.get_default_calendar()
            event = calendar.get_event(event_id)
            if event:
                event.delete()
                return True
            return False
        except Exception as e:
            logger.error(f"Error cancelando evento en Outlook Calendar: {e}")
            return False
            
    return False
