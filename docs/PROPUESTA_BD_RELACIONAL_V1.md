# PROPUESTA_BD_RELACIONAL_MAIRA_CLAUDIA_V1

## Estado
Propuesta V1 (21/09/2026), planteada por Pablo y Alberto. **No implementada, sin datos reales,
pendiente de validación por Claudia y LexGuardian.** No sustituye ningún documento aprobado: si se
acepta, se convierte en un contrato V5 que reemplaza solo el *mecanismo de transporte* del V4.

## 1. Idea en una frase

Sustituir la carpeta puente de SharePoint por una **base de datos relacional alojada y
administrada por LexGuardian** que sea el canal entre Maira y Claudia (órdenes, entregas, acuses y
eventos), manteniendo íntegros los principios ya aprobados. La base de datos es un **bus de
mensajes con garantías**, no una copia de los datos de los clientes.

## 2. Por qué

Buena parte del contrato V4 y del spike existen porque SharePoint no es una base de datos: hay que
simular con archivos lo que un motor relacional da de serie.

| Problema del diseño actual | Qué da un motor relacional |
|---|---|
| Secuencia atómica y bifurcación (spike 6, 11) | `UNIQUE (operation_id, secuencia)`: compare-and-swap real, no simulado con `O_CREAT\|O_EXCL` |
| Inmutabilidad "solo a nivel de aplicación" (V4, Addendum 5) | Permisos reales por rol: `INSERT`/`SELECT` sí, `UPDATE`/`DELETE` no |
| `.partial` + renombrado atómico, ventana de latencia (spike 7) | Una transacción: o se ve entera o no existe |
| Idempotencia por comando y ACK | Clave única + `INSERT ... ON CONFLICT` |
| Latencia de sondeo (job cada N minutos) | Consulta directa o notificación |
| Marca de tiempo declarada por el firmante (spike 22) | Marca de tiempo asignada por el servidor de base de datos |

## 3. Qué NO cambia (principios del contrato V4 y de la resolución de identidad)

1. Una operación = una dirección, nunca reutilizada; respuestas enlazadas por `PARENT_OPERATION_ID`.
2. Inmutabilidad: nada se edita; todo cambio es una fila nueva.
3. Maira no accede a SharePoint ni a los datos maestros de cliente. Solo envía `TELEFONO_CORRELACION`.
4. **No existe tabla ni caché teléfono→cliente** en el lado de Maira. La resolución la hace Claudia, es
   puntual (por `PARENT_OPERATION_ID`) y se resuelve de nuevo en cada mensaje.
5. Salida de Claudia hacia el cliente: `AUTORIZADO_PARA_ENTREGA`, caducidad, validación humana cuando
   proceda y `CONVERSACION_EXACTA`; si falta algo, Maira bloquea.
6. `ENTREGADO` solo acredita que el proveedor aceptó el mensaje, no que se leyó.
7. Maira no mueve estados entre `01…05`, `90`, `99`; esas transiciones son solo de Claudia.
8. Anclaje externo firmado de la cabeza de cadena, con verificación criptográfica real; nunca "firme"
   sin verificador explícito.
9. Producción y datos reales siguen sin autorizar hasta superar pruebas.

## 4. Alcance: qué guarda y qué no

**Sí** (metadatos y control): operaciones, manifiestos, archivos (nombre, tamaño, MIME, SHA-256 y
referencia de almacenamiento), eventos de estado, acuses, resoluciones de identidad, checkpoints y
registros de claves.

**No**:
- Datos maestros de clientes ni expedientes: la fuente de verdad sigue siendo Microsoft 365
  (`CLIENTE_ID` = ID real del ítem). Copiarlos crea un problema de sincronización y reabre la
  decisión ya cerrada de no tener un índice derivado en Maira.
- El **contenido** de los documentos (PDF, Word, Excel). Va a un almacén de archivos aparte; la base
  de datos guarda su referencia y su hash. Ver §7.
- Nada de `chatbot.db`: la SQLite actual de Maira (conversaciones, memoria, facturas) es otra cosa y
  no se toca ni se expone a Claudia.

## 5. Esquema propuesto (PostgreSQL; el equivalente T-SQL es directo)

```sql
-- Una fila por paquete (entrada de Maira, respuesta de Claudia, acuse, resolución de identidad).
CREATE TABLE operaciones (
  operation_id         text PRIMARY KEY,               -- MAIRA-YYYYMMDD-HHMMSS-{aleatorio}
  direccion            text NOT NULL CHECK (direccion IN ('MAIRA_A_CLAUDIA','CLAUDIA_A_MAIRA')),
  tipo                 text NOT NULL,                  -- documento | captura_estructurada | acuse_entrega | RESOLUCION_IDENTIDAD
  parent_operation_id  text REFERENCES operaciones(operation_id),
  clave_idempotente    text NOT NULL,
  version_contrato     smallint NOT NULL,
  origen               text,                           -- whatsapp | telegram | chat_web
  telefono_correlacion text,                           -- solo trazabilidad
  cliente_id           text,                           -- ID real del ítem de SharePoint
  expediente_id        text,
  estado_identidad     text CHECK (estado_identidad IN ('RESUELTA','IDENTIDAD_PENDIENTE')),
  payload              jsonb NOT NULL,                 -- campos específicos del tipo
  hash_paquete         text NOT NULL,                  -- SHA-256 del manifiesto canónico
  creado_por           text NOT NULL DEFAULT current_user,
  creado_utc           timestamptz NOT NULL DEFAULT now(),   -- hora del servidor
  UNIQUE (direccion, clave_idempotente)
);

CREATE TABLE archivos (
  operation_id  text NOT NULL REFERENCES operaciones(operation_id),
  nombre        text NOT NULL,
  tamano_bytes  bigint NOT NULL,
  mime          text NOT NULL,
  sha256        text NOT NULL,
  ubicacion     text NOT NULL,                         -- referencia al almacén de archivos
  PRIMARY KEY (operation_id, nombre)
);

-- Cadena de eventos: una fila = una transición, nunca se edita.
CREATE TABLE eventos_estado (
  operation_id         text NOT NULL REFERENCES operaciones(operation_id),
  secuencia            integer NOT NULL,
  estado_anterior      text,
  estado_nuevo         text NOT NULL,
  actor                text NOT NULL,
  comando_id           text NOT NULL,                  -- idempotencia por comando, no por estado destino
  motivo               text,
  hash_evento_anterior text,
  hash_evento          text NOT NULL,
  fecha_utc            timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (operation_id, secuencia),               -- exclusión real: dos escritores no pueden tomar la misma
  UNIQUE (operation_id, comando_id)
);

CREATE TABLE checkpoints_anclaje (    -- copia completa y verificable (FIRMA + SIGNED_PAYLOAD_HASH)
  checkpoint_id text PRIMARY KEY, operation_id text NOT NULL, secuencia integer NOT NULL,
  hash_cabeza text NOT NULL, hash_paquete text, motivo_sin_paquete text,
  key_id text NOT NULL, identidad_firmante text NOT NULL, algoritmo_firma text NOT NULL,
  version_esquema text NOT NULL, signed_payload_hash text NOT NULL, firma text NOT NULL,
  fecha_utc timestamptz NOT NULL DEFAULT now(),
  CHECK ((hash_paquete IS NULL) <> (motivo_sin_paquete IS NULL))   -- mutuamente excluyentes
);

CREATE TABLE claves (                 -- altas y revocaciones firmadas, append-only
  registro_id bigserial PRIMARY KEY, key_id text NOT NULL, tipo text NOT NULL, -- alta | cese | compromiso
  fecha_efectiva timestamptz NOT NULL, key_id_autoridad text NOT NULL,
  signed_payload_hash text NOT NULL, firma text NOT NULL
);
```

Las tablas de acuses y resoluciones de identidad son `operaciones` con `tipo` distinto: mantiene la
regla de que cada uno es una operación nueva e independiente.

## 6. Roles y permisos (la ACL real que hoy falta)

| Rol | Permisos | Efecto |
|---|---|---|
| `maira_app` | `INSERT` en `operaciones` (solo `direccion='MAIRA_A_CLAUDIA'`) y en `archivos` de sus propias operaciones; `SELECT` sobre `operaciones` filtrado por `direccion='CLAUDIA_A_MAIRA'` mediante una **vista** o *row-level security*; `SELECT` sobre `checkpoints_anclaje` (para verificar ACK); sin `UPDATE`, `DELETE`, `TRUNCATE` | Maira solo crea y solo ve lo que le toca |
| `claudia_app` | `SELECT` en todo; `INSERT` en `operaciones` (`CLAUDIA_A_MAIRA`), `eventos_estado`; sin `UPDATE`/`DELETE` | Solo Claudia mueve estados |
| `anclaje_writer` | `INSERT` en `checkpoints_anclaje` y `claves`; identidad **distinta** de Maira y Claudia | Separación de autoridades (spike 26) |
| `auditor` | `SELECT` en todo y en el registro de auditoría | Lectura independiente |
| Administrador | Fuera del alcance de Maira; sus acciones se auditan | Ver riesgo R1 |

Además: *triggers* que rechazan `UPDATE`, `DELETE` y `TRUNCATE` sobre todas estas tablas para
cualquier rol distinto del propietario, y auditoría de la base de datos activada (p. ej. `pgaudit` o
el equivalente gestionado).

## 7. Documentos (archivos)

La base de datos no debe contener el binario. Opciones, a decidir con Claudia:

- **a) Biblioteca de SharePoint de LexGuardian** para los archivos, con la base de datos guardando
  referencia y hash. Claudia sigue leyéndolos de forma nativa.
- **b) Almacenamiento de objetos** (p. ej. Azure Blob) con las mismas garantías de hash.

En ambos casos rige el orden del contrato V4: primero se suben y verifican los archivos (hash y
tamaño contra lo declarado); solo después se inserta la fila de `operaciones` con `hash_paquete`. La
inserción es la que "publica" el paquete, atómicamente.

## 8. Cómo accede Claudia (la pregunta que decide todo)

Claudia es un agente de Microsoft 365. **No está verificado** que pueda leer y escribir en una base
de datos externa. Rutas posibles, por orden de menor a mayor esfuerzo:

1. **Conector de plataforma** (Power Platform / Power Automate) hacia Azure SQL o PostgreSQL.
   Pendiente de confirmar disponibilidad y licencia del conector.
2. **API delante de la base de datos** (un servicio pequeño que solo expone operaciones
   autorizadas). Esto equivale en la práctica a la **Opción B** del Broker/ACL (escritor único), con
   un almacén relacional detrás.
3. Base de datos solo para eventos y control, y los archivos en SharePoint (§7a): Claudia lee los
   documentos como hasta ahora y el resto lo consulta por 1 o 2.

Sin respuesta a esto no se puede elegir motor: Azure SQL suele integrarse mejor con el ecosistema
Microsoft; PostgreSQL es más portable. Se decide **después** de saber por dónde entra Claudia.

## 9. Efecto sobre los 26 puntos del spike

| Puntos | Con base de datos |
|---|---|
| 1 (licencia), 2-5, 7, 8 (etiquetas de retención, bloqueo, auditoría, latencia de sellado) | **Dejan de aplicar** tal cual; se sustituyen por: permisos por rol, *triggers* y auditoría de la BD (mismas comprobaciones, otro mecanismo) |
| 6, 11 (concurrencia y bifurcación) | **Se simplifican mucho**: la restricción `UNIQUE` lo garantiza; se sigue probando con 20 escritores reales |
| 9, 10, 12 (borrado del último evento, orden, repetición legítima) | Se siguen probando; los cubre la combinación permisos + restricciones + anclaje |
| 13 (timeout de Purview) | Sustituido por "caída/timeout de la base de datos a mitad de operación" |
| 14-19 (firma inválida, revocación, checkpoint duplicado/conflictivo, notificación, ancla no disponible) | **Sin cambios**: no dependen del almacén |
| 20 (ETag) | Sustituido por aislamiento transaccional |
| 21 (persistencia antes del ACK) | Sustituido por *commit* confirmado antes del ACK |
| 22 (fuente horaria) | **Resuelto** con `now()` del servidor |
| 23-26 (verificación criptográfica real, canónico, `HASH_PAQUETE`, altas/revocaciones) | **Sin cambios**: son independientes del almacén; siguen dependiendo de la PKI |

## 10. Riesgos y límites (a asumir con los ojos abiertos)

- **R1. El administrador de la base de datos es un punto de confianza.** Puede reescribir tablas
  como hoy podría borrar archivos. El anclaje externo firmado con copia bajo control de Claudia sigue
  siendo imprescindible; la base de datos no lo sustituye.
- **R2. Alojamiento y RGPD.** Debe estar en la UE, bajo LexGuardian, con contrato de encargado de
  tratamiento, copias de seguridad cifradas y política de retención. Maira corre hoy en Hetzner:
  la base de datos **no debe** colgar de ahí.
- **R3. Disponibilidad.** Una base de datos caída bloquea el canal; hay que definir qué hace Maira
  entonces (cola local que no publica nada dudoso, igual que la recuperación tras caída del V4).
- **R4. Coste y operación.** Pasa a existir un servicio que alguien monitoriza, actualiza y
  respalda.
- **R5. Migración.** `puente_claudia.py` (diseño previo, teléfono como clave) no se reutiliza; se
  migra al formato V4/V5 sobre datos sintéticos.

## 11. Comparación de opciones

| | Opción A (SharePoint + etiquetas de retención) | Opción B (broker de escritor único) | **BD relacional** |
|---|---|---|---|
| Atomicidad y concurrencia | A probar contra SharePoint | La da el broker | La da el motor |
| Inmutabilidad real | Etiquetas *record* | Broker | Permisos + *triggers* |
| Claudia lo lee de forma nativa | Sí | No (API) | Depende del conector (§8) |
| Depende de licencia Purview | Sí | No | No |
| Servicio nuevo a operar | No | Sí | Sí |
| Complejidad del spike | Alta (26 puntos en SharePoint real) | Media | Media-baja |
| Anclaje externo firmado | Necesario | Necesario | Necesario |

## 12. Plan propuesto

1. **Fase 0 -- respuestas**: Claudia y LexGuardian contestan a las preguntas del §13. Sin código.
2. **Fase 1 -- prototipo sintético local**: base de datos local desechable, esquema del §5 y los roles
   del §6; reproducir los tests de `scratch/test_contrato_maira_claudia.py` (incluida la prueba de 20
   escritores) contra ella. Sin tenant, sin datos reales.
3. **Fase 2 -- entorno de pruebas de LexGuardian**: la misma base de datos gestionada, con el camino
   real de acceso de Claudia. Evidencia en el formato del spike (hora UTC, identidad,
   petición/respuesta, auditoría, veredicto).
4. **Fase 3 -- decisión**: V5 del contrato si todo pasa. Producción y datos reales, solo con
   autorización expresa posterior.

## 13. Preguntas abiertas

1. ¿Puede Claudia leer y escribir en una base de datos o API, y con qué conector y licencia?
2. ¿Quién aloja y administra la base de datos? ¿Región y contrato de tratamiento de datos?
3. ¿Los archivos van a SharePoint (§7a) o a almacenamiento de objetos (§7b)?
4. ¿Se acepta una V5 que sustituya solo el transporte del V4, manteniendo todos sus principios?
5. ¿Esta propuesta convive con el spike de la Opción A (en paralelo) o lo sustituye?

## 14. Qué depende de quién

| Pendiente | De quién |
|---|---|
| Diseño del esquema, roles y prototipo sintético (Fase 1) | Nuestra parte |
| Decidir el camino de acceso de Claudia (§8) | Claudia / LexGuardian |
| Alojar y administrar la base de datos, contrato de tratamiento | LexGuardian |
| Esquema real de claves/PKI y autoridad raíz | LexGuardian (gobierno) |
| Aprobar V5 | Claudia |
