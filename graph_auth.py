import os
import time
import logging
import asyncio
import msal

logger = logging.getLogger("asistente.graph_auth")

class GraphAuthManager:
    def __init__(self):
        self._token = None
        self._expires_at = 0

    def get_token(self) -> str:
        """
        Retorna el token de acceso de MS Graph usando Client Credentials.
        Utiliza un caché en memoria con expiración.
        """
        now = time.time()
        # Si ya tenemos un token y expira en más de 5 minutos (300 segundos), lo reutilizamos.
        if self._token and self._expires_at > now + 300:
            return self._token

        tenant_id = os.getenv("MS_TENANT_ID")
        client_id = os.getenv("MS_CLIENT_ID")
        client_secret = os.getenv("MS_CLIENT_SECRET")

        if not tenant_id or not client_id or not client_secret:
            raise ValueError(
                "Faltan credenciales de Microsoft Graph en el entorno. "
                "Por favor, configure MS_TENANT_ID, MS_CLIENT_ID y MS_CLIENT_SECRET en su archivo .env."
            )

        authority = f"https://login.microsoftonline.com/{tenant_id}"
        
        logger.info("Solicitando nuevo token de acceso a Microsoft Graph (MSAL Client Credentials)...")
        app = msal.ConfidentialClientApplication(
            client_id,
            authority=authority,
            client_credential=client_secret
        )

        # Para Client Credentials, el scope debe ser exactamente "https://graph.microsoft.com/.default"
        scopes = ["https://graph.microsoft.com/.default"]
        
        # Primero intentamos adquirir del caché interno de MSAL
        result = app.acquire_token_silent(scopes, account=None)
        
        if not result:
            result = app.acquire_token_for_client(scopes=scopes)

        if "access_token" in result:
            self._token = result["access_token"]
            expires_in = result.get("expires_in", 3600)
            self._expires_at = now + expires_in
            logger.info(f"Token de acceso adquirido correctamente. Expira en {expires_in} segundos.")
            return self._token
        else:
            error = result.get("error")
            error_description = result.get("error_description")
            err_msg = f"Error al adquirir token de MS Graph: {error} - {error_description}"
            logger.error(err_msg)
            raise RuntimeError(err_msg)

    async def get_token_async(self) -> str:
        now = time.time()
        if self._token and self._expires_at > now + 300:
            return self._token
        try:
            return await asyncio.to_thread(self.get_token)
        except Exception as e:
            # Import diferido: alertas_desarrollador -> email_adapter -> graph_auth formaría un
            # ciclo si se importara a nivel de módulo.
            import alertas_desarrollador
            await alertas_desarrollador.enviar_alerta_desarrollador(
                clave="graph_auth_fallo",
                asunto="Fallo de autenticación con Microsoft Graph",
                mensaje=(
                    f"No se pudo obtener un token de acceso de Microsoft Graph: {e}\n\n"
                    "Revisa MS_CLIENT_ID, MS_CLIENT_SECRET y MS_TENANT_ID en el .env, y que "
                    "el secreto no haya caducado (Azure Portal > Entra ID > App registrations "
                    "> Maira > Certificates & secrets)."
                )
            )
            raise

# Instancia singleton para ser importada por otros adaptadores
auth_manager = GraphAuthManager()

async def get_access_token() -> str:
    return await auth_manager.get_token_async()
