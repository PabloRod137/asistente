# ANCLAJE_EXTERNO_MAIRA_CLAUDIA_V3 -- APROBADA COMO BASE DEL SPIKE

## Estado
**APROBADA como base del spike** (31/08/2026), con 4 condiciones de cierre a resolver dentro del
propio spike (puntos 23-26 más abajo) y un quinto punto de invariantes ya incorporado al código.
Producción y datos reales siguen sin autorizar hasta superar el spike real.

Cuerpo original de la V3 (incorpora los 6 puntos del veredicto de Claudia sobre la V2, "mejora
sustancialmente, pero requiere V3 antes del spike real") conservado íntegro más abajo; el
addendum de aprobación va primero.

## Addendum de aprobación (31/08/2026) -- puntos 23-26 del spike + invariantes

**23. Verificación estructural no autentica.** Cualquiera podría recalcular el hash canónico
sobre datos falsos -- eso demuestra consistencia interna, no procedencia. *Ya implementado*:
`obtener_estado_confirmado(operation_id, verificador_firma_real=None)` exige explícitamente un
verificador criptográfico real; con el valor por defecto (`None`), la función **nunca** devuelve
`firme=True`, sin importar que la verificación estructural, la coincidencia de cabeza y la
vigencia de la clave encajen todas. Probado (TEST 25): mismo checkpoint, mismo ACK -- sin
verificador, no firme; con un verificador (aunque sea el simétrico de prueba, no PKI real), sí.
La verificación criptográfica real contra un esquema de claves de verdad sigue pendiente del
spike -- lo que ya está resuelto es que el sistema no puede fingir tenerla por descuido.

**24. Especificación canónica exacta + vectores de prueba.** *Ya implementado*: cada campo del
payload firmado es siempre una cadena JSON o `null` (nunca número, booleano ni objeto anidado);
`null` exclusivamente en `HASH_PAQUETE` o `MOTIVO_SIN_PAQUETE` (mutuamente excluyentes). Vectores
de prueba calculados contra este código y fijados como aserciones (TEST 36), reproducibles en
cualquier lenguaje sin necesitar este repositorio:

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

Orden de campos (`CAMPOS_FIRMADOS_ANCLAJE_V3`): `CHECKPOINT_ID, OPERATION_ID, SECUENCIA,
HASH_CABEZA, HASH_PAQUETE, MOTIVO_SIN_PAQUETE, FECHA_UTC, KEY_ID, IDENTIDAD_FIRMANTE,
ALGORITMO_FIRMA, VERSION_ESQUEMA`. Codificación: `json.dumps(array_de_valores, ensure_ascii=True,
separators=(",", ":"))`, UTF-8. Esto no sustituye una especificación formal como RFC 8785, pero
sí fija tipos, orden y vectores verificables -- si vuestra implementación usa otro lenguaje,
reproducir estos dos vectores byte a byte es la prueba de interoperabilidad.

**25. HASH_PAQUETE debe ligar los archivos reales, no solo el texto del manifiesto.** *Ya
implementado*: `_verificar_archivos_paquete` recalcula el hash y tamaño de cada archivo listado
en `ARCHIVOS` contra el archivo real en disco, y compara el conjunto de nombres reales contra el
conjunto declarado. Si algo no coincide -- modificación, adición, eliminación o renombrado --
`_hash_manifiesto_sellado` lanza `PaqueteManipulado` en vez de devolver un hash o confundirlo con
"no hay paquete" (son dos fallos distintos, nunca se solapan). Probado explícitamente los cuatro
casos (TEST 34) más el caso sano.

**26. Alta/revocación de claves son también autoridad crítica.** *Ya implementado*:
`registrar_clave_vigente` y `revocar_clave` ahora firman su propio registro
(`SIGNED_PAYLOAD_HASH`/`FIRMA`, mismo patrón que un checkpoint) con una `KEY_ID_AUTORIDAD`
explícita, en almacenes append-only (`O_CREAT|O_EXCL`) que -- en el sistema real -- viven fuera
del control de Maira. Un registro que no verifica estructuralmente se trata como **fallo
cerrado**: un alta manipulada nunca es vigente, una revocación manipulada se trata como "ya
revocada" en vez de ignorarse (TEST 35, ambos casos probados demostrando la inversión del
resultado). **No resuelto aquí, pendiente del spike/gobierno**: el bootstrapping de la autoridad
raíz (quién firma la primera `KEY_ID_AUTORIDAD`) es una decisión de PKI real, no algo que un
prototipo local pueda inventar de forma segura. Sobre la separación de credenciales: la clave de
firma del anclaje ya está estructuralmente separada de cualquier credencial de Graph -- este
módulo nunca importa `graph_auth` (verificado por AST en TEST 0), así que no hay forma de que
ambas cosas se mezclen por accidente.

**Invariantes generales (antes implícitas, ahora explícitas y probadas):**
- `HASH_PAQUETE` y `MOTIVO_SIN_PAQUETE` son mutuamente excluyentes (`_registro_bien_formado`,
  cubierto en TEST 29).
- Un ACK solo se publica después de confirmar que el checkpoint quedó persistido y verifica
  estructuralmente (`_simular_claudia_crear_checkpoint`, TEST 21/22 y el flujo completo).
- Cualquier fallo -- de firma (punto 23), de confianza (punto 26), de reloj (comparaciones de
  fecha explícitas, nunca silenciosas) o de almacén (`PaqueteManipulado`, `CheckpointConflictivo`)
  -- se traduce en `firme=False` con motivo explícito o en una excepción que se propaga. Ningún
  camino del código devuelve un resultado "aparentemente válido" sobre datos que no lo son.

## Qué depende de quién (actualizada)

| Pendiente | De quién |
|---|---|
| Gate de verificación criptográfica real (nunca firme sin verificador explícito) | Ya implementado y probado |
| Especificación exacta + vectores de prueba interoperables | Ya implementado y probado |
| Verificación de archivos reales del paquete (no solo el manifiesto) | Ya implementado y probado |
| Alta/revocación de claves firmadas, fallo cerrado | Ya implementado y probado |
| Esquema real de claves/PKI (verificador_firma_real de verdad) | LexGuardian/conjunto -- a decidir en el spike |
| Bootstrapping de la autoridad raíz de confianza | LexGuardian (gobierno) -- decisión de PKI, no técnica |
| ETag/versionado real, persistencia confirmada contra el backend real, fuente horaria del servidor (puntos 20-22, ya acordados en la V3 original) | LexGuardian, a probar en el spike |

---

## Cuerpo original de la V3 (referencia)

## 1. El ACK ya no es el eslabón débil

Diagnóstico correcto: un ACK sin firma ni hash firmado no se puede autenticar -- que Maira solo
tenga lectura no impide que otro escritor con acceso al buzón falsifique un ACK.

**Corregido**: el ACK deja de ser un subconjunto de campos y pasa a ser una **copia completa y
verificable** del checkpoint persistido -- incluye `FIRMA` y `SIGNED_PAYLOAD_HASH`. Maira puede
llamar a `verificar_checkpoint_estructural()` sobre el propio ACK antes de confiar en él, en vez
de asumir que vino del sitio correcto solo porque apareció en su buzón. Verificación
criptográfica real de `FIRMA` sigue pendiente del esquema de claves/PKI del spike -- lo que sí se
gana ya es detección de manipulación/falsificación estructural.

## 2. Gramática estricta: se sustituye "campo=valor" por un array JSON canónico

Tenías razón -- `"campo=valor\n"` no controla `=`, `CR/LF` ni Unicode sin escapar. En vez de
adoptar JSON canónico de objeto (que exigiría implementar RFC 8785: ordenar claves, normalizar
número/Unicode), usamos algo más simple con la misma garantía de determinismo: **un array JSON
de valores**, en el orden fijo de `CAMPOS_FIRMADOS_ANCLAJE_V3` -- el orden lo da la lista de
campos (fuera del documento), no las claves de un objeto, así que no hace falta canonicalizar
orden de claves. `json.dumps(valores, ensure_ascii=True, separators=(",", ":"))`: el escapado de
JSON resuelve `=`, saltos de línea y comillas; `ensure_ascii=True` evita la ambigüedad de
normalización Unicode al forzar `\uXXXX`; sin espacios, sin ambigüedad de formato.

`IDENTIDAD_FIRMANTE` ahora forma parte de `CAMPOS_FIRMADOS_ANCLAJE_V3` -- si se conserva, queda
firmada como pedías, no solo de adorno.

## 3. Conflicto: huella completa, no solo HASH_CABEZA

La detección de conflicto ahora agrupa por `SECUENCIA` y compara la huella
`(HASH_CABEZA, HASH_PAQUETE, VERSION_ESQUEMA)` -- dos ACKs con la misma cabeza pero distinto
`HASH_PAQUETE` o `VERSION_ESQUEMA` también bloquean la proyección con `CheckpointConflictivo`,
no solo una `HASH_CABEZA` distinta.

## 4. HASH_PAQUETE: ausencia tipada, definición exacta

Dos correcciones:

- **Ausencia tipada**: ya no existe el sentinela `"NULL"` de texto -- si no hay paquete, la clave
  `HASH_PAQUETE` sencillamente NO EXISTE en el registro (y aparece `MOTIVO_SIN_PAQUETE` en su
  lugar). En el payload firmado, un campo ausente serializa como `null` real (JSON), no como
  cadena vacía ni magia de texto.
- **Definición exacta**: `HASH_PAQUETE` es el SHA-256 de `manifiesto.md` **recalculado
  directamente**, nunca leído de `manifiesto.sha256`. Aunque ese archivo hoy está protegido por
  la exclusividad del directorio del paquete (`os.makedirs` sin `exist_ok`, que ya impide una
  segunda escritura del paquete completo), no tiene su propia protección `O_CREAT|O_EXCL` a nivel
  de archivo -- así que en vez de fiarnos de él, este módulo lo ignora por completo y recalcula
  el hash sobre el manifiesto real cada vez que hace falta.

## 5. Instantánea estable: releer antes de firmar no basta -- confirmar persistencia antes del ACK

De acuerdo en que un doble read local no puede simular la consistencia eventual de SharePoint --
eso es explícitamente trabajo del spike (ETag/versionado o primitiva equivalente, punto 20 más
abajo), no algo que este prototipo pueda demostrar contra un sistema de archivos local.

Lo que sí se corrigió ya: `_simular_claudia_crear_checkpoint` ahora **relee el checkpoint desde
disco después de escribirlo** y lo verifica estructuralmente (`verificar_checkpoint_estructural`)
antes de publicar su ACK -- nunca publica el ACK solo porque la escritura "aparentemente" tuvo
éxito. Si la relectura falla, se aborta con error en vez de publicar un ACK sobre algo que no se
pudo confirmar persistido.

## 6. Política de revocación: cese vs. compromiso, confianza inicial, rotación, fuente horaria

Implementada la distinción exacta que pediste:

- **`tipo="cese"`** (rotación normal, fin de vida útil): prospectiva -- invalida checkpoints
  firmados en o después de la revocación, nunca los anteriores.
- **`tipo="compromiso"`**: invalida checkpoints firmados en o después de `fecha_efectiva` -- la
  fecha ESTIMADA del compromiso, que puede ser anterior a cuándo se detectó/registró la
  revocación. Obliga (en términos de este módulo: hace que `obtener_estado_confirmado` deje de
  considerarlos firmes) a reanclar con una clave válida todo lo posterior a esa fecha. Probado
  explícitamente: un checkpoint firmado ANTES del aviso de revocación, pero después de la fecha
  estimada del compromiso, queda invalidado.

**Confianza inicial**: `registrar_clave_vigente()` -- una clave NUNCA se considera vigente solo
por aparecer en un checkpoint (antes, con solo el registro de revocación, el modelo era
implícitamente "confía salvo que esté revocada"; ahora es default-deny: hace falta alta
explícita). `obtener_estado_confirmado` comprueba alta + ausencia de corte de revocación antes de
dar algo por firme.

**Rotación**: no es un concepto aparte -- es registrar la clave nueva + revocar la vieja con
`tipo="cese"` desde la fecha de corte de la rotación. Ya cubierto por las dos piezas de arriba.

**Fuente horaria**: seguimos usando el reloj del proceso (`datetime.utcnow()`) -- no es una
fuente fiable frente a un adversario que controle el proceso emisor. **No resuelto aquí**: el
spike debe evaluar si puede usarse el timestamp que el propio backend (SharePoint/Purview) asigna
en servidor para las fechas que importan a la política de revocación, en vez de una que cualquiera
de las partes declare por su cuenta.

## Ampliación del spike (además de los puntos 1-19 ya acordados)

20. Confirmar que SharePoint ofrece ETag/versionado (o primitiva equivalente) utilizable para una
    instantánea realmente estable -- releer dos veces localmente no basta como prueba.
21. Confirmar que el checkpoint queda persistido (releíble, durable) antes de publicar su ACK
    contra el backend real, no solo en el prototipo local.
22. Verificar qué fuente de timestamp usa realmente el backend para los eventos relevantes a la
    política de revocación (servidor vs. declarado por el firmante).

## Qué depende de quién

| Pendiente | De quién |
|---|---|
| ACK completo y verificable, gramática canónica JSON, conflicto por huella completa | Ya implementado y probado (sintético) |
| HASH_PAQUETE con ausencia tipada, recalculado del manifiesto real | Ya implementado y probado |
| Confirmar persistencia antes de publicar ACK | Ya implementado y probado |
| Política cese/compromiso + confianza inicial (alta explícita) | Ya implementado y probado |
| Verificación criptográfica real de FIRMA (esquema de claves/PKI) | Conjunto -- a decidir en el spike |
| ETag/versionado real y fuente horaria fiable del backend | LexGuardian, a probar en el spike (puntos 20-22) |
