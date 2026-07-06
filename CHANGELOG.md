# Changelog - Proyecto Maira

Historial de cambios y refactorizaciones realizadas sobre el asistente virtual Maira (Lex Guardian).

## [1.1.0] - 2026-07-06
### Added
- Solución definitiva a la condición de carrera en facturas:
  - Creación de migración de base de datos idempotente al inicio del servidor FastAPI (`database.py`) para dotar a la tabla `facturas` de `AUTOINCREMENT` real e inyección de datos antiguos.
  - Configuración centralizada de conexiones SQLite con `PRAGMA journal_mode=WAL;` y `PRAGMA busy_timeout=5000;` a través del helper `database.get_connection()`.
  - Refactorización de todos los módulos que acceden a base de datos (`client_memory.py`, `conversation_summary.py`, `escalado_humano.py`, `gestor_mode.py`, y `secretaria.py`) para utilizar la conexión centralizada con timeout preventivo de bloqueos concurrentes.
  - Eliminación de la llamada de lectura previa `get_next_factura_numero()` en el flujo de emisión de facturas, forzando la asignación atómica a través del `lastrowid` de `save_factura()`.
  - Red de seguridad (Robustez) ante caídas/bloqueos de la API de Gemini (ej: API Key filtrada): Inyección de regla heuristic directa para detectar intención `"FACTURA"` y parser regex alternativo en `facturas.py` para extraer datos de facturación si la llamada HTTP a Gemini falla.
  - Ajuste en generación de PDFs en `facturas.py` para reemplazar los caracteres especiales no ASCII (`Nº` por `Num.` y `€` por `EUR`) que producían excepciones críticas al renderizar Helvetica estándar.
- Prevención de fugas de archivos temporales en triaje:
  - Limpieza proactiva del archivo de imagen de triaje temporal de inmediato tras finalizar el flujo de triaje con éxito.
  - Programación de un job recurrente en `main.py` de APScheduler para ejecutar `limpiar_archivos_temporales_antiguos()` cada 12 horas, escaneando y eliminando de forma segura archivos huérfanos con más de 2 horas en `storage/temp/`.
- Limpieza de documentación obsoleta:
  - README.md actualizado eliminando variables y menciones a Telegram (`TELEGRAM_TOKEN`, `GESTOR_CHAT_ID`) y agregando documentación de `TEAMS_WEBHOOK_URL`.

### IMPORTANT - Guía de despliegue en producción (Hetzner)
- Antes de desplegar el refactor, el operador humano **debe realizar un backup manual** de la base de datos en el servidor de producción ejecutando:
  `cp chatbot.db chatbot.db.pre-migracion-facturas.bak`

---

## [1.0.0] - 2026-07-06
### Added
- Punto de partida inicial documentado mediante informe de auditoría técnica.
- Copia de seguridad local de la base de datos previa al refactor (`chatbot.db.bak`).
- Configuración de exclusiones de archivos de SQLite WAL (`chatbot.db-wal`, `chatbot.db-shm`) y backups en el archivo `.gitignore`.
