import os
import logging
import requests
from abc import ABC, abstractmethod
import graph_auth

logger = logging.getLogger("asistente.storage_adapter")

class StorageAdapter(ABC):
    @abstractmethod
    def guardar_archivo(self, ruta_logica: str, contenido_bytes: bytes) -> str:
        pass

    @abstractmethod
    def leer_archivo(self, ruta_logica: str) -> bytes:
        pass

    @abstractmethod
    def listar_archivos(self, carpeta_logica: str) -> list:
        pass

    @abstractmethod
    def eliminar_archivo(self, ruta_logica: str) -> bool:
        pass

class LocalStorageAdapter(StorageAdapter):
    def __init__(self):
        self.storage_ruta = os.getenv("STORAGE_RUTA", "./storage")

    def guardar_archivo(self, ruta_logica: str, contenido_bytes: bytes) -> str:
        # Prevenir barras iniciales duplicadas y guiar la ruta adecuadamente
        ruta_logica_clean = ruta_logica.lstrip("/")
        local_path = os.path.join(self.storage_ruta, *ruta_logica_clean.split("/"))
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, "wb") as f:
            f.write(contenido_bytes)
        logger.info(f"Archivo guardado localmente en: {local_path}")
        return local_path

    def leer_archivo(self, ruta_logica: str) -> bytes:
        ruta_logica_clean = ruta_logica.lstrip("/")
        local_path = os.path.join(self.storage_ruta, *ruta_logica_clean.split("/"))
        if not os.path.exists(local_path):
            raise FileNotFoundError(f"Archivo no encontrado en almacenamiento local: {local_path}")
        with open(local_path, "rb") as f:
            return f.read()

    def listar_archivos(self, carpeta_logica: str) -> list:
        ruta_logica_clean = carpeta_logica.lstrip("/")
        local_path = os.path.join(self.storage_ruta, *ruta_logica_clean.split("/"))
        if not os.path.exists(local_path) or not os.path.isdir(local_path):
            return []
        return os.listdir(local_path)

    def eliminar_archivo(self, ruta_logica: str) -> bool:
        ruta_logica_clean = ruta_logica.lstrip("/")
        local_path = os.path.join(self.storage_ruta, *ruta_logica_clean.split("/"))
        if os.path.exists(local_path):
            os.remove(local_path)
            logger.info(f"Archivo eliminado localmente: {local_path}")
            return True
        return False

class SharePointStorageAdapter(StorageAdapter):
    def _get_base_url(self) -> str:
        site_id = os.getenv("MS_SITE_ID")
        drive_id = os.getenv("MS_DRIVE_ID")
        if drive_id:
            return f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root"
        elif site_id:
            return f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive/root"
        else:
            raise ValueError("Falta configurar MS_SITE_ID o MS_DRIVE_ID para SharePoint.")

    def guardar_archivo(self, ruta_logica: str, contenido_bytes: bytes) -> str:
        token = graph_auth.get_access_token()
        base_url = self._get_base_url()
        # Asegurar barra simple en la url
        path = ruta_logica.lstrip("/")
        url = f"{base_url}:/{path}:/content"
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/octet-stream"
        }
        
        logger.info(f"Subiendo archivo a SharePoint: {path}")
        res = requests.put(url, headers=headers, data=contenido_bytes, timeout=30)
        res.raise_for_status()
        logger.info(f"Archivo subido con éxito a SharePoint: {path}")
        return path

    def leer_archivo(self, ruta_logica: str) -> bytes:
        token = graph_auth.get_access_token()
        base_url = self._get_base_url()
        path = ruta_logica.lstrip("/")
        url = f"{base_url}:/{path}:/content"
        
        headers = {
            "Authorization": f"Bearer {token}"
        }
        
        logger.info(f"Descargando archivo de SharePoint: {path}")
        res = requests.get(url, headers=headers, timeout=30)
        if res.status_code == 404:
            raise FileNotFoundError(f"Archivo no encontrado en SharePoint: {path}")
        res.raise_for_status()
        return res.content

    def listar_archivos(self, carpeta_logica: str) -> list:
        token = graph_auth.get_access_token()
        base_url = self._get_base_url()
        path = carpeta_logica.strip("/")
        if not path:
            url = f"{base_url}/children"
        else:
            url = f"{base_url}:/{path}:/children"
            
        headers = {
            "Authorization": f"Bearer {token}"
        }
        
        logger.info(f"Listando archivos en SharePoint: {path or 'root'}")
        res = requests.get(url, headers=headers, timeout=30)
        if res.status_code == 404:
            return []
        res.raise_for_status()
        
        items = res.json().get("value", [])
        return [item["name"] for item in items]

    def eliminar_archivo(self, ruta_logica: str) -> bool:
        token = graph_auth.get_access_token()
        base_url = self._get_base_url()
        path = ruta_logica.lstrip("/")
        url = f"{base_url}:/{path}"
        
        headers = {
            "Authorization": f"Bearer {token}"
        }
        
        logger.info(f"Eliminando archivo en SharePoint: {path}")
        res = requests.delete(url, headers=headers, timeout=30)
        if res.status_code in (200, 204):
            logger.info(f"Archivo eliminado con éxito de SharePoint: {path}")
            return True
        elif res.status_code == 404:
            logger.warning(f"Archivo no encontrado para eliminar en SharePoint: {path}")
            return False
        res.raise_for_status()
        return True

# Instancias de los adaptadores
_local_adapter = LocalStorageAdapter()
_sharepoint_adapter = SharePointStorageAdapter()

def _get_adapter():
    tipo = os.getenv("STORAGE_TIPO", "local").strip().lower()
    if tipo == "sharepoint":
        return _sharepoint_adapter
    return _local_adapter

def guardar_archivo(ruta_logica: str, contenido_bytes: bytes) -> str:
    tipo = os.getenv("STORAGE_TIPO", "local").strip().lower()
    if tipo == "sharepoint":
        try:
            return _sharepoint_adapter.guardar_archivo(ruta_logica, contenido_bytes)
        except Exception as e:
            logger.warning(
                f"FALLBACK ALMACENAMIENTO: Error guardando '{ruta_logica}' en SharePoint: {e}. "
                f"Cayendo automáticamente a almacenamiento local.", 
                exc_info=True
            )
    return _local_adapter.guardar_archivo(ruta_logica, contenido_bytes)

def leer_archivo(ruta_logica: str) -> bytes:
    tipo = os.getenv("STORAGE_TIPO", "local").strip().lower()
    if tipo == "sharepoint":
        try:
            return _sharepoint_adapter.leer_archivo(ruta_logica)
        except FileNotFoundError:
            raise
        except Exception as e:
            logger.warning(
                f"FALLBACK ALMACENAMIENTO: Error leyendo '{ruta_logica}' de SharePoint: {e}. "
                f"Cayendo automáticamente a almacenamiento local.", 
                exc_info=True
            )
    return _local_adapter.leer_archivo(ruta_logica)

def listar_archivos(carpeta_logica: str) -> list:
    tipo = os.getenv("STORAGE_TIPO", "local").strip().lower()
    if tipo == "sharepoint":
        try:
            return _sharepoint_adapter.listar_archivos(carpeta_logica)
        except Exception as e:
            logger.warning(
                f"FALLBACK ALMACENAMIENTO: Error listando '{carpeta_logica}' en SharePoint: {e}. "
                f"Cayendo automáticamente a almacenamiento local.", 
                exc_info=True
            )
    return _local_adapter.listar_archivos(carpeta_logica)

def eliminar_archivo(ruta_logica: str) -> bool:
    tipo = os.getenv("STORAGE_TIPO", "local").strip().lower()
    if tipo == "sharepoint":
        try:
            return _sharepoint_adapter.eliminar_archivo(ruta_logica)
        except Exception as e:
            logger.warning(
                f"FALLBACK ALMACENAMIENTO: Error eliminando '{ruta_logica}' en SharePoint: {e}. "
                f"Cayendo automáticamente a eliminación local.", 
                exc_info=True
            )
    return _local_adapter.eliminar_archivo(ruta_logica)
