# DESPLIEGUE_SERVIDOR_TELEGRAM_V1 -- Maira en `pimia`, solo Telegram

## Alcance
Primer despliegue de Maira en el servidor `pimia`, que **ya sirve a clientes reales** (escape room de
Santander y Lex Guardian). Por eso: contenedor y volumen propios, límites de recursos, ningún puerto
abierto a internet y ningún cambio sobre lo que ya corre. WhatsApp queda para la siguiente fase.

**Fuera de esta fase:** WhatsApp (no hace falta `WHATSAPP_TOKEN` ni `META_APP_SECRET`), Microsoft 365,
la carpeta puente contra SharePoint, y cualquier dato del chatbot actual de Lex Guardian.

## Reglas
1. No se toca ningún contenedor, volumen, puerto ni carpeta que no sea de Maira.
2. El bot `@AgenteMairaBot` solo lo usa este contenedor. Dos procesos con el mismo token de Telegram
   se pelean por los mensajes.
3. Los secretos se escriben **en el servidor**, con `nano`. No se pegan en chats ni se suben a git.
4. Si algo sale mal: `docker compose down` en la carpeta de Maira. Es lo único que hay que parar.

## Paso 0 -- Comprobación previa (solo lectura, en el servidor)

```bash
docker compose version          # necesita el plugin "compose"; si falla, avisa y usamos docker run
docker ps --format "{{.Names}} | {{.Ports}}"
ss -tln | grep 8060 || echo "puerto 8060 libre"
df -h / | tail -1 ; free -h | sed -n 2p
```

Si el puerto 8060 está ocupado, elige otro y ponlo en el `.env` como `MAIRA_PANEL_PUERTO=8061`.

## Paso 1 -- Empaquetar y enviar el código (en tu PC, PowerShell, en la carpeta del proyecto)

```powershell
git archive -o maira.tar HEAD
scp maira.tar pimia:~/
Remove-Item maira.tar
```

`git archive` solo incluye lo que está en git: sin `.env`, sin bases de datos, sin credenciales.

## Paso 2 -- Desempaquetar y configurar (en el servidor)

```bash
mkdir -p ~/maira && tar -xf ~/maira.tar -C ~/maira && rm ~/maira.tar
cd ~/maira
cp deploy/env.servidor.example .env
chmod 600 .env
nano .env
```

En `nano`, rellena solo estas variables (guardar: `Ctrl+O`, Enter; salir: `Ctrl+X`):

| Variable | Qué poner |
|---|---|
| `GEMINI_API_KEY` | Una clave **con facturación activada**. Con el plan gratuito (20 peticiones/día) Maira deja de contestar. |
| `TELEGRAM_BOT_TOKEN` | El token de `@AgenteMairaBot` |
| `GESTOR_TELEGRAM_CHAT_ID` | Tu `chat_id` numérico de Telegram (comandos de gestor) |
| `VERIFY_TOKEN` | Un valor largo y aleatorio (no se usa sin WhatsApp, pero no lo dejes por defecto) |
| `PANEL_PASSWORD` | Una contraseña larga |

Deja todo lo demás como está: los módulos que necesitan WhatsApp, correo o Microsoft van
desactivados a propósito para que no fallen envíos ni salten alertas.

## Paso 3 -- Construir y arrancar (en el servidor)

```bash
docker compose up -d --build
```

Tarda unos minutos la primera vez. Usa como máximo 0,5 CPU y 512 MB una vez arrancado.

## Paso 4 -- Comprobar

```bash
docker compose ps                       # el estado debe pasar a "healthy" en ~1 minuto
docker compose logs --tail 40 maira     # sin "Traceback" ni errores de arranque
```

Después, desde el móvil, escribe «hola» a `@AgenteMairaBot`. Debe contestar.

## Paso 5 -- Ver el panel (opcional)

El panel solo escucha en el propio servidor. Desde tu PC:

```powershell
ssh -L 8060:127.0.0.1:8060 pimia
```

y abre `http://localhost:8060/panel` en el navegador (usuario: cualquiera; contraseña:
`PANEL_PASSWORD`).

## Parar, actualizar y borrar

| Acción | Comando (en `~/maira`) |
|---|---|
| Parar sin perder datos | `docker compose down` |
| Ver logs | `docker compose logs -f maira` |
| Actualizar a una versión nueva | repetir el paso 1 y el 2 (sin tocar `.env`) y `docker compose up -d --build` |
| **Borrar también los datos** | `docker compose down -v` (destructivo: elimina la base de datos de Maira) |

## Qué NO está probado todavía
- No se ha construido la imagen de Docker (Docker Desktop no estaba activo en el equipo donde se
  preparó). Se construye por primera vez en el servidor.
- El arranque de la aplicación sí se probó en un entorno limpio (endpoints, panel y ocultación de
  secretos en logs).
