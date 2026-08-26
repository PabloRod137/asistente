# CONTRATO_MAIRA_CLAUDIA_V4 — APROBADO

## Estado final
CONTRATO V4 APROBADO / IMPLEMENTACIÓN NO AUTORIZADA / DATOS REALES NO AUTORIZADOS.

Aprobado por Claudia (agente de gobierno de LexGuardian) el 2026-08-26, tras 4 rondas de revisión (V1-V4). Este documento es la referencia vigente para una futura implementación de la carpeta puente entre Maira y Claudia. **No implementar contra producción ni con datos reales hasta que se autorice expresamente** (ver Addendum, punto 5).

## 1. Canal (nombres canónicos exactos)

```text
PUENTE_AGENTES
└── 03_MAIRA
    ├── 00_ORDENES_NUEVAS
    ├── 01_ORDENES_ACEPTADAS
    ├── 02_EN_EJECUCION
    ├── 03_BLOQUEADAS
    ├── 04_ENTREGADAS
    ├── 05_VALIDADAS
    ├── 90_CANCELADAS
    └── 99_ARCHIVO
```

## 2. Una operación = una dirección, nunca reutilizada

- Cada entrega Maira→Claudia y cada entrega Claudia→Maira tiene su propio `OPERATION_ID`, nunca compartido.
- Cada manifiesto lleva `DIRECCION: MAIRA_A_CLAUDIA | CLAUDIA_A_MAIRA`.
- Una respuesta se enlaza a su origen mediante `PARENT_OPERATION_ID`, nunca modificando el paquete original.

## 3. Inmutabilidad real

- El manifiesto de Maira, una vez `READY`, no lo modifica nadie — ni Maira ni Claudia.
- Una respuesta de Claudia es siempre un paquete nuevo, propio `OPERATION_ID`, `DIRECCION: CLAUDIA_A_MAIRA`, enlazado por `PARENT_OPERATION_ID`.

## 4. Manifiesto de entrada (`manifiesto.md`) + hash externo

```text
OPERATION_ID: MAIRA-YYYYMMDD-HHMMSS-{aleatorio}
DIRECCION: MAIRA_A_CLAUDIA
PARENT_OPERATION_ID: {vacío si es entrada nueva}
CLAVE_IDEMPOTENTE: {valor único que evite procesar dos veces el mismo evento}
VERSION_CONTRATO: 4
FECHA_HORA: yyyy-MM-dd HH:mm:ss
ORIGEN: whatsapp | telegram | chat_web
TELEFONO_CORRELACION: {solo trazabilidad/correlación}
CLIENTE_ID: {ID real del ítem de SharePoint, nunca Correlativo}
EXPEDIENTE_ID: {ID real del ítem, si aplica}
NUMERO_VISIBLE_CLIENTE / NUMERO_VISIBLE_EXPEDIENTE: {código legible, solo referencia humana}
ESTADO_IDENTIDAD: RESUELTA | IDENTIDAD_PENDIENTE
TIPO: documento | captura_estructurada
ARCHIVOS: [nombre + tamaño + MIME + SHA-256 de cada uno]
ESTADO: READY
```

El hash del manifiesto no va dentro de sí mismo (autorreferencia). Va en `manifiesto.sha256` aparte, calculado sobre `manifiesto.md` ya finalizado.

## 5. Subida y cierre atómico

- Cada archivo se sube con sufijo `.partial` mientras se transfiere.
- Al completarse, se renombra de forma atómica quitando `.partial`.
- Solo cuando todos los archivos están renombrados se escribe `manifiesto.md`, luego `manifiesto.sha256`, y el paquete pasa a `READY`.

## 6. Resolución de identidad

- Maira no consulta SharePoint directamente. Solo envía `TELEFONO_CORRELACION`.
- La resolución a `CLIENTE_ID`/`EXPEDIENTE_ID` la hace Claudia/M365, o un índice derivado mínimo de solo lectura, autorizado aparte (no el acceso general de Graph que ya tiene Maira).
- Hasta esa resolución: `ESTADO_IDENTIDAD: IDENTIDAD_PENDIENTE`.

## 7. Camino de vuelta

Claudia deposita la salida como paquete nuevo en `00_ORDENES_NUEVAS`:

```text
OPERATION_ID: MAIRA-YYYYMMDD-HHMMSS-{aleatorio}
DIRECCION: CLAUDIA_A_MAIRA
PARENT_OPERATION_ID: {OPERATION_ID del paquete original de Maira}
AUTORIZADO_PARA_ENTREGA: SI
VALIDACION_HUMANA_REQUERIDA: SI | NO
VALIDACION_HUMANA_ID: {referencia de la validación humana, si aplica}
AUTORIZADO_POR: {persona}
AUTORIZADO_EN: {fecha/hora}
CANAL_ENTREGA: whatsapp | telegram | chat_web
CONVERSACION_EXACTA: {chat_id exacto, el teléfono solo nunca basta}
CADUCIDAD_ENTREGA: {fecha/hora límite}
ARCHIVOS: [...]
ESTADO: READY
```

- Maira lee `00_ORDENES_NUEVAS` filtrando `DIRECCION: CLAUDIA_A_MAIRA`.
- Antes de entregar: `AUTORIZADO_PARA_ENTREGA: SI`, no caducado, hash verifica, y si `VALIDACION_HUMANA_REQUERIDA: SI` deben estar `VALIDACION_HUMANA_ID`, `AUTORIZADO_POR` y `AUTORIZADO_EN` — si falta cualquiera, Maira bloquea la entrega.
- Resultado de cada intento: `ENTREGADO | FALLIDO_REINTENTABLE | FALLIDO_DEFINITIVO`, con contador `INTENTOS`. Un reintento nunca reenvía si un intento anterior ya tuvo `ENTREGADO`.

El acuse es una operación nueva, independiente, nunca escrita dentro del paquete de salida:

```text
OPERATION_ID: MAIRA-YYYYMMDD-HHMMSS-{aleatorio}
DIRECCION: MAIRA_A_CLAUDIA
TIPO: acuse_entrega
PARENT_OPERATION_ID: {OPERATION_ID de la salida}
RESULTADO_ENTREGA: ENTREGADO | FALLIDO_REINTENTABLE | FALLIDO_DEFINITIVO
INTENTOS: {número}
FECHA_ENTREGA: {fecha/hora}
ID_PROVEEDOR: {id del mensaje devuelto por WhatsApp/Telegram}
ESTADO_PROVEEDOR: {lo que el canal confirme realmente — aceptación de envío, no lectura, salvo que el canal lo confirme}
ESTADO: READY
```

El hash del acuse también es externo (`acuse.sha256`) o excluye explícitamente el propio campo hash — no autorreferencia.

## 8. ACL

- Maira lee `00_ORDENES_NUEVAS` completa, filtrando por `DIRECCION` lo que le corresponde.
- Maira solo crea paquetes nuevos (entradas y acuses) — nunca edita un paquete existente, propio o ajeno.
- Limitación reconocida: una carpeta de OneDrive compartida no impone esta inmutabilidad a nivel de almacenamiento por sí sola. Para esta fase, la garantía es solo a nivel de aplicación (el código de Maira nunca emite una operación de modificación, solo creación). Insuficiente para producción — ver Addendum punto 5.
- Maira no mueve nada entre `01…05`, `90` o `99` — transiciones exclusivas de Claudia.
- Antivirus, límites de tamaño/tipo, retención y cuarentena sobre todo archivo recibido.

## Addendum vinculante (aprobación V4)

1. Solo un acuse con `RESULTADO_ENTREGA: ENTREGADO` permite mover la salida a `05_VALIDADAS`.
2. `FALLIDO_REINTENTABLE` permanece en `02_EN_EJECUCION` o `03_BLOQUEADAS` hasta reintento; `FALLIDO_DEFINITIVO` pasa a `03_BLOQUEADAS`. `90_CANCELADAS` requiere siempre una decisión humana expresa, nunca automática.
3. El hash del acuse sigue la misma regla que el del manifiesto: externo o excluyendo explícitamente el campo — no autorreferencia.
4. `ID_PROVEEDOR` acredita únicamente que la plataforma (WhatsApp/Telegram) aceptó el mensaje, no que el cliente lo leyó. `ESTADO_PROVEEDOR` debe reflejar solo lo que el canal confirme realmente — nunca afirmar "entregado" o "leído" si el canal no lo garantiza.
5. La inmutabilidad a nivel de aplicación (sin broker ni ACL por ítem) es válida únicamente para pruebas sintéticas. Bloquea producción y datos reales hasta disponer de un broker/ACL efectivo y superar pruebas de manipulación, duplicados y reintentos.

## Límites que se mantienen en toda versión

- Maira no escribe en SharePoint real bajo ninguna circunstancia.
- Sin datos reales de cliente hasta autorización expresa adicional a esta aprobación de contrato.
