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
- **Flujo**: Pregunta nombre, teléfono, descripción del problema, código postal, urgencia y solicita una foto. Un prompt multimodal con Gemini determina la categoría del oficio (fontanería, electricidad, etc.), evalúa la complejidad técnica de la avería (baja, media, alta) y redacta un resumen ejecutivo enviado de inmediato al profesional responsable por Telegram y Email.

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
| `TELEGRAM_TOKEN` | API | Token del bot de Telegram (alerta de profesionales). | `12345:AA...` |
| `WHATSAPP_TOKEN` | API | Token de acceso de Meta Developers. | `EAAG...` |
| `WHATSAPP_PHONE_ID` | API | ID de teléfono emisor en la API de Meta. | `123456789...` |
| `VERIFY_TOKEN` | Config | Token de verificación para configurar el webhook. | `pimia_secret_2026` |
| `GESTOR_WHATSAPP` | Admin | Teléfono de WhatsApp del administrador (recibe resúmenes). | `34600112233` |
| `GESTOR_CHAT_ID` | Admin | ID del chat de Telegram del gestor. | `987654321` |
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
