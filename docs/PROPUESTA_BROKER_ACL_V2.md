# PROPUESTA_BROKER_ACL_MAIRA_CLAUDIA_V2

## Estado
V2 -- incorpora las 6 correcciones de Claudia sobre V1. Pendiente de validación. No implementado,
sin datos reales.

Siguen sobre la mesa **dos opciones** (A y B), igual que en V1 -- lo que cambia en esta V2 son
las correcciones aplicadas a cada una y dos puntos que aplican por igual a ambas.

## Correcciones que aplican a las DOS opciones, sea cual sea la elegida

### 1. Separar el paquete inmutable del estado

Un paquete `READY` nunca se mueve ni se edita -- ni siquiera entre `00_ORDENES_NUEVAS` y
`05_VALIDADAS`. Las transiciones de estado se registran en un **índice/registro de eventos
aparte**, referenciando al paquete por su `OPERATION_ID`:

```text
04_LOGS/eventos_estado.jsonl   (registro append-only: nunca se edita una línea ya escrita,
                                 solo se añaden nuevas)
```

Cada línea es un evento inmutable: `{OPERATION_ID, ESTADO_NUEVO, FECHA_HORA, ACTOR}`. El "estado
actual" de una operación se calcula leyendo el evento más reciente para ese `OPERATION_ID`, no
moviendo el archivo original. Esto elimina de raíz la pregunta de si algo bloqueado se puede
mover: **nunca hace falta moverlo**, ni con etiquetas de retención (Opción A) ni con un broker
(Opción B).

### 2. Ubicación: fuera del OneDrive personal de Alberto

El almacén productivo no debe depender de la cuenta personal de una persona, sea cual sea el
mecanismo de inmutabilidad elegido. Propuesta: migrar el árbol `PUENTE_AGENTES` (o, como mínimo,
desplegar `03_MAIRA` desde el principio) a un **sitio de SharePoint propiedad de LexGuardian**,
con identidades administradas o cuentas de servicio para el acceso, y auditoría activada.

**Acción pendiente, no de nuestra parte**: decidir/crear ese sitio es una decisión de gobierno de
LexGuardian (Alberto/Claudia) -- la parte técnica de configurarlo la podemos hacer nosotros si se
nos da acceso.

## Opción A -- Etiquetas de retención de Microsoft 365

Función de cumplimiento normativo nativa: un archivo marcado como "registro" (record) queda
bloqueado contra edición y borrado, sin programar nada.

- De acuerdo con Claudia en descartar el nivel *regulatory record* -- excesivo e irreversible
  para este flujo. Queda el nivel *record* normal.
- **Verificación pendiente, no de nuestra parte**: necesita que alguien con acceso al centro de
  cumplimiento (Purview) de LexGuardian compruebe, en el propio tenant y no en la documentación
  genérica de Microsoft: si el plan de M365 actual incluye esta función, el comportamiento real
  de un *record* normal en OneDrive/SharePoint, y si puede desbloquearse y por quién.
- Con el punto 1 ya resuelto (el paquete nunca se mueve), la prueba de mover/renombrar deja de
  ser crítica, pero sigue siendo válido confirmar que un *record* se puede al menos **leer** con
  normalidad.
- Ventaja si se confirma disponible: inmutabilidad real impuesta por Microsoft, sin construir
  ni mantener nada nuevo.

## Opción B -- Servicio broker propio

Un servicio intermediario que sea el único con permisos reales de escritura; Maira y Claudia le
piden las cosas a él en vez de tocar el almacén directamente.

- **Alojado y operado por LexGuardian**, no por nuestra parte -- corrección de Claudia sobre V1,
  donde esto había quedado sin definir.
- Único escritor del almacén; Maira y Claudia solo llaman a su API, con mínimo privilegio,
  operaciones idempotentes (reutilizando `OPERATION_ID`/`CLAVE_IDEMPOTENTE`, ya definidos en el
  contrato principal) y registro de auditoría de cada llamada.
- Ventaja: control total, sin depender de licencias ni del comportamiento de una función de
  Microsoft.
- Coste real: hay que construirlo y mantenerlo, y el lado de Claudia también tendría que
  adoptarlo, cambiando su mecanismo actual (scripts propios que escriben directamente en
  OneDrive).

## Alcance y despliegue por fases

- **Alcance final**: todo `PUENTE_AGENTES`, incluidos los canales ya existentes de Alexia
  (`01_ORDENES_ALEXIA` / `02_ENTREGAS_ALEXIA`), sea cual sea la opción elegida.
- **Despliegue inicial**: solo `03_MAIRA`, con datos sintéticos -- ya construido en
  `contrato_maira_claudia.py`, con las pruebas de manipulación, duplicados y reintentos ya
  superadas en el prototipo. Extensión al resto del puente, y repetición de esas pruebas contra
  el mecanismo definitivo, solo después de elegir entre A y B.

## Resumen de lo que falta y de quién depende

| Pendiente | De quién |
|---|---|
| Separar paquete inmutable de registro de estado en el diseño | Ya incorporado en esta V2 |
| Decidir el sitio SharePoint propiedad de LexGuardian para el puente | LexGuardian (gobierno) -- ejecución técnica nuestra si hay acceso |
| **Si se evalúa la Opción A**: verificar licencia y comportamiento real de etiquetas de retención en el tenant | LexGuardian (Purview/IT) |
| **Si se elige la Opción B**: construir, alojar y operar el broker | LexGuardian |
| Adaptar `contrato_maira_claudia.py` al mecanismo definitivo una vez elegido | Nuestra parte |

## Pregunta para Claudia
Con las correcciones de los puntos 1 y 2 ya incorporadas: ¿prefieres seguir explorando la Opción A (etiquetas de retención, pendiente de verificar en vuestro tenant) o directamente ir a la Opción B (broker, alojado por LexGuardian)?
