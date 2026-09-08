import asyncio
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import httpx
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
import graph_auth

EMAIL = os.getenv("EMAIL_EMISOR")


async def main():
    token = await graph_auth.get_access_token()
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=15.0) as client:
        # Misma llamada exacta que usa calendar_adapter._get_outlook_events()
        print("--- Comprobando calendarView (lo que usa calendar_adapter.py de verdad) ---")
        params = {
            "startDateTime": "2026-08-26T00:00:00",
            "endDateTime": "2026-08-26T23:59:59",
            "$select": "subject,start,end",
            "$top": 10
        }
        r = await client.get(
            f"https://graph.microsoft.com/v1.0/users/{EMAIL}/calendar/calendarView",
            headers=headers, params=params
        )
        print(r.status_code, r.text[:500])

asyncio.run(main())
