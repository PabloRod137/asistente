# PROPUESTA_BROKER_ACL_MAIRA_CLAUDIA_V4

## Estado
V4 -- incorpora los 4 cierres obligatorios sobre V3 y las 6 correcciones sobre el spike de la
Opción A. Pendiente de validación. No implementado en producción, sin datos reales.

## 1. Los 4 cierres obligatorios -- ya implementados y probados (sintético, local)

**Bifurcación**: se impide por diseño, no por convención de "un solo actor". Cada evento reclama
un número de `SECUENCIA` mediante creación exclusiva de archivo (`O_CREAT|O_EXCL`), la primitiva
compare-and-swap real que garantiza el sistema de archivos. Probado con **20 hilos reales**
reclamando secuencia concurrentemente para la misma operación: cero colisiones, cero huecos.

**Idempotencia por comando, no por estado destino**: `CLAVE_IDEMPOTENTE` identifica el
comando/intento de origen, no el estado al que se transiciona -- permite que un mismo estado se
visite legítimamente varias veces (`EJECUCIÓN→BLOQUEADA→EJECUCIÓN→BLOQUEADA`, probado). Reintentar
el mismo comando_id devuelve el evento existente; el mismo comando_id con un estado distinto se
rechaza como conflicto.

**SECUENCIA monotónica**: asignada atómicamente (no el timestamp, que no garantiza orden único).
El diagnóstico de la cadena distingue explícitamente huecos, ruptura del encadenamiento de hashes,
y ausencia del evento de mayor secuencia reclamada.

**Anclaje de la cabeza de cadena**: la reclamación de secuencia (`.claim`) es un artefacto
independiente del contenido del evento (`.json`/`.sha256`). Si se borra el evento pero no su
`.claim`, se detecta como hueco en la posición más alta (probado). **Límite reconocido**: esto no
protege contra un atacante que borre ambos artefactos -- eso requiere un anclaje cruzado con un
tercero independiente (el propio Claudia manteniendo su copia del último estado conocido), fuera
de lo que el código de Maira puede garantizar en solitario.

`obtener_estado_actual` **bloquea la proyección** (lanza `CadenaEventosInvalida`) en cualquiera de
estos casos -- nunca devuelve un estado potencialmente manipulado o desactualizado.

## 2. Sellado de paquete: nunca dos escrituras

Corregido: `crear_operacion_entrada` (y toda creación de paquete) usa creación exclusiva de
carpeta -- si por cualquier motivo se intentase escribir dos veces sobre el mismo `OPERATION_ID`,
la segunda escritura falla explícitamente en vez de coescribir en silencio.

## 3. Ventana de latencia entre READY y protección real

`.partial` + renombrado atómico evita publicar contenido incompleto, pero no cubre la ventana
entre marcar `READY` (sellado local) y que el mecanismo elegido (etiqueta de retención u otro)
aplique la protección real. Añadido: `paquete_accesible(operation_id)` devuelve `False` hasta que
se registre una `confirmar_sellado_real()` explícita -- en producción, disparada solo por una
señal real del mecanismo (respuesta de la API de etiquetado, webhook de Purview), nunca
automática al crear el paquete.

## 4. Plan de spike ampliado para la Opción A

Además de los 8 puntos ya definidos en V3 (licencia, etiquetado por API, bloqueo, desbloqueo,
auditoría, concurrencia, latencia, protección de eventos), el spike debe probar explícitamente:

9. **Eliminación del último evento** -- confirmar que el mecanismo real también lo hace detectable
   (o, si no, qué mitigación adicional hace falta).
10. **Eventos fuera de orden** -- forzar la escritura de un evento con secuencia anterior después
    de uno posterior, confirmar que se detecta.
11. **Dos ramas concurrentes** -- intentar deliberadamente una bifurcación real contra el
    mecanismo elegido, no solo contra el prototipo.
12. **Repetición legítima de un estado** -- confirmar que el mecanismo real no confunde esto con
    un duplicado.
13. **Indisponibilidad/timeout de Purview** -- qué ocurre si el servicio no responde a tiempo
    durante el sellado.

**Formato de evidencia por cada punto probado** (obligatorio, sin datos reales): hora UTC,
identidad usada, petición/respuesta, auditoría obtenida, veredicto `PASS`/`FAIL`.

**Restricción de ejecución**: el spike solo puede ejecutarse en un sitio/biblioteca de prueba
corporativa, con archivos sintéticos, y con autorización expresa del administrador del tenant --
nunca sobre el puente actual (`PUENTE_AGENTES` en el OneDrive personal de Alberto).

## Qué depende de quién

| Pendiente | De quién |
|---|---|
| Los 4 cierres obligatorios (bifurcación, idempotencia, secuencia, anclaje) | Ya implementados y probados (sintético, incluida concurrencia real con hilos) |
| Sellado sin doble escritura | Ya implementado |
| Guardia de ventana de latencia (`paquete_accesible`) | Ya implementado (el disparo real depende del mecanismo elegido) |
| Ejecutar el spike ampliado (13 puntos) en sitio de prueba corporativo | LexGuardian (autorización + acceso a Purview) -- nosotros si se nos da acceso |
| Anclaje cruzado independiente contra borrado total de un evento | Conjunto -- requiere que Claudia mantenga su propia copia de verificación, no resoluble solo por Maira |
| Repetir todo contra el mecanismo y sitio reales una vez decidido | Nuestra parte |
