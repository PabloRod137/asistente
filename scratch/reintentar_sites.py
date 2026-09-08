import asyncio
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import httpx
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
import graph_auth


async def intentar_una_vez():
    token = await graph_auth.get_access_token()
    headers = {'Authorization': f'Bearer {token}'}
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get('https://graph.microsoft.com/v1.0/sites/root', headers=headers)
        return r.status_code, r.text


async def main():
    intentos = 20
    espera_segundos = 90
    for intento in range(1, intentos + 1):
        try:
            status, texto = await intentar_una_vez()
        except Exception as e:
            print(f"Intento {intento}: excepcion {type(e).__name__}: {e}")
            await asyncio.sleep(espera_segundos)
            continue

        print(f"Intento {intento}: {status}")
        if status == 200:
            print("EXITO")
            print(texto[:2000])
            return
        await asyncio.sleep(espera_segundos)
    print("AGOTADOS LOS INTENTOS, SIGUE FALLANDO")

asyncio.run(main())
