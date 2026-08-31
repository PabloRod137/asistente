# PROPUESTA_ANCLAJE_EXTERNO_MAIRA_CLAUDIA_V1

## Estado
V1 -- responde a la decisión de Claudia del 31/08/2026 sobre el punto 5 del addendum de
BROKER_ACL_V4 ("necesitamos checkpoint firmado, inmutable y correlacionado por operación").
Implementado y probado en `contrato_maira_claudia.py` (pruebas sintéticas, local, sin datos
reales). No conectado al flujo real de Maira ni al almacén real de Claudia.

## Punto de partida
Claudia ya descartó el vigilante local actual como ancla suficiente ("corre cada minuto y aporta
SHA-256, deduplicación, mutex y registro JSONL, pero no consta que firme ni publique checkpoints
externos") y fijó el modelo: Maira notifica cada cabeza nueva solo como disparador; Claudia relee
la cadena por su cuenta desde la fuente, la verifica, y firma una copia independiente. Un evento
no queda firme hasta recibir ese checkpoint firmado y correlacionado.

Esta V1 propone el formato concreto de las dos piezas que faltaban por definir: la notificación
(disparador) y el checkpoint (ancla).

## 1. Notificación de cabeza nueva (Maira -> Claudia)

Deliberadamente mínima -- ningún campo de esta notificación debe tratarse como fuente de verdad,
solo dispara el proceso de verificación en el lado de Claudia:

```text
NOTIFICATION_ID
OPERATION_ID
SECUENCIA        -- orientativo únicamente (p. ej. para priorizar), Claudia debe recalcularlo
FECHA_UTC
```

Explícitamente **no incluye** `HASH_CABEZA` ni `HASH_PAQUETE` -- si los incluyéramos, existiría
la tentación de usarlos como atajo en vez de releer la cadena real, que es justo lo que Claudia
pidió evitar.

Cada notificación es un archivo independiente e inmutable
(`NOTIFICACIONES_CABEZA/{OPERATION_ID}/{SECUENCIA}_{timestamp}_{NOTIFICATION_ID}.json`), mismo
patrón de inmutabilidad que el resto del contrato.

## 2. Checkpoint canónico (Claudia -> almacén externo)

Con los campos exactos que pediste:

```text
CHECKPOINT_ID
OPERATION_ID
SECUENCIA
HASH_CABEZA
HASH_PAQUETE        -- puede ser "" si la cabeza no referencia un paquete; no se exige no-vacío
FECHA_UTC
IDENTIDAD_FIRMANTE
ALGORITMO_FIRMA
VERSION_ESQUEMA
FIRMA
```

Almacenamiento **append-only, fuera del control de Maira**: en el prototipo, Maira solo tiene una
función de simulación para pruebas (`_simular_claudia_crear_checkpoint`, marcada explícitamente
como solo-para-pruebas, mismo patrón ya usado para simular vuestra resolución de identidad) y una
función de **solo lectura** (`leer_checkpoints_externos`). Ninguna ruta de código de Maira escribe
ahí fuera de esa simulación de pruebas. En producción, ese almacén debería vivir literalmente en
vuestro lado (o en un sitio donde Maira solo tenga permiso de lectura).

## 3. Cuándo un evento se considera firme

Nueva función `obtener_estado_confirmado(operation_id)`, distinta de la proyección local ya
existente (`obtener_estado_actual`, que sigue siendo solo **provisional**):

- Calcula la cabeza local (misma verificación de siempre: secuencia, hashes, sin huecos ni
  bifurcaciones).
- Busca un checkpoint cuyo `SECUENCIA`, `HASH_CABEZA` y `HASH_PAQUETE` coincidan **exactamente**
  con la cabeza local.
- Si coincide: `{"firme": True, "checkpoint_id": ...}`.
- Si no hay checkpoint, o el que existe es de una cabeza anterior (por ejemplo, llegó un evento
  nuevo después del último checkpoint firmado): `{"firme": False, ...}` -- el estado nunca se
  reporta como definitivo solo porque la cadena local verifique.

Probado explícitamente: checkpoint ausente (no firme), checkpoint que coincide (firme), y
checkpoint desactualizado tras un evento posterior (vuelve a no firme hasta el siguiente
checkpoint).

## 4. Lo que queda pendiente, no resuelto en este prototipo

- **Verificación criptográfica real de `FIRMA`**: qué esquema de claves/PKI se usa, cómo Maira
  obtendría la clave pública para verificar, y quién la gestiona -- lo dejamos para decidir junto
  con el spike, el prototipo solo exige que el campo exista.
- **Dónde vive físicamente el almacén de anclaje**: si aprovecháis alguna extensión del vigilante
  actual o montáis algo nuevo, es decisión vuestra -- el contrato de campos de arriba es
  independiente de esa elección.
- **Cadencia**: ¿Claudia procesa notificaciones en tiempo real o en el mismo barrido periódico que
  ya tiene? No lo asumimos, es compatible con cualquiera de las dos.

## Qué depende de quién

| Pendiente | De quién |
|---|---|
| Formato de notificación y checkpoint | Ya implementado y probado (sintético) en `contrato_maira_claudia.py` |
| `obtener_estado_confirmado` (firme solo con checkpoint que coincide) | Ya implementado y probado |
| Esquema real de firma/PKI | Conjunto -- a decidir en el spike |
| Dónde y cómo genera Claudia el checkpoint real | LexGuardian/Claudia |
| Repetir contra el mecanismo real una vez decidido | Nuestra parte |
