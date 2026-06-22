# Superasistente Comercial Genérico y Multicliente

Este proyecto es una plataforma genérica de chatbot comercial que permite desplegar asistentes de venta y gestión independientes para cualquier tipo de negocio. Cada cliente se configura de forma aislada a nivel de configuración de entorno (`.env`) y de directrices comerciales (`system_prompt.txt`), sin necesidad de modificar el código fuente.

## Estructura de Archivos

```
asistente/
├── main.py               # Orquestador (FastAPI y enrutador de webhooks/sesiones)
├── router.py             # Detector de intenciones con Gemini
├── llm.py                # Interfaz conversacional fallback (Gemini 2.5 Flash)
├── database.py           # Gestor de base de datos SQLite (mensajería, citas y facturas)
├── whatsapp.py           # Adaptador de API de WhatsApp (mensajería y subida/descarga de media)
├── calendar_adapter.py   # Adaptador unificado de calendario (Outlook / Google Calendar)
├── modulos/
│   ├── agenda.py         # Módulo de citas (descubrimiento, reservas y recordatorios APScheduler)
│   ├── tickets.py        # Módulo de gastos/OCR de tickets y registro a Excel
│   ├── facturas.py       # Módulo de emisión de facturas en PDF (fpdf2) y envío automático
│   ├── triaje.py         # Módulo de recogida de presupuestos y alertas al profesional
│   └── cobrador.py       # Módulo de recordatorios de impago por WhatsApp
├── system_prompt.txt     # Información de la identidad y reglas del negocio
├── system_prompt_example.txt # Plantilla de ejemplo rellena con Escape Room Santander
├── .env.example          # Plantilla de variables de entorno
├── Dockerfile            # Configuración para despliegue en contenedores
├── requirements.txt      # Dependencias fijadas del proyecto
└── README.md             # Guía de onboarding y despliegue (este archivo)
```

## Guía de Onboarding para un Nuevo Cliente

Para dar de alta a un nuevo cliente en una instancia independiente del asistente, sigue los siguientes pasos:

### 1. Clonar o Instalar Dependencias
Asegúrate de tener Python 3.10 o superior y ejecuta:
```bash
pip install -r requirements.txt
```

### 2. Configurar Variables de Entorno
Copia el archivo de plantilla `.env.example` y renómbralo a `.env`:
```bash
cp .env.example .env
```
Rellena los siguientes campos obligatorios en el archivo `.env`:
- `GEMINI_API_KEY`: Tu clave de la API de Google Gemini.
- `WHATSAPP_TOKEN` y `WHATSAPP_PHONE_ID`: Credenciales de Meta Developer para el canal WhatsApp.
- `CALENDAR_TIPO`: Selecciona `google` o `outlook` según la preferencia del cliente y rellena las credenciales correspondientes.
- `FACTURA_EMISOR_*`: Rellena los datos fiscales del negocio que emitirá las facturas en PDF.
- `PROFESIONAL_WHATSAPP` y `PROFESIONAL_EMAIL`: Datos de contacto del autónomo/profesional del negocio para el módulo de Triaje.
- Modifica los toggles `MODULO_*=true/false` para activar o desactivar funcionalidades específicas.

### 3. Definir la Identidad del Negocio
Abre el archivo `system_prompt.txt` y describe el negocio completando cada sección:
- **IDENTIDAD**: Quién es el bot, qué tono usa y cómo debe presentarse.
- **NEGOCIO**: Qué servicios ofrece, horarios, ubicación física, precios, etc.
- **REGLAS DE COMUNICACIÓN**: Longitud del mensaje, estilo y emojis permitidos.
- **LO QUE NO DEBES HACER**: Restricciones del bot.

*(Puedes guiarte usando el ejemplo provisto en `system_prompt_example.txt`)*

### 4. Arrancar la Aplicación
Puedes iniciar el servidor localmente ejecutando:
```bash
python main.py
```
O con Uvicorn:
```bash
uvicorn main:app --host 0.0.0.0 --port 8050 --reload
```

---

## Verificación de Funcionalidades y Endpoints

### 1. Endpoint de Webhook (Meta Developer)
- **GET `/webhook`**: Verificación de webhook requerida por Facebook. Usa el token configurado en `VERIFY_TOKEN`.
- **POST `/webhook`**: Canal principal por el que llegan los mensajes e imágenes del cliente a través de WhatsApp Cloud API.

### 2. Sandbox Conversacional Web
- **POST `/chat-web`**:
  Envía una solicitud HTTP con JSON para probar la conversación sin pasar por WhatsApp:
  ```json
  {
    "mensaje": "Hola, ¿tenéis citas para mañana?",
    "phone_number": "user_prueba_123"
  }
  ```

### 3. Recordatorios de Impago
- **POST `/cobrar`**:
  Endpoint HTTP expuesto para que tu orquestador externo lance avisos de cobro por WhatsApp:
  ```json
  {
    "telefono": "34666555444",
    "mensaje": "Hola, te recordamos que tienes la factura Nº 00123 pendiente por importe de 450€."
  }
  ```
