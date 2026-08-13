import os
import re
import logging
import asyncio
import pdfplumber

logger = logging.getLogger(__name__)

# Memoria caché global
_cached_content = ""
_last_mtimes = {}  # file_path -> mtime

# Encabezados de sección (estilo Markdown "## Título") que marcan contenido dirigido solo al
# equipo interno, nunca a un cliente. Se recorta antes de inyectarlo en el prompt de cara al
# cliente (llm.py) — no basta con la instrucción en texto libre dentro del propio knowledge.txt
# ("no compartir con clientes"), porque eso depende por completo de que el modelo la respete.
_PATRON_SECCION_INTERNA = re.compile(
    r"^##\s*Notas?\s+internas?.*?$(?:\n(?!##\s).*)*",
    re.IGNORECASE | re.MULTILINE
)

def _filtrar_contenido_interno(texto: str) -> str:
    """Elimina cualquier sección '## Notas internas ...' antes de devolver el conocimiento
    para uso de cara al cliente. El contenido crudo (sin filtrar) sigue siendo el que se cachea
    y el que se usa para el parseo interno de plazos fiscales."""
    return _PATRON_SECCION_INTERNA.sub("", texto).strip()

def cargar_conocimiento(incluir_notas_internas: bool = False) -> str:
    """
    Carga el conocimiento del negocio desde knowledge.txt o knowledge.pdf.
    Cachea el resultado y lo recarga solo si el archivo ha sido modificado.

    Por defecto (incluir_notas_internas=False, el caso de uso normal de cara al cliente en
    llm.py) se recorta cualquier sección "## Notas internas" antes de devolver el texto.
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
        
    if not current_mtimes:
        _cached_content = ""
        _last_mtimes = {}
        return ""
        
    if current_mtimes == _last_mtimes:
        return _cached_content if incluir_notas_internas else _filtrar_contenido_interno(_cached_content)
        
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

    try:
        import secretaria
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(secretaria.parsear_y_guardar_plazos_txt(_cached_content))
        except RuntimeError:
            asyncio.run(secretaria.parsear_y_guardar_plazos_txt(_cached_content))
    except Exception as se:
        logger.error(f"Error procesando plazos fiscales en base de conocimiento: {se}")

    return _cached_content if incluir_notas_internas else _filtrar_contenido_interno(_cached_content)
