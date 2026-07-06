# Changelog - Proyecto Maira

Historial de cambios y refactorizaciones realizadas sobre el asistente virtual Maira (Lex Guardian).

## [1.0.0] - 2026-07-06
### Added
- Punto de partida inicial documentado mediante informe de auditoría técnica.
- Copia de seguridad local de la base de datos previa al refactor (`chatbot.db.bak`).
- Configuración de exclusiones de archivos de SQLite WAL (`chatbot.db-wal`, `chatbot.db-shm`) y backups en el archivo `.gitignore`.
