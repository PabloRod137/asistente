# SPIKE_SHAREPOINT_MAIRA_CLAUDIA_V1 -- PAQUETE DE INSTRUCCIONES

## Estado
Borrador V1 (21/09/2026), **pendiente de validación por Claudia y de autorización expresa del
administrador del tenant de LexGuardian**. Es el runbook para ejecutar el spike real que exigen
tres documentos ya aprobados como base del spike:

- `CONTRATO_MAIRA_CLAUDIA_V4_APROBADO.md` (Addendum, punto 5)
- `BROKER_ACL_V4_APROBADA_PARA_SPIKE.md` (puntos 1-13)
- `ANCLAJE_EXTERNO_V3_APROBADA_PARA_SPIKE.md` (puntos 14-26)

Este documento no cambia ningún diseño aprobado: ordena las 26 comprobaciones, dice qué hace falta
para ejecutarlas, cómo se registra la evidencia y cómo se decide entre Opción A (etiquetas de
retención / registros en SharePoint + Purview) y Opción B (broker de escritor único).

## 1. Reglas de ejecución (no negociables)

1. **Solo sitio/biblioteca de prueba corporativa de LexGuardian.** Nunca `PUENTE_AGENTES` del
   OneDrive personal de Alberto, nunca una biblioteca con contenido de clientes.
2. **Solo archivos sintéticos.** Sin datos reales de cliente, sin NIF, teléfonos ni nombres reales.
   Los identificadores de prueba llevan el prefijo `SPIKE-` (p. ej. `OPERATION_ID: MAIRA-SPIKE-...`).
3. **Autorización previa y escrita del administrador del tenant**, con fecha y ventana de
   ejecución. Sin ella no se empieza.
4. **Identidades técnicas dedicadas al spike**, con autenticación por certificado (no secreto de
   cliente) y mínimo privilegio. Nunca credenciales personales ni las de la app actual de Maira en
   Graph (`MS_CLIENT_ID`/`MS_CLIENT_SECRET`).
5. **Maira no escribe en SharePoint real** fuera del sitio de prueba. Este spike no lo cambia.
6. **Nada de lo que pase o falle en el spike autoriza producción ni datos reales.** Eso requiere
   una decisión posterior y expresa de LexGuardian/Claudia.
7. **Cada comprobación produce evidencia** (sección 5). Sin evidencia, el punto cuenta como `FAIL`.
8. **Cierre y limpieza** al terminar (sección 8): el sitio de prueba no puede quedar con
   identidades ni credenciales activas.

## 2. Qué se necesita de LexGuardian (lista de comprobación previa)

| # | Necesidad | Responsable | Hecho |
|---|---|---|---|
| P1 | Autorización escrita del administrador del tenant + ventana de ejecución | Admin tenant | [ ] |
| P2 | Sitio SharePoint de prueba corporativo + una biblioteca dedicada | Admin tenant | [ ] |
| P3 | Confirmación de licencia: el plan M365 incluye etiquetas de retención / gestión de registros (punto 1) | Admin tenant | [ ] |
| P4 | Acceso a Purview (centro de cumplimiento) para quien ejecute el spike: crear etiquetas, ver auditoría | Admin cumplimiento | [ ] |
| P5 | Registro de app en Entra ID para el spike, con **certificado**, permisos mínimos sobre esa biblioteca | Admin tenant | [ ] |
| P6 | Tres identidades de prueba separadas (ver sección 3) | Admin tenant | [ ] |
| P7 | Una **segunda cuenta de Purview/rol distinto** para probar el desbloqueo (punto 4) | Admin cumplimiento | [ ] |
| P8 | Decisión sobre quién actúa como firmante de checkpoints en el spike y cómo se custodia su clave (puntos 23 y 26) | Claudia / gobierno | [ ] |
| P9 | Canal acordado para entregar la evidencia y persona que recibe el informe | Claudia | [ ] |

Los identificadores del sitio (`MS_SITE_ID`, `MS_DRIVE_ID` del sitio de prueba) se pasan al equipo
de Maira por un canal seguro, no por chat ni por correo en claro.

## 3. Entorno de prueba

### Estructura de la biblioteca (nombres canónicos del contrato V4)

```text
PUENTE_AGENTES
└── 03_MAIRA
    ├── 00_ORDENES_NUEVAS   01_ORDENES_ACEPTADAS   02_EN_EJECUCION   03_BLOQUEADAS
    ├── 04_ENTREGADAS       05_VALIDADAS           90_CANCELADAS      99_ARCHIVO
ESTADOS/{OPERATION_ID}/     ← eventos de estado y anclajes (un archivo por evento, inmutable)
```

### Identidades (todas técnicas, con certificado)

| Identidad | Permisos esperados | Qué comprueba |
|---|---|---|
| `spike-maira` | Lectura de `00_ORDENES_NUEVAS`; **solo crear** paquetes nuevos (entradas y acuses); no editar ni borrar; no mover entre carpetas | Que la ACL real impone lo que hoy solo impone el código (contrato §8) |
| `spike-claudia` | Lectura completa, transiciones entre `01…05/90/99`, alta de checkpoints firmados | Punto 3 (bloqueo), punto 6 (concurrencia) |
| `spike-admin-cumplimiento` | Etiquetado, desbloqueo, consulta de auditoría | Puntos 2, 4, 5 |

Si una identidad necesita más permisos de los previstos para completar un punto, **se anota como
hallazgo** en la evidencia; no se ensancha el permiso en silencio.

### Configuración en el código de Maira (solo en un entorno de pruebas, nunca en el `.env` de producción)

```text
STORAGE_TIPO=sharepoint
MS_TENANT_ID=…        (tenant de LexGuardian)
MS_CLIENT_ID=…        (app del spike, NO la de Maira)
MS_SITE_ID=…          (sitio de prueba)
MS_DRIVE_ID=…         (biblioteca de prueba)
```

> Aviso: `puente_claudia.py` **se niega a ejecutar** con `STORAGE_TIPO=sharepoint` (salvaguarda
> `b8c2630`). Es intencionado: ese módulo es el diseño anterior al contrato V4. El spike se ejecuta
> con `contrato_maira_claudia.py` y sus funciones, no con `puente_claudia.py`.

### Estado del código que se aporta

`contrato_maira_claudia.py` es hoy un prototipo **local**: escribe en el sistema de archivos. Para
repetir las pruebas contra SharePoint hay que **sustituir su capa de almacenamiento** por una que
opere sobre Graph con las mismas garantías (creación exclusiva, renombrado atómico, lectura fresca).
Ese adaptador aún no existe (ver sección 9, tarea T1). Hasta que exista, los puntos que dependen de
"repetir la prueba contra el backend real" (6, 9-13, 17, 20, 21) se pueden ejecutar de forma
**manual/exploratoria** contra Graph para responder la pregunta de fondo (¿ofrece la primitiva?), y
se repiten con el prototipo adaptado cuando esté.

## 4. Las 26 comprobaciones, en orden de ejecución

Veredicto por punto: `PASS` / `FAIL`. Formato de evidencia en la sección 5.
Los puntos marcados **[ELIM]** son eliminatorios para la Opción A (ver sección 6).

### Bloque 1 -- Capacidades de la plataforma (¿existe la primitiva?)

| # | Comprobación | Criterio de PASS |
|---|---|---|
| 1 | **Licencia**: el plan incluye etiquetas de retención / gestión de registros | Confirmado por el admin con captura o consulta de licencias |
| 2 | **Etiquetado por API** al cerrar un paquete, no solo manual desde Purview | Un paquete recibe la etiqueta con una llamada programática autenticada con la identidad técnica. Anotar qué endpoint exacto de Graph se usa (a confirmar aquí; no se da por supuesto) **[ELIM]** |
| 3 | **Bloqueo real de edición y borrado**: archivo sintético etiquetado como *record* | Editar y borrar **fallan** para `spike-maira` y para `spike-claudia` **[ELIM]** |
| 4 | **Desbloqueo**: qué rol exacto puede desbloquear un *record* y si queda auditado | Rol identificado; el desbloqueo aparece en auditoría |
| 5 | **Auditoría**: etiquetado, intentos bloqueados y desbloqueo quedan registrados y son consultables | Los tres tipos de evento localizables en el registro de auditoría, correlacionados con la identidad y la hora |
| 8 | **Protección de eventos, no solo de paquetes**: los archivos de `ESTADOS/` (evento + `.sha256`) se pueden etiquetar igual | Mismo resultado que los puntos 2 y 3 sobre un evento |

### Bloque 2 -- Concurrencia, orden y latencia (¿se comporta como el prototipo?)

| # | Comprobación | Criterio de PASS |
|---|---|---|
| 6 | **Concurrencia real**: **20 escritores concurrentes** reclamando secuencia para la misma operación contra el backend real (Addendum Broker V4, punto 1). `O_CREAT|O_EXCL` solo prueba exclusión local | Cero colisiones, cero huecos, cero pérdidas; documentar qué ocurre con los perdedores (error, cola, rechazo) **[ELIM]** |
| 7 | **Latencia**: tiempo entre la petición de etiquetado y la protección efectiva | Se mide la ventana (mín/med/máx en al menos 20 muestras) y se comprueba si el archivo es editable durante ella **[ELIM si no hay forma de detectar el fin de la ventana]** |
| 9 | **Eliminación del último evento** de una cadena | Es detectable, o se documenta la mitigación adicional necesaria |
| 10 | **Eventos fuera de orden**: escribir uno con secuencia anterior tras uno posterior | Se detecta (`diagnosticar_cadena_eventos`) |
| 11 | **Dos ramas concurrentes**: intento deliberado de bifurcación contra el mecanismo real | Se impide o se detecta; nunca pasa desapercibido |
| 12 | **Repetición legítima de un estado** (`EJECUCIÓN→BLOQUEADA→EJECUCIÓN→BLOQUEADA`) | El mecanismo real no lo confunde con un duplicado |
| 13 | **Indisponibilidad/timeout de Purview** durante el sellado | Ante fallo, el paquete no se publica ni se proyecta estado dudoso |

### Bloque 3 -- Anclaje externo y firmas (checkpoints, ACK, claves)

| # | Comprobación | Criterio de PASS |
|---|---|---|
| 14 | **Firma inválida**: payload que no coincide con `SIGNED_PAYLOAD_HASH`, o `FIRMA` que no verifica | `firme=False` con motivo explícito |
| 15 | **Clave revocada o rotada** durante una operación en curso | Checkpoints posteriores al corte dejan de ser firmes; los anteriores a un `cese` se mantienen |
| 16 | **Checkpoint duplicado** (mismo `CHECKPOINT_ID`) y **conflictivo** (misma secuencia, huella distinta) | Duplicado idempotente; conflictivo bloquea la proyección con `CheckpointConflictivo` |
| 17 | **La cadena cambia realmente durante la firma** (concurrencia real, no simulada) | El checkpoint no se publica sobre una cabeza obsoleta |
| 18 | **Notificación perdida o repetida** | Ninguno de los dos casos rompe nada |
| 19 | **Indisponibilidad del ancla externa** (Maira no puede leer el ACK a tiempo) | Maira no da nada por firme; queda en estado no confirmado con motivo |
| 20 | **ETag/versionado** (o primitiva equivalente) para una instantánea estable | Confirmado y utilizable; releer dos veces no se acepta como prueba |
| 21 | **Persistencia confirmada antes del ACK**, contra el backend real | Relectura tras escribir verifica estructuralmente antes de publicar el ACK |
| 22 | **Fuente de timestamp** que usa realmente el backend | Se documenta si la hora la fija el servidor o la declara el firmante; si es esto último, se propone alternativa |
| 23 | **Verificación estructural no autentica**: verificador criptográfico real | Con un verificador real, `obtener_estado_confirmado` devuelve `firme=True`; sin él, nunca. Requiere decisión P8 |
| 24 | **Interoperabilidad de la especificación canónica** | Los dos vectores del anexo A se reproducen **byte a byte** en la implementación de Claudia |
| 25 | **`HASH_PAQUETE` liga los archivos reales** (modificación, adición, eliminación y renombrado) | Los cuatro casos lanzan `PaqueteManipulado`; el caso sano pasa |
| 26 | **Alta/revocación de claves como autoridad crítica**, fallo cerrado | Alta manipulada nunca vigente; revocación manipulada tratada como "ya revocada". Pendiente de gobierno: quién firma la primera autoridad raíz |

### Orden recomendado

1. Bloque 1 completo (decide si merece la pena seguir con la Opción A).
2. Puntos 6 y 7 (los otros dos eliminatorios).
3. Resto del Bloque 2.
4. Bloque 3.

Si un punto **[ELIM]** da `FAIL`, se detiene el resto del Bloque 1-2 y se pasa directamente a
evaluar la Opción B (sección 6). El Bloque 3 es independiente de A/B y puede continuar.

## 5. Formato de evidencia (obligatorio, un bloque por punto)

```text
PUNTO: {n} -- {nombre}
HORA_UTC: {yyyy-MM-ddTHH:mm:ssZ}
IDENTIDAD_USADA: {spike-maira | spike-claudia | spike-admin-cumplimiento}
PETICION: {método + ruta + cuerpo relevante, sin secretos ni tokens}
RESPUESTA: {código HTTP + cuerpo relevante, o error exacto}
AUDITORIA: {referencia al evento del registro de auditoría, o "no localizado"}
VEREDICTO: PASS | FAIL
NOTAS: {hallazgos, permisos extra necesarios, latencias medidas}
```

Reglas de la evidencia: sin tokens, sin certificados, sin secretos; solo identificadores sintéticos
`SPIKE-`; las capturas de Purview se acompañan de la hora UTC; los `FAIL` **no se repiten hasta que
aprueben** -- se registran tal cual y se documenta el reintento como un punto nuevo.

## 6. Criterio de decisión: Opción A o Opción B

Según el Addendum 6 del Broker V4, **la Opción A queda descartada y se adopta la Opción B sin más
rediseño** si SharePoint no ofrece alguna de estas tres cosas:

1. **Primitivas atómicas reales** (punto 6: 20 escritores concurrentes sin colisión ni hueco).
2. **Aislamiento durante la ventana de latencia** (punto 7 y 3: no hay forma de editar entre
   `READY` y la protección efectiva, o al menos el fin de la ventana es detectable).
3. **Confirmación fiable** del sellado (punto 2 y 5: evidencia verificable del proveedor -- etiqueta
   aplicada, bloqueo efectivo, auditoría correlacionada; nunca un temporizador ni el mero éxito de
   la petición).

Propuesta de este documento (**pendiente de validar por Claudia**): además de esos tres, tratar como
eliminatorios para A los puntos 2, 3, 6 y 7 tal como se marcan en la sección 4.

Si A pasa, el informe pide igualmente la autorización expresa de LexGuardian para el siguiente
paso; **pasar el spike no equivale a autorizar producción**.

Si A falla, Opción B: servicio broker de escritor único, alojado y operado por LexGuardian, con
Maira y Claudia llamando solo a su API con mínimo privilegio, idempotencia y auditoría (diseño en
`PROPUESTA_BROKER_ACL_V3.md` §4). El spike sigue sirviendo para el Bloque 3.

## 7. Informe final del spike (entregable)

Un único documento con:

1. Cabecera: fecha, ventana, tenant/sitio de prueba, identidades usadas, versión del código
   (commit) y del contrato/anclaje probados.
2. Tabla de los 26 puntos con veredicto y enlace a su bloque de evidencia.
3. Decisión propuesta: A o B, con los criterios de la sección 6 evaluados uno a uno.
4. Hallazgos no previstos: permisos extra, latencias, límites de la API, cambios necesarios en el
   contrato.
5. Lista de decisiones que quedan para LexGuardian/Claudia (PKI, autoridad raíz, custodia de claves).
6. Confirmación de limpieza (sección 8).

Se entrega a Claudia por el canal fijado en P9. **No se modifica ningún documento aprobado**: si el
spike exige un cambio de diseño, se propone como una versión nueva para su revisión.

## 8. Cierre y limpieza

- [ ] Revocar los certificados y las identidades `spike-*`.
- [ ] Eliminar o archivar la biblioteca de prueba según decida el admin (los *records* bloqueados
      pueden requerir el desbloqueo del punto 4 antes de poder borrarse).
- [ ] Retirar del entorno de pruebas `STORAGE_TIPO=sharepoint` y las variables `MS_*` del spike.
- [ ] Confirmar por escrito que el `.env` de producción de Maira no se ha tocado.
- [ ] Guardar la evidencia en un lugar bajo control de Claudia/LexGuardian, con retención.

## 9. Trabajo previo por nuestra parte (antes de poder ejecutar el spike completo)

| # | Tarea | Estado |
|---|---|---|
| T1 | Adaptador de almacenamiento de `contrato_maira_claudia.py` sobre Graph, con las mismas garantías (creación exclusiva, renombrado atómico, lectura fresca), aislado detrás de una interfaz y desactivado por defecto | Pendiente |
| T2 | Script de arnés para el punto 6 (20 escritores concurrentes contra Graph) y para medir latencia (punto 7), que escriba la evidencia en el formato de la sección 5 | Pendiente |
| T3 | Confirmar que las pruebas locales siguen en verde justo antes del spike (comandos abajo) | Verde a 21/09/2026 |
| T4 | Decidir con Claudia qué implementación de firma se usa en el spike para el punto 23 | Bloqueado por P8 |

Pruebas locales de referencia (deben pasar antes de empezar):

```bash
python scratch/test_contrato_maira_claudia.py
python scratch/test_puente_claudia.py
```

## 10. Preguntas abiertas para Claudia

1. ¿Confirma la lista de puntos eliminatorios de la sección 4 y 6, o quiere otra?
2. ¿Quién y con qué esquema firma los checkpoints durante el spike (P8)?
3. ¿Quién ejecuta el spike: LexGuardian solo, nosotros con acceso delegado a Purview, o ambos?
4. ¿Canal y formato de entrega de la evidencia (P9)?
5. ¿El sitio de prueba está en el mismo tenant que el futuro entorno productivo?

## Anexo A -- Vectores de prueba canónicos (punto 24)

Codificación: `json.dumps(array_de_valores, ensure_ascii=True, separators=(",", ":"))`, UTF-8.
Campos, en este orden: `CHECKPOINT_ID, OPERATION_ID, SECUENCIA, HASH_CABEZA, HASH_PAQUETE,
MOTIVO_SIN_PAQUETE, FECHA_UTC, KEY_ID, IDENTIDAD_FIRMANTE, ALGORITMO_FIRMA, VERSION_ESQUEMA`.
Todos son cadena JSON o `null`; `null` solo en `HASH_PAQUETE` o `MOTIVO_SIN_PAQUETE`, nunca ambos.

```text
Vector 1 (con paquete):
["cp-vector-0001","MAIRA-VECTOR-0001","0",
 "a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f9",
 "f9e8d7c6b5a4030201f9e8d7c6b5a4030201f9e8d7c6b5a4030201f9e8d7c6b5",null,
 "2026-08-31T10:00:00Z","key-2026-01","claudia@berdejoasesores.com","Ed25519","3"]
SHA-256: ba45933ad655ba2bc66c084da22408f771316a71ad6a968f1010e27c3df8c075

Vector 2 (sin paquete, MOTIVO_SIN_PAQUETE):
["cp-vector-0002","MAIRA-VECTOR-0001","0",
 "a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f9",null,
 "no_existe_paquete_para_esta_operacion","2026-08-31T10:00:00Z","key-2026-01",
 "claudia@berdejoasesores.com","Ed25519","3"]
SHA-256: d9407a3dd94be53ed17b5c67218982af7038ef51504ccfbad1c7d899235be030
```

(Los arrays se muestran en varias líneas por legibilidad; el payload real va en **una sola línea,
sin espacios ni saltos**.)

## Anexo B -- Trazabilidad de los 26 puntos

| Puntos | Origen |
|---|---|
| 1-8 | `PROPUESTA_BROKER_ACL_V3.md` §2 |
| 9-13 | `BROKER_ACL_V4_APROBADA_PARA_SPIKE.md` §4 |
| 14-19 | `PROPUESTA_ANCLAJE_EXTERNO_V2.md` §6 |
| 20-22 | `ANCLAJE_EXTERNO_V3_APROBADA_PARA_SPIKE.md` (ampliación del spike) |
| 23-26 | `ANCLAJE_EXTERNO_V3_APROBADA_PARA_SPIKE.md` (addendum de aprobación) |
