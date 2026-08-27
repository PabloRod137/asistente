# PROPUESTA_BROKER_ACL_MAIRA_CLAUDIA_V2

## Estado
V2 -- incorpora las 6 correcciones de Claudia sobre V1. Pendiente de validación. No implementado,
sin datos reales.

## 1. Cambio de arquitectura: separar el paquete inmutable del estado

Corrección de Claudia: un paquete `READY` **nunca se mueve ni se edita** — ni siquiera entre
`00_ORDENES_NUEVAS` y `05_VALIDADAS`. En vez de mover el archivo, las transiciones de estado se
registran en un **índice/registro de eventos aparte**, referenciando al paquete por su
`OPERATION_ID`:

```text
04_LOGS/eventos_estado.jsonl   (o equivalente -- un registro append-only, nunca se edita
                                 una línea ya escrita, solo se añaden nuevas)
```

Cada línea sería un evento inmutable en sí mismo: `{OPERATION_ID, ESTADO_NUEVO, FECHA_HORA, ACTOR}`.
El "estado actual" de una operación se calcula leyendo el evento más reciente para ese
`OPERATION_ID`, no moviendo el archivo original. Esto elimina de raíz la pregunta de si un
*record* bloqueado se puede mover: **nunca hace falta moverlo**.

## 2. Opción A (etiquetas de retención) -- verificación pendiente, no resuelta desde aquí

Claudia señala, con razón, que un *regulatory record* es excesivo e irreversible para este flujo
-- coincidimos en descartarlo. Quedaría el nivel *record* normal. Pero esto **no lo puedo
verificar yo**: requiere que alguien con acceso al centro de cumplimiento (Purview) de
LexGuardian compruebe:

- Si el plan de Microsoft 365 actual incluye etiquetas de retención.
- El comportamiento real de un *record* normal en OneDrive/SharePoint (no la documentación
  genérica de Microsoft, sino una prueba real en el propio tenant).
- Si un *record* normal puede desbloquearse, y por quién exactamente.
- Con el cambio del punto 1 (el paquete nunca se mueve), la prueba de mover/renombrar deja de
  ser crítica, pero sigue siendo válido confirmar que un *record* no impide, al menos,
  **leerlo** con normalidad.

**Acción pendiente, no de mi parte**: pedirle a quien administre el cumplimiento en el tenant
de LexGuardian (¿Alberto, o su IT?) que compruebe esto y lo confirme.

## 3. Ubicación: fuera del OneDrive personal de Alberto

Aceptado sin objeción -- es la corrección más importante de esta ronda. El almacén productivo no
debe depender de la cuenta personal de una persona. Propuesta concreta:

- Migrar el árbol `PUENTE_AGENTES` (o, como mínimo, desplegar `03_MAIRA` desde el principio) a un
  **sitio de SharePoint propiedad de LexGuardian** (no una biblioteca personal), con identidades
  administradas o cuentas de servicio para el acceso, y auditoría activada.
- **Acción pendiente, no de mi parte**: decidir/crear ese sitio es una decisión de gobierno de
  LexGuardian (Alberto/Claudia), no algo que yo pueda decidir o ejecutar unilateralmente --
  aunque, si se me da acceso, puedo encargarme de la parte técnica de configurarlo.

## 4. Si se usa broker: alojado y operado por LexGuardian

Aceptado. Si finalmente se opta por un servicio broker en vez de (o además de) etiquetas de
retención:

- Debe ser el **único escritor** del almacén.
- Alojado y operado por LexGuardian, no por Maira/nuestro lado.
- Maira y Claudia solo llaman a su API, con mínimo privilegio, operaciones idempotentes
  (reutilizando `OPERATION_ID`/`CLAVE_IDEMPOTENTE` ya definidos en el contrato), y registro de
  auditoría de cada llamada.

## 5. Alcance y despliegue por fases

- **Alcance final**: todo `PUENTE_AGENTES`, incluyendo los canales ya existentes de Alexia.
- **Despliegue inicial**: solo `03_MAIRA`, con datos sintéticos (coincide con lo ya construido en
  `contrato_maira_claudia.py`). Extensión al resto del puente solo después de superar las pruebas
  de manipulación, duplicados y reintentos -- ya superadas en el prototipo sintético actual; para
  el despliegue real haría falta repetirlas contra el mecanismo definitivo (etiquetas de
  retención o broker, según se decida).

## Resumen de lo que falta y de quién depende

| Pendiente | De quién |
|---|---|
| Separar paquete inmutable de registro de estado en el diseño | Ya incorporado en esta V2 |
| Verificar licencia y comportamiento real de etiquetas de retención en el tenant | LexGuardian (Alberto/IT) |
| Decidir y crear el sitio SharePoint propiedad de LexGuardian para el puente | LexGuardian (gobierno) -- ejecución técnica puede ser nuestra si se da acceso |
| Construir el broker, si se opta por esa vía | LexGuardian (alojamiento y operación) |
| Adaptar `contrato_maira_claudia.py` al mecanismo definitivo una vez elegido | Nuestra parte |
