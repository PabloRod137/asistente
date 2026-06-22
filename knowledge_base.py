import os
import logging
import pdfplumber

logger = logging.getLogger(__name__)

# Memoria caché global
_cached_content = ""
_last_mtimes = {}  # file_path -> mtime

def cargar_conocimiento() -> str:
    """
    Carga el conocimiento del negocio desde knowledge.txt o knowledge.pdf.
    Cachea el resultado y lo recarga solo si el archivo ha sido modificado.
    """
    global _cached_content, _last_mtimes
    
    dir_path = os.path.dirname(os.path.abspath(__file__))
    txt_path = os.path.join(dir_path, "knowledge.txt")
    pdf_path = os.path.join(dir_path, "knowledge.pdf")
    
    current_mtimes = {}
    
    if os.path.exists(txt_path):
        current_mtimes[txt_path] = os.path.getmtime(txt_path)
    if os.path.exists(pdf_path):
        current_mtimes[pdf_path] = os.path.getmtime(pdf_path)
        
    # Si no existe ningún archivo de conocimiento, limpiamos caché y retornamos vacío
    if not current_mtimes:
        _cached_content = ""
        _last_mtimes = {}
        return ""
        
    # Si las marcas de tiempo coinciden exactamente con la caché, devolvemos la caché
    if current_mtimes == _last_mtimes:
        return _cached_content
        
    # Recargar contenido
    loaded_parts = []
    
    if txt_path in current_mtimes:
        try:
            with open(txt_path, "r", encoding="utf-8") as f:
                loaded_parts.append(f.read())
            logger.info("Cargado conocimiento desde knowledge.txt")
        except Exception as e:
            logger.error(f"Error leyendo knowledge.txt: {e}")
            
    if pdf_path in current_mtimes:
        try:
            pdf_text = []
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        pdf_text.append(text)
            loaded_parts.append("\n".join(pdf_text))
            logger.info("Cargado conocimiento desde knowledge.pdf")
        except Exception as e:
            logger.error(f"Error leyendo knowledge.pdf: {e}")
            
    _cached_content = "\n\n".join(loaded_parts)
    _last_mtimes = current_mtimes

    # Parsear plazos fiscales de forma automática ante cambios en el conocimiento
    try:
        import secretaria
        secretaria.parsear_y_guardar_plazos_txt(_cached_content)
    except Exception as se:
        logger.error(f"Error procesando plazos fiscales en base de conocimiento: {se}")

    return _cached_content
