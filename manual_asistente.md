# 📖 Manual de Capacidades del Asistente Virtual: MAIRA

MAIRA es un asistente virtual avanzado e inteligente desarrollado para **Lex Guardian**. Ha sido diseñado para operar de forma híbrida: atiende y automatiza la relación con los clientes directamente por WhatsApp y, al mismo tiempo, actúa como la **secretaria interna** y panel de control del gestor del negocio.

---

## 👥 1. Atención al Cliente (Modo Público)
Cuando un cliente escribe al número de WhatsApp de Lex Guardian, MAIRA clasifica de forma automática la intención del mensaje y lo procesa según las siguientes capacidades:

### 📅 Agenda y Gestión de Citas
- **Consulta de disponibilidad**: Permite consultar slots libres en tiempo real (integrado con Outlook u Office 365).
- **Reservas**: Agenda citas y registra la confirmación de forma automática.
- **Cancelaciones**: Cancela citas existentes con un mensaje conversacional.
- **Recordatorios**: Programa un aviso automático por WhatsApp 24 horas antes de la cita.

### 📄 Recepción y Registro de Gastos (Tickets)
- **Análisis de imágenes**: El cliente puede enviar directamente la foto de un ticket o factura de gastos por WhatsApp.
- **Procesamiento inteligente**: Extrae automáticamente los datos relevantes (emisor, importe, fecha, conceptos) y los procesa para su clasificación.

### 💼 Solicitud de Facturación
- **Emisión de facturas**: Recopila los datos de facturación necesarios (destinatario, CIF, concepto, importe) para que el gestor pueda emitir cobros de manera ágil.

### 🔧 Triaje de Presupuestos e Incidencias
- **Captura estructurada**: Si el cliente reporta una avería o solicita un presupuesto, MAIRA realiza un triaje conversacional para almacenar los datos detallados de la solicitud.

### 🧠 Base de Conocimiento Dinámica
- **Respuestas inteligentes**: MAIRA lee y consulta de forma transparente archivos de conocimiento locales (`knowledge.txt` o `knowledge.pdf`).
- Esto le permite responder preguntas frecuentes (FAQs), detallar tarifas orientativas o explicar plazos fiscales sin necesidad de cambiar el código de prompt rígido.

---

## 💾 2. Memoria del Cliente
MAIRA cuenta con memoria persistente entre conversaciones. Esto evita que los clientes recurrentes tengan que repetir su información:
- **Reconocimiento automático**: Identifica si el cliente ha escrito antes.
- **Inyección de contexto**: Almacena el nombre, la empresa, la fecha de primera visita y notas adicionales, presentándolos en el prompt de la IA de forma interna.
- **Trato personalizado**: Maira saludará al cliente por su nombre si ya lo conoce.

---

## 🚨 3. Escalado Humano
Cuando una consulta supera las capacidades automatizadas de MAIRA, el sistema cierra el bucle con el equipo humano de forma instantánea:
- **Detección inteligente**: Analiza la respuesta del bot para saber si se ha derivado o sugerido atención humana.
- **Tickets de soporte**: Genera un ticket en la base de datos local.
- **Notificaciones a Teams**: Envía una tarjeta estructurada en tiempo real al Microsoft Teams del equipo con el número del cliente, el motivo del ticket y las últimas interacciones.
- **Resolución bidireccional**: El gestor puede escribir comandos en Teams o usar el canal de gestor en WhatsApp para responder directamente al cliente a través del bot.

---

## 🛠️ 4. Modo Gestor (Comandos Privilegiados)
Si el mensaje entrante procede del teléfono móvil del dueño del negocio (`GESTOR_WHATSAPP`), MAIRA responde a comandos especiales de administración y diagnóstico en lugar del flujo de chat de clientes:

- `/ayuda` — Muestra el listado de comandos y formatos soportados.
- `/clientes_hoy` — Lista los números de teléfono activos hoy con un resumen de su primera consulta.
- `/resumen_semana` — Genera un resumen ejecutivo de las conversaciones de los últimos 7 días con Gemini y lo envía por Email.
- `/pendientes` — Filtra y lista a todos los clientes que tienen puntos de acción pendientes para el gestor.
- `/actualizar` — Permite dictar nueva información en lenguaje natural; el bot la añade al final del archivo de conocimiento (`knowledge.txt`) de forma automática.
- `/stats` — Indica estadísticas mensuales: conversaciones, citas, facturas emitidas y tickets de soporte pendientes.
- `/responder_{id} {mensaje}` — Permite al gestor enviar un WhatsApp personalizado al cliente en relación a un ticket de escalado y pasa el estado a `en_gestion`.

---

## ☀️ 5. Secretaria Interna
MAIRA gestiona la agenda privada del propio gestor y organiza sus quehaceres matutinos:

### Lenguaje Natural
El gestor puede programar su agenda simplemente hablándole a MAIRA:
- _"Apunta reunión con Hacienda mañana a las 10:30"_ ➔ Crea una cita interna.
- _"Hay que revisar los impuestos de García esta semana"_ ➔ Crea una tarea de la agenda.
- _"Recuérdame llamar a la Seguridad Social a las 16h"_ ➔ Registra un recordatorio.
- _"¿Qué tengo programado hoy?"_ ➔ Consulta y lista la agenda.
- _"La llamada a la Seguridad Social ya está hecha"_ ➔ Marca la tarea como completada automáticamente.

### Briefing Matutino Recurrente
Todos los días a la hora configurada (por defecto `09:00`):
1. **Recopila**: Citas del día, tareas pendientes, plazos fiscales de los próximos 7 días, tickets de clientes que requieren atención y el recuento de conversaciones de ayer.
2. **Redacta**: Utiliza la inteligencia de Gemini para formular un resumen ejecutivo natural en tono de secretaria eficiente.
3. **Distribuye**: Envía el resumen simultáneamente por **WhatsApp** al gestor, por **Teams Webhook** al canal de trabajo, y por **Email** con una tabla detallada de la agenda del día.
