import os
import sys
import logging
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_email")

def run_test():
    import email_adapter
    
    # Crear archivos de prueba locales temporales
    temp_dir = "./storage/temp"
    os.makedirs(temp_dir, exist_ok=True)
    
    pdf_test_path = os.path.join(temp_dir, "test_factura.pdf")
    with open(pdf_test_path, "wb") as f:
        f.write(b"%PDF-1.4 test invoice data")
        
    img_test_path = os.path.join(temp_dir, "test_triaje.jpg")
    with open(img_test_path, "wb") as f:
        f.write(b"fake image data")

    # 1. Test de envío real con configuración activa
    logger.info("--- Probando envío de correo con configuración activa ---")
    dest_email = os.getenv("GESTOR_EMAIL", "test@test.com")
    
    adjuntos = [
        {
            "filepath": pdf_test_path,
            "filename": "Factura_Test.pdf",
            "is_inline": False
        },
        {
            "filepath": img_test_path,
            "filename": "Averia_Test.jpg",
            "content_id": "foto_triaje",
            "is_inline": True
        }
    ]
    
    html_body_real = """
    <html>
    <body>
        <h2>[PRUEBA] Correo de validación Graph API</h2>
        <p>Este correo ha sido enviado utilizando el adaptador de Microsoft Graph API / SMTP.</p>
        <p>Imagen inline incorporada:</p>
        <img src="cid:foto_triaje" style="max-width:300px;" />
    </body>
    </html>
    """
    
    try:
        logger.info(f"Enviando correo real a {dest_email}...")
        res_real = email_adapter.enviar_email(
            destinatario=dest_email,
            asunto="[PRUEBA] Correo de validación Graph API",
            cuerpo_html=html_body_real,
            adjuntos=adjuntos
        )
        logger.info(f"Resultado de envío real: {res_real}")
    except Exception as e:
        logger.error(f"Fallo en envío de correo real: {e}")
        return False

    # 2. Test SMTP Fallback forzando EMAIL_TIPO=graph con secreto inválido
    logger.info("--- Probando fallback de Graph a SMTP ---")
    
    original_tipo = os.getenv("EMAIL_TIPO")
    original_secret = os.getenv("MS_CLIENT_SECRET")
    
    os.environ["EMAIL_TIPO"] = "graph"
    os.environ["MS_CLIENT_SECRET"] = "secret_invalido_de_prueba"
    
    html_body = """
    <html>
    <body>
        <h2>[PRUEBA] Correo de Fallback</h2>
        <p>Este correo prueba la caída a SMTP si Graph falla:</p>
        <img src="cid:foto_triaje" style="max-width:300px;" />
    </body>
    </html>
    """
    
    try:
        logger.info("Enviando correo con secreto inválido (debería dar warning de fallback a SMTP)...")
        success = email_adapter.enviar_email(
            destinatario=dest_email,
            asunto="[PRUEBA] Correo de Fallback Asistente",
            cuerpo_html=html_body,
            adjuntos=adjuntos
        )
        logger.info(f"Retorno de enviar_email en fallback: {success}")
        
    except Exception as e:
        logger.warning(f"Error esperado si SMTP tampoco tiene credenciales válidas en .env: {e}")
        logger.info("La caída de Graph a SMTP fue intentada correctamente.")
        
    finally:
        # Restaurar variables
        if original_tipo is not None:
            os.environ["EMAIL_TIPO"] = original_tipo
        else:
            del os.environ["EMAIL_TIPO"]
            
        if original_secret is not None:
            os.environ["MS_CLIENT_SECRET"] = original_secret
        else:
            del os.environ["MS_CLIENT_SECRET"]
            
    return True

if __name__ == "__main__":
    run_test()
