# PROPUESTA_ANCLAJE_EXTERNO_MAIRA_CLAUDIA_V3

## Estado
V3 -- incorpora los 6 puntos del veredicto de Claudia sobre la V2 (31/08/2026: "mejora
sustancialmente, pero requiere V3 antes del spike real"). Implementado y probado en
`contrato_maira_claudia.py` (pruebas sintéticas, local). No ejecutar todavía spike, sin
producción ni datos reales.

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
