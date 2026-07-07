import os
import sys
import logging
from dotenv import load_dotenv

# Asegurar que el path del proyecto esté en el sys.path para poder importar graph_auth
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Cargar variables de entorno
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_graph_auth")

def test_auth():
    try:
        import graph_auth
        logger.info("Intentando obtener token de acceso a Microsoft Graph...")
        token = graph_auth.get_access_token()
        logger.info("¡Éxito! Token obtenido.")
        logger.info(f"Token (primeros 30 caracteres): {token[:30]}...")
        
        # Realizar llamada simple de lectura a Graph (GET /sites/{site-id} o similar)
        import requests
        site_id = os.getenv("MS_SITE_ID")
        if not site_id:
            logger.warning("No se configuró MS_SITE_ID en el .env. Se saltará la llamada de prueba a Graph API.")
            return True
            
        url = f"https://graph.microsoft.com/v1.0/sites/{site_id}"
        headers = {
            "Authorization": f"Bearer {token}"
        }
        
        logger.info(f"Realizando llamada GET a {url}...")
        res = requests.get(url, headers=headers)
        if res.status_code == 200:
            logger.info("¡Llamada a Graph API exitosa!")
            logger.info(f"Detalles del sitio: {res.json().get('displayName')}")
            return True
        else:
            logger.error(f"Fallo en la llamada a Graph API. Código de respuesta: {res.status_code}")
            logger.error(f"Respuesta: {res.text}")
            return False
            
    except Exception as e:
        logger.error(f"Error durante la prueba de autenticación: {e}")
        return False

if __name__ == "__main__":
    success = test_auth()
    sys.exit(0 if success else 1)
