# PROPUESTA_ANCLAJE_EXTERNO_MAIRA_CLAUDIA_V2

## Estado
V2 -- incorpora los 6 puntos del veredicto de Claudia sobre la V1 (31/08/2026: "diseño
conceptual válido / V2 criptográfica y operativa pendiente"). Implementado y probado en
`contrato_maira_claudia.py` (pruebas sintéticas, local). No conectado al flujo real de Maira, sin
producción ni datos reales.

## 1. Serialización canónica firmada (corrige: "IDENTIDAD_FIRMANTE sola no acredita nada")

El checkpoint completo ahora lleva:

```text
CHECKPOINT_ID, OPERATION_ID, SECUENCIA, HASH_CABEZA, HASH_PAQUETE, MOTIVO_SIN_PAQUETE,
FECHA_UTC, KEY_ID, ALGORITMO_FIRMA, VERSION_ESQUEMA, SIGNED_PAYLOAD_HASH, FIRMA, IDENTIDAD_FIRMANTE
```

`KEY_ID` identifica la clave/certificado real que firma -- `IDENTIDAD_FIRMANTE` queda solo como
etiqueta legible, nunca como acreditación por sí sola.

Especificación exacta de qué se firma: los campos `CAMPOS_FIRMADOS_ANCLAJE_V2` (los diez
primeros de la lista de arriba, en ESE orden exacto, versionados como esquema `2`), serializados
como `"{campo}={valor}"` uno por línea, UTF-8, sin JSON de por medio (evita la ambigüedad de
orden de claves/espacios que sí tendría JSON). `SIGNED_PAYLOAD_HASH` es el SHA-256 de esa
serialización. Cualquier cambio a la lista de campos firmados exige subir `VERSION_ESQUEMA`.

`verificar_checkpoint_estructural()` recalcula ese hash a partir del propio checkpoint y lo
compara -- detecta manipulación estructural ya en el prototipo, aunque la verificación
criptográfica real de `FIRMA` sigue pendiente del esquema de claves/PKI del spike (ver §6).

## 2. Checkpoints incompatibles y revocación de clave

`obtener_estado_confirmado()` agrupa los ACKs por `SECUENCIA`; si dos tienen distinto
`HASH_CABEZA` para la misma secuencia, lanza `CheckpointConflictivo` y queda en el log de error
-- nunca se elige uno en silencio, la proyección entera se bloquea.

`revocar_clave(key_id, motivo, fecha_utc)` registra una revocación inmutable (append-only, un
archivo por clave, nunca se reescribe). Un checkpoint firmado con una clave ya revocada en ese
momento no cuenta como confirmación (`_clave_revocada_antes_de`).

**Regla implementada, la más simple**: revocación hacia adelante -- invalida checkpoints
firmados después de la fecha de revocación, no los anteriores. **Pendiente de decidir con
vosotros**: si una revocación por compromiso de clave debe invalidar también checkpoints
anteriores (retroactivo). Lo dejamos como pregunta abierta de política, no lo resolvemos aquí.

## 3. HASH_PAQUETE deja de ser ambiguo

Ya no se toma del campo opcional del evento (que legítimamente puede estar vacío en transiciones
que no tocan documentos). Ahora se deriva **siempre** del hash real del paquete en disco para esa
`OPERATION_ID`. Si de verdad no existe paquete asociado: `HASH_PAQUETE = "NULL"` +
`MOTIVO_SIN_PAQUETE` explícito. Nunca cadena vacía ambigua.

## 4. Lectura mínima para Maira, no el almacén completo

Separamos dos almacenes:

- **Anclaje protegido** (`ANCLAJE_EXTERNO`): el checkpoint completo, con `FIRMA`,
  `SIGNED_PAYLOAD_HASH`, `ALGORITMO_FIRMA`, `IDENTIDAD_FIRMANTE`. En producción vive
  enteramente de vuestro lado; Maira no lo lee.
- **ACK** (`ACKS_ANCLAJE`): lo único que Maira lee -- `ACK_ID, CHECKPOINT_ID, OPERATION_ID,
  SECUENCIA, HASH_CABEZA, HASH_PAQUETE, KEY_ID, FECHA_UTC`. Sin `FIRMA` ni
  `SIGNED_PAYLOAD_HASH`. Probado explícitamente que el ACK no filtra esos campos.

Sobre "append-only debe imponerse técnicamente, no basta la convención": de acuerdo -- en el
prototipo aplicamos `O_CREAT|O_EXCL` (que sí depende del código y ya impide una segunda escritura
sobre el mismo archivo), pero permisos/retención/auditoría a nivel de almacenamiento real es
exactamente lo que el spike tiene que probar contra vuestro backend real, no algo que este módulo
pueda garantizar en local.

## 5. Instantánea estable + idempotencia/reintentos

`_simular_claudia_crear_checkpoint` ahora modela: lee la cabeza, la relee antes de firmar: si
cambió entre medias, reintenta sobre la cabeza nueva (hasta 3 intentos). Probado con una cabeza
que cambia real y de verdad a mitad del proceso -- el checkpoint resultante firma la cabeza
actualizada, nunca la obsoleta.

`notificar_cabeza_nueva` es idempotente por `SECUENCIA` (nombre de archivo determinista):
reintentar la notificación de la misma cabeza nunca duplica nada, incluida una carrera entre dos
llamadas concurrentes (capturada con `O_CREAT|O_EXCL` + lectura de lo ya existente en el
`FileExistsError`).

**Timeout/reintentos de más alto nivel** (si Maira no ve un ACK en X minutos, renotificar) es una
política de orquestación, no de este módulo -- se implementará en el planificador (`main.py`)
cuando esto se conecte al flujo real, no antes.

## 6. Ampliación del spike (además de los 13 puntos ya acordados)

14. Firma inválida (payload no coincide con `SIGNED_PAYLOAD_HASH`, o `FIRMA` no verifica contra
    la clave real una vez exista el esquema de PKI).
15. Clave revocada o rotada durante la ventana de una operación en curso.
16. Checkpoint duplicado (mismo `CHECKPOINT_ID`) y checkpoint conflictivo (misma secuencia,
    distinta cabeza) contra el mecanismo real, no solo el prototipo local.
17. La cadena cambia realmente durante la firma (concurrencia real, no simulada con un mock).
18. Notificación perdida o repetida -- confirmar que ninguno de los dos casos rompe nada.
19. Indisponibilidad del ancla externa -- qué le pasa a Maira si no puede leer el ACK a tiempo.

## Qué depende de quién

| Pendiente | De quién |
|---|---|
| Serialización canónica, KEY_ID, SIGNED_PAYLOAD_HASH, verificación estructural | Ya implementado y probado (sintético) |
| Detección de checkpoints conflictivos + revocación de clave (regla hacia adelante) | Ya implementado y probado |
| HASH_PAQUETE derivado del paquete real, nunca ambiguo | Ya implementado y probado |
| Separación almacén protegido / ACK mínimo | Ya implementado y probado |
| Instantánea estable + idempotencia de notificación | Ya implementado y probado |
| Política de revocación retroactiva por compromiso de clave | Pendiente de decidir junto con vosotros |
| Esquema real de claves/PKI y verificación criptográfica de FIRMA | Conjunto -- a decidir en el spike |
| Permisos/retención/auditoría reales del almacén protegido | LexGuardian, a probar en el spike |
| Puntos 14-19 del spike ampliado | LexGuardian (acceso) -- nosotros si se nos da acceso |
