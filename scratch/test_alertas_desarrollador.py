import os
import sys
import asyncio
import logging
from datetime import datetime, timedelta
from unittest.mock import patch, AsyncMock

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("test_alertas_desarrollador")

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

os.environ.setdefault("GEMINI_API_KEY", "mock_key_para_no_llamar_a_gemini_en_este_test")

import alertas_desarrollador
import graph_auth
import whatsapp

DEV_EMAIL_TEST = "dev_prueba@example.com"


async def run_tests():
    logger.info("================================================================================")
    logger.info("   PRUEBAS: ALERTAS PARA EL DESARROLLADOR")
    logger.info("================================================================================")

    os.environ["DEV_ALERT_EMAIL"] = DEV_EMAIL_TEST
    alertas_desarrollador._ultima_alerta_por_clave.clear()

    # -------------------------------------------------------------------------
    # 1. Sin DEV_ALERT_EMAIL configurado -> no intenta enviar nada
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 1: sin DEV_ALERT_EMAIL configurado ---")
    os.environ.pop("DEV_ALERT_EMAIL", None)
    with patch("email_adapter.enviar_email", new=AsyncMock(return_value=True)) as mock_enviar:
        await alertas_desarrollador.enviar_alerta_desarrollador("clave_test", "asunto", "mensaje")
        mock_enviar.assert_not_called()
    logger.info("✅ TEST 1 superado: sin DEV_ALERT_EMAIL, no se intenta enviar nada.")

    os.environ["DEV_ALERT_EMAIL"] = DEV_EMAIL_TEST

    # -------------------------------------------------------------------------
    # 2. Con DEV_ALERT_EMAIL -> envía correo al desarrollador
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 2: envío normal de alerta ---")
    with patch("email_adapter.enviar_email", new=AsyncMock(return_value=True)) as mock_enviar:
        await alertas_desarrollador.enviar_alerta_desarrollador("clave_test_2", "Fallo de prueba", "Detalle del fallo")
        mock_enviar.assert_called_once()
        kwargs = mock_enviar.call_args.kwargs
        assert kwargs["destinatario"] == DEV_EMAIL_TEST
        assert "Fallo de prueba" in kwargs["asunto"]
    logger.info("✅ TEST 2 superado: se envía al DEV_ALERT_EMAIL configurado.")

    # -------------------------------------------------------------------------
    # 3. Cooldown: la misma clave no reenvía dentro de la ventana
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 3: cooldown por clave ---")
    with patch("email_adapter.enviar_email", new=AsyncMock(return_value=True)) as mock_enviar:
        await alertas_desarrollador.enviar_alerta_desarrollador("clave_cooldown", "a", "m", cooldown_horas=12)
        await alertas_desarrollador.enviar_alerta_desarrollador("clave_cooldown", "a", "m", cooldown_horas=12)
        assert mock_enviar.call_count == 1, f"No debe reenviar dentro del cooldown, se llamó {mock_enviar.call_count} veces"
    logger.info("✅ TEST 3 superado: no reenvía la misma alerta dentro del cooldown.")

    # -------------------------------------------------------------------------
    # 4. verificar_caducidades: sin fecha configurada -> no hace nada
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 4: verificar_caducidades sin fecha configurada ---")
    os.environ.pop("MS_CLIENT_SECRET_EXPIRA", None)
    with patch("email_adapter.enviar_email", new=AsyncMock(return_value=True)) as mock_enviar:
        await alertas_desarrollador.verificar_caducidades()
        mock_enviar.assert_not_called()
    logger.info("✅ TEST 4 superado: sin MS_CLIENT_SECRET_EXPIRA, no avisa de nada.")

    # -------------------------------------------------------------------------
    # 5. verificar_caducidades: dentro de la ventana de 30 días -> avisa
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 5: secreto caduca en 10 días ---")
    alertas_desarrollador._ultima_alerta_por_clave.clear()
    fecha_futura = (datetime.now().date() + timedelta(days=10)).isoformat()
    os.environ["MS_CLIENT_SECRET_EXPIRA"] = fecha_futura
    with patch("email_adapter.enviar_email", new=AsyncMock(return_value=True)) as mock_enviar:
        await alertas_desarrollador.verificar_caducidades()
        mock_enviar.assert_called_once()
        assert "10 días" in mock_enviar.call_args.kwargs["asunto"]
    logger.info("✅ TEST 5 superado: avisa dentro de la ventana de 30 días con los días exactos.")

    # -------------------------------------------------------------------------
    # 6. verificar_caducidades: fuera de la ventana (60 días) -> no avisa todavía
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 6: secreto caduca en 60 días (aún no toca avisar) ---")
    alertas_desarrollador._ultima_alerta_por_clave.clear()
    fecha_lejana = (datetime.now().date() + timedelta(days=60)).isoformat()
    os.environ["MS_CLIENT_SECRET_EXPIRA"] = fecha_lejana
    with patch("email_adapter.enviar_email", new=AsyncMock(return_value=True)) as mock_enviar:
        await alertas_desarrollador.verificar_caducidades()
        mock_enviar.assert_not_called()
    logger.info("✅ TEST 6 superado: no avisa si faltan más de 30 días.")

    # -------------------------------------------------------------------------
    # 7. verificar_caducidades: ya caducado -> avisa con mensaje de urgencia
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 7: secreto ya caducado ---")
    alertas_desarrollador._ultima_alerta_por_clave.clear()
    fecha_pasada = (datetime.now().date() - timedelta(days=3)).isoformat()
    os.environ["MS_CLIENT_SECRET_EXPIRA"] = fecha_pasada
    with patch("email_adapter.enviar_email", new=AsyncMock(return_value=True)) as mock_enviar:
        await alertas_desarrollador.verificar_caducidades()
        mock_enviar.assert_called_once()
        assert "CADUCADO" in mock_enviar.call_args.kwargs["asunto"]
    logger.info("✅ TEST 7 superado: si ya caducó, avisa con urgencia.")

    os.environ.pop("MS_CLIENT_SECRET_EXPIRA", None)

    # -------------------------------------------------------------------------
    # 8. graph_auth: un fallo real de autenticación dispara la alerta y re-lanza el error
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 8: fallo de autenticación de Graph dispara alerta ---")
    alertas_desarrollador._ultima_alerta_por_clave.clear()
    manager = graph_auth.GraphAuthManager()
    with patch.object(manager, "get_token", side_effect=RuntimeError("secreto invalido")), \
         patch("alertas_desarrollador.enviar_alerta_desarrollador", new=AsyncMock()) as mock_alerta:
        try:
            await manager.get_token_async()
            assert False, "Debe relanzar la excepción original"
        except RuntimeError:
            pass
        mock_alerta.assert_called_once()
        assert mock_alerta.call_args.kwargs["clave"] == "graph_auth_fallo"
    logger.info("✅ TEST 8 superado: fallo de Graph dispara la alerta y no oculta el error original.")

    # -------------------------------------------------------------------------
    # 9. whatsapp: un 401 al enviar dispara la alerta de token inválido
    # -------------------------------------------------------------------------
    logger.info("\n--- TEST 9: 401 de WhatsApp dispara alerta de token inválido ---")
    alertas_desarrollador._ultima_alerta_por_clave.clear()
    os.environ["WHATSAPP_TOKEN"] = "token_de_prueba"
    os.environ["WHATSAPP_PHONE_ID"] = "id_de_prueba"

    import httpx

    class RespuestaFalsa401:
        status_code = 401
        text = '{"error": "token invalido"}'

        def raise_for_status(self):
            raise httpx.HTTPStatusError("401", request=None, response=self)

    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=RespuestaFalsa401())), \
         patch("alertas_desarrollador.enviar_alerta_desarrollador", new=AsyncMock()) as mock_alerta:
        resultado = await whatsapp.send_whatsapp_message("34600000000", "hola")
        assert resultado is False
        mock_alerta.assert_called_once()
        assert mock_alerta.call_args.kwargs["clave"] == "whatsapp_token_invalido"
    logger.info("✅ TEST 9 superado: un 401 de WhatsApp dispara la alerta de token inválido.")

    logger.info("\n================================================================================")
    logger.info("   ✅ TODAS LAS PRUEBAS DE ALERTAS DE DESARROLLADOR PASARON CORRECTAMENTE")
    logger.info("================================================================================")

    os.environ.pop("DEV_ALERT_EMAIL", None)
    alertas_desarrollador._ultima_alerta_por_clave.clear()


if __name__ == "__main__":
    asyncio.run(run_tests())
