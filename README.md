# 🚀 Superasistente Comercial Genérico, Modular y Multicliente

Este proyecto es una plataforma empresarial avanzada para la creación y gestión de chatbots comerciales inteligentes. Está construido sobre **FastAPI** (Python) y se integra de forma nativa con **WhatsApp Cloud API** (Meta Developers) y **Web Chat**. 

El sistema utiliza **Google Gemini** para la comprensión del lenguaje natural (NLU), la clasificación de intenciones y la toma de decisiones. Gracias a su diseño modular, permite activar o desactivar funcionalidades específicas según las necesidades del negocio de forma aislada, todo configurado mediante variables de entorno en el archivo `.env` y directrices comerciales en `system_prompt.txt`.

---

## 📋 Índice
1. [Arquitectura del Sistema](#-arquitectura-del-sistema)
2. [Detector de Intenciones (Router)](#-detector-de-intenciones-router)
3. [Módulos Integrados](#-módulos-integrados)
4. [Estructura del Proyecto](#-estructura-del-proyecto)
5. [Endpoints de la API](#-endpoints-de-la-api)
6. [Configuración del Archivo `.env`](#-configuración-del-archivo-env)
7. [Instalación y Despliegue](#-instalación-y-despliegue)
8. [Personalización del System Prompt](#-personalización-del-system-prompt)

---

## ⚙️ Arquitectura del Sistema

El bot orquesta una conversación inteligente estructurada de la siguiente manera:

```
                  Mensaje entrante (WhatsApp / Web)
                                  │
                                  ▼
               ¿Hay una sesión conversacional activa?
              ├── SÍ: Continuar flujo de sesión (Triage / Tickets / Agenda)
              └── NO:
                      │
                      ▼
            Clasificador de Intenciones (Gemini 2.0 Flash)
             ├── AGENDA  ──> [Módulo Agenda (Calendarios/Citas)]
             ├── TICKET  ──> [Módulo Tickets (OCR Gasto)]
             ├── FACTURA ──> [Módulo Facturas (Emisión PDF)]
             ├── TRIAJE  ──> [Módulo Triaje (Presupuestos de avería)]
             └── CHAT    ──> [Modelo Conversacional Fallback + Prompt del negocio]
```

### Gestión de Estados
El bot cuenta con memoria a corto plazo en memoria (`dict` en Python) para controlar sesiones activas de flujos paso a paso:
- `triaje._triaje_sesiones`: Controla el triaje de averías.
- `tickets._tickets_pendientes`: Controla la confirmación de tickets de gastos.
- `agenda._ofrecidos_temp`: Controla la reserva de citas y selección de huecos disponibles.

---

## 🧠 Detector de Intenciones (Router)

El archivo [`router.py`](file:///c:/proyectos/automatizacion/EjercitoDeBots/asistente/router.py) utiliza `gemini-2.0-flash` para interceptar cada mensaje de texto nuevo e identificar su intención:
* **`AGENDA`**: Reserva de citas, consulta de fechas, cancelaciones o modificaciones.
* **`TICKET`**: Envío de imágenes de tickets, recibos o facturas recibidas de gastos.
* **`FACTURA`**: Solicitud de creación de facturas (ej. *"hazme una factura por 200€ a..."*).
* **`TRIAJE`**: Reporte de averías o solicitudes de presupuestos técnicos.
* **`CHAT`**: Preguntas frecuentes del negocio (precios, horarios, ubicación, saludos, etc.).

*Nota:* Si un módulo está configurado como inactivo (`MODULO_*=false` en el `.env`), el enrutador redirige automáticamente la conversación al flujo de **`CHAT`**.

---

## 📦 Módulos Integrados

### 1. Citas y Agenda (`modulos/agenda.py`)
Gestiona el calendario del profesional de forma inteligente.
- **Soporte de Calendarios**: Integra Google Calendar y Outlook Calendar mediante un adaptador unificado (`calendar_adapter.py`).
- **Lógica**: Detecta peticiones de citas, busca slots libres en tiempo real, propone alternativas al cliente y bloquea la reserva.
- **Recordatorios**: Emplea `APScheduler` para programar alertas previas automáticas enviadas al WhatsApp del cliente.

### 2. Gastos y Tickets (`modulos/tickets.py`)
Automatiza el escaneo de facturas recibidas y tickets de compra.
- **Flujo**: El usuario envía una foto del ticket. El sistema descarga la imagen usando la API de Media de WhatsApp, ejecuta un análisis multimodal con Gemini para extraer importes, conceptos, fecha, IVA y CIF, y pide confirmación al usuario para archivar el archivo y registrarlo en una hoja de cálculo Excel.

### 3. Emisión de Facturas (`modulos/facturas.py`)
Genera facturas oficiales en PDF para clientes del negocio.
- **Flujo**: Extrae mediante Inteligencia Artificial los datos del cliente emisor, receptor, concepto y el importe desde el mensaje del chat. Diseña un PDF oficial con la librería `fpdf2` y lo envía directamente por WhatsApp en formato documento.

### 4. Triaje de Presupuestos (`modulos/triaje.py`)
Interactúa de manera guiada con el cliente para presupuestar averías.
- **Flujo**: Pregunta nombre, teléfono, descripción del problema, código postal, urgencia y solicita una foto. Un prompt multimodal con Gemini determina la categoría del oficio (fontanería, electricidad, etc.), evalúa la complejidad técnica de la avería (baja, media, alta) y redacta un resumen ejecutivo enviado de inmediato al profesional responsable por Teams, WhatsApp y Email.

### 5. Gestión de Cobros (`modulos/cobrador.py`)
Permite lanzar avisos masivos de deudas pendientes.
- **Flujo**: Expone un endpoint HTTP `/cobrar` para integrarse con CRMs o software contable externo y enviar notificaciones de cobro automáticas personalizadas por WhatsApp.

### 6. Secretaría Inteligente (`secretaria.py`)
Un reporte consolidado para el administrador del negocio.
- **Flujo**: Ejecuta una tarea recurrente diaria (cron) a la hora configurada para procesar la base de datos y mandar un resumen ejecutivo al administrador de las citas de hoy, presupuestos pendientes y avisos importantes.

---

## 📁 Estructura del Proyecto

```
asistente/
├── main.py                   # Orquestador del servicio FastAPI y receptor de Webhooks.
├── router.py                 # Enrutador de intenciones basado en IA (Gemini 2.0 Flash).
├── llm.py                    # Cerebro conversacional fallback (Gemini 2.5 Flash).
├── database.py               # Gestión de base de datos SQLite (mensajes, citas, facturas).
├── whatsapp.py               # Cliente y gestor de integración con Meta API (Envío/Descarga).
├── calendar_adapter.py       # Adaptador unificado para Google Calendar y Outlook API.
├── client_memory.py          # Seguimiento de visitas y retención de perfil de usuario.
├── conversation_summary.py   # Detección de despedidas y generación de resúmenes de chats.
├── escalado_humano.py        # Detección de insatisfacción y alertas de escalado manual.
├── gestor_mode.py            # Comandos de administración directa por chat.
├── secretaria.py             # Briefings y reportes programados.
├── system_prompt.txt         # Identidad, reglas y contexto comercial activo del bot.
├── system_prompt_example.txt # Plantilla de ejemplo orientativa (Escape Room).
├── requirements.txt          # Dependencias y librerías necesarias de Python.
├── Dockerfile                # Configuración de Docker para contenedores.
├── .env.example              # Plantilla de configuración de variables.
└── modulos/                  # Submódulos específicos de funcionalidad.
    ├── agenda.py             # Lógica de gestión de reservas de citas.
    ├── tickets.py            # Procesamiento de OCR de tickets y contabilidad.
    ├── facturas.py           # Generación de PDFs de facturación.
    ├── triaje.py             # Clasificación de averías y triaje.
    └── cobrador.py           # Lanzamiento de notificaciones de impago.
```

---

## 📡 Endpoints de la API

* **`GET /`**: Comprobación de estado del servicio.
* **`GET /webhook`**: Validación inicial del webhook requerida por Meta Developers.
* **`POST /webhook`**: Recepción de eventos en tiempo real de WhatsApp (mensajes de texto e imágenes).
* **`POST /chat-web`**: Endpoint conversacional para integrar un Widget Web Chat o probar flujos conversacionales de forma rápida enviando JSON.
* **`POST /cobrar`**: Endpoint de integración para notificaciones externas de facturas vencidas.

---

## 🔑 Configuración del Archivo `.env`

Crea el archivo `.env` renombrando el archivo `.env.example` y configurando las variables del negocio:

| Variable | Tipo | Descripción | Ejemplo |
|---|---|---|---|
| `APP_NAME` | Config | Nombre descriptivo del bot. | `Pimia Asistente` |
| `GEMINI_API_KEY` | API | Clave de acceso a Google Gemini. | `AIzaSy...` |
| `WHATSAPP_TOKEN` | API | Token de acceso de Meta Developers. | `EAAG...` |
| `WHATSAPP_PHONE_ID` | API | ID de teléfono emisor en la API de Meta. | `123456789...` |
| `VERIFY_TOKEN` | Config | Token de verificación para configurar el webhook. | `pimia_secret_2026` |
| `GESTOR_WHATSAPP` | Admin | Teléfono de WhatsApp del administrador (recibe resúmenes). | `34600112233` |
| `TEAMS_WEBHOOK_URL` | API | URL del Incoming Webhook para canal de Teams. | `https://outlook.office.com/webhook/...` |
| `EMAIL_GESTOR` | Admin | Email del administrador del bot. | `admin@negocio.com` |
| `EMAIL_EMISOR` | SMTP | Email para enviar notificaciones de triaje y facturas. | `sistema@gmail.com` |
| `SMTP_PASSWORD` | SMTP | Contraseña de aplicación del email emisor. | `abcd efgh ijkl` |
| `CALENDAR_TIPO` | Mod Agenda | Tipo de calendario a usar (`google` o `outlook`). | `google` |
| `PROFESIONAL_WHATSAPP` | Mod Triaje | WhatsApp del profesional técnico a avisar. | `34611223344` |
| `PROFESIONAL_EMAIL` | Mod Triaje | Email del profesional técnico a avisar. | `tecnico@empresa.com` |
| `FACTURA_EMISOR_CIF` | Mod Factura| CIF del negocio para el PDF de factura. | `B12345678` |
| `MODULO_[X]` | Interruptor | Activa/Desactiva módulo (`true` o `false`). | `MODULO_AGENDA=true` |

---

## 🚀 Instalación y Despliegue

### 1. Configuración Local

**Instalar librerías:**
```bash
pip install -r requirements.txt
```

**Crear Base de Datos SQLite:**
La base de datos `chatbot.db` se crea e inicializa automáticamente con la estructura necesaria la primera vez que se inicia el servidor.

**Arrancar con Uvicorn:**
```bash
uvicorn main:app --host 0.0.0.0 --port 8050 --reload
```

El servidor estará escuchando en `http://localhost:8050`.

### 2. Despliegue con Docker

**Construcción de la imagen:**
```bash
docker build -t asistente-comercial .
```

**Ejecución del contenedor:**
```bash
docker run -d -p 8050:8050 --env-file .env --name asistente-comercial asistente-comercial
```

---

## 📝 Personalización del System Prompt

El comportamiento y conocimiento del asistente se definen por completo en [`system_prompt.txt`](file:///c:/proyectos/automatizacion/EjercitoDeBots/asistente/system_prompt.txt). 

Para reconfigurar el bot para otro cliente:
1. Edita [`system_prompt.txt`](file:///c:/proyectos/automatizacion/EjercitoDeBots/asistente/system_prompt.txt).
2. Modifica la **Identidad** (ej. *Max el Game Master* o *Sofía la recepcionista*), el **Negocio** (dirección, catálogo de servicios, precios) y las **Reglas de Comunicación**.
3. Guarda el archivo y reinicia el servicio. La Inteligencia Artificial adoptará los nuevos parámetros de forma inmediata sin alterar la lógica de programación del sistema.

---

## 🔑 Integración con Microsoft 365 (Graph API)

Maira utiliza la API de Microsoft Graph para centralizar la autenticación y gestionar documentos en SharePoint, correos en Outlook y eventos en el calendario.

### 📝 Registro de la Aplicación en Azure AD
Para permitir que el bot interactúe con el tenant de Microsoft 365, es necesario registrar una aplicación en Azure Portal:

1. **Crear Registro**:
   - Vaya a [Azure Portal](https://portal.azure.com/) > **Microsoft Entra ID** (anteriormente Azure Active Directory) > **App registrations** > **New registration**.
   - Asigne un nombre a la aplicación (ej. `Maira-Chatbot`).
   - Seleccione los tipos de cuenta soportados (normalmente "Accounts in this organizational directory only").
   - Haga clic en **Register**.

2. **Permisos de API (API permissions)**:
   - En el menú lateral izquierdo, seleccione **API permissions** > **Add a permission** > **Microsoft Graph**.
   - Seleccione **Application permissions** (Permisos de aplicación, ya que el bot actúa en segundo plano sin intervención humana).
   - Busque y marque los siguientes permisos:
     - `Files.ReadWrite.All` (Para almacenar facturas e imágenes de tickets en SharePoint).
     - `Mail.Send` (Para enviar emails con Outlook).
     - `Calendars.ReadWrite` (Para agendar y cancelar citas).
   - Haga clic en **Add permissions**.
   - **CRÍTICO**: El administrador del tenant debe pulsar en **Grant admin consent for [Nombre del Tenant]** para activar los permisos.

3. **Certificados y Secretos (Certificates & secrets)**:
   - Vaya a **Certificates & secrets** > **Client secrets** > **New client secret**.
   - Añada una descripción, establezca el vencimiento recomendado y pulse **Add**.
   - **Copie inmediatamente el "Value" del secreto**. Este valor no volverá a mostrarse y se configurará como `MS_CLIENT_SECRET`.

4. **Obtener IDs**:
   - Vaya a **Overview** y copie:
     - `Application (client) ID` (se configurará como `MS_CLIENT_ID`).
     - `Directory (tenant) ID` (se configurará como `MS_TENANT_ID`).

5. **Obtener MS_SITE_ID**:
   - Puede obtener el ID de su sitio de SharePoint realizando una petición a:
     `GET https://graph.microsoft.com/v1.0/sites/{domain}.sharepoint.com:/sites/{site-name}`
     El ID obtenido tiene el formato `{domain}.sharepoint.com,{site-id},{web-id}`.

---

## ⚠️ Reconciliación tras Fallback Local (Nota Operativa)

Si Microsoft Graph no está disponible (red, credenciales incorrectas, expiración, etc.), Maira activará de forma automática el **fallback local/SMTP/simulado**:
- Las facturas y fotos de tickets de gasto se guardarán localmente en la carpeta local `/storage`.
- Los emails se enviarán vía SMTP.
- La agenda de citas utilizará la simulación en memoria.

> [!IMPORTANT]
> **Acción del Administrador**: Tras restablecer la conexión con Graph, los archivos guardados localmente durante la caída **no se sincronizan de manera automática**. El gestor técnico de IT debe revisar la carpeta `/storage` del servidor y subir manualmente a la biblioteca de SharePoint correspondiente los archivos guardados para evitar asincronías.

---

## 📋 Alta de un nuevo cliente (gestoría)

Para desplegar Maira para una nueva gestoría, sin tocar código:

### Microsoft 365
- [ ] Registrar una app en Azure AD del tenant del cliente (o de Pimia, según el modelo de contrato) siguiendo los pasos de "Integración con Microsoft 365 (Graph API)".
- [ ] Rellenar las variables `MS_TENANT_ID`, `MS_CLIENT_ID`, `MS_CLIENT_SECRET`, `MS_SITE_ID` y `MS_DRIVE_ID` en el archivo `.env`.
- [ ] Ajustar `SHAREPOINT_CARPETA_FACTURAS` y `SHAREPOINT_CARPETA_TICKETS` si el cliente usa una convención de carpetas distinta.

### Datos fiscales y de negocio
- [ ] Configurar las variables `FACTURA_EMISOR_*` (nombre, CIF, dirección e IBAN del emisor de facturas).
- [ ] Configurar `GESTOR_WHATSAPP` y `GESTOR_EMAIL` (datos de contacto del gestor humano responsable).
- [ ] Configurar `PROFESIONAL_EMAIL` y `PROFESIONAL_WHATSAPP` si aplica el módulo de triaje de averías.
- [ ] Configurar `BRIEFING_HORA` (hora a la que se enviará el resumen matutino).

### Base de conocimiento
- [ ] Sustituir `knowledge.txt` / `knowledge.pdf` con la información específica del cliente (horarios, servicios, ubicación, FAQ).
- [ ] Revisar `system_prompt.txt` si el tono o el nombre del asistente cambia por cliente.

### Módulos activos
- [ ] Revisar qué variables `MODULO_[X]` activar o desactivar según el plan contratado por la gestoría (agenda, tickets, facturas, triaje, cobrador, etc.).

### Base de datos
- [ ] Confirmar que se arranca con una base de datos limpia (`chatbot.db` nuevo), no la de otro cliente ni la de desarrollo/pruebas.

---

## 👥 CRM y Gestión de Clientes (Fase 3)

Maira incluye un módulo CRM integrado en SQLite para clasificar a los usuarios entre **clientes activos** y **usuarios nuevos**:

### Detección y Tratamiento Diferenciado
- **Clientes Activos (`tipo_cliente = 'activo'`)**: Si el usuario tiene un expediente asignado, el bot inyecta automáticamente su ficha en el contexto del LLM para saludarle por su nombre y atenderle con el contexto completo de su expediente.
- **Consultas FAQ y Saludos**: Los saludos ("hola") y preguntas generales de FAQ desde números no registrados se responden con normalidad sin solicitar alta de forma disruptiva.
- **Flujo de Alta Automático (`alta_cliente.py`)**: Si un usuario nuevo solicita una acción que requiere identificación formal (`AGENDA`, `FACTURA`, `TICKET` o `TRIAJE`), se activa una máquina de estados para solicitar Nombre, NIF/CIF (opcional) y Motivo de consulta. Tras completar el registro, el bot reanuda y procesa la solicitud original.
- **Sin Repeticiones Molestas**: Si el usuario ya dio sus datos de alta (posee `nombre` registrado en SQLite), no se le vuelve a solicitar el alta en peticiones posteriores aunque su ficha siga en estado `nuevo` a la espera de la revisión del gestor.

### Comandos de Gestor para CRM (`gestor_mode.py`)
- **`/clientes_nuevos`**: Muestra la lista de clientes registrados en estado `nuevo` pendientes de revisión por el gestor.
- **`/alta_cliente {telefono} "{expediente}" "{nombre_opcional}"`**: Activa al cliente en el CRM, asignando su número de expediente definitivo y cambiando su estado a `activo`.
- **`/cliente_info {telefono}`**: Consulta y muestra la ficha completa de un cliente (datos personales, NIF/CIF, expediente, gestor asignado, notas e historial de visitas).
