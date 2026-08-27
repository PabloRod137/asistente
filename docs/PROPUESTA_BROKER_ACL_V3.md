# PROPUESTA_BROKER_ACL_MAIRA_CLAUDIA_V3

## Estado
V3 -- incorpora las 7 correcciones de Claudia sobre V2. Pendiente de validación tras el spike de
la Opción A. No implementado, sin datos reales.

## Decisión de proceso
Claudia prefiere explorar primero la **Opción A mediante un spike controlado en el tenant real**;
si licencia, API o bloqueo no cumplen, se pasa a la Opción B sin más rediseño previo. Esta V3 ya
no compara A y B en abstracto -- define el diseño corregido y el plan de spike concreto.

## 1. Diseño de eventos corregido (rechaza el V2)

El V2 proponía un `04_LOGS/eventos_estado.jsonl` compartido -- **rechazado**: rompe los nombres
canónicos y un archivo compartido exige que varios escritores modifiquen el mismo archivo, con
riesgo real de concurrencia, corrupción y pérdida de eventos.

Diseño corregido, **ya implementado y probado en `contrato_maira_claudia.py`** (pruebas
sintéticas, local):

```text
ESTADOS/{OPERATION_ID}/{timestamp}_{EVENT_ID}.json
ESTADOS/{OPERATION_ID}/{timestamp}_{EVENT_ID}.sha256
```

Cada transición es un **archivo independiente e inmutable**, nunca una edición de un archivo
existente. Campos de cada evento:

```text
EVENT_ID
OPERATION_ID
ESTADO_ANTERIOR
ESTADO_NUEVO
ACTOR
FECHA_UTC
MOTIVO
CLAVE_IDEMPOTENTE
HASH_PAQUETE
HASH_EVENTO_ANTERIOR   -- encadena con el hash del evento inmediatamente anterior
```

El **estado actual nunca se almacena como autoridad** -- se calcula siempre como una proyección
leyendo el evento más reciente de la cadena. La cadena completa es verificable: si se manipula o
se retira un evento intermedio, la verificación de la cadena falla de inmediato (probado con un
test que manipula un evento y confirma que la cadena deja de verificar).

`CLAVE_IDEMPOTENTE` es determinista (`{OPERATION_ID}:{ESTADO_NUEVO}`, sin el `EVENT_ID` dentro):
si se reintenta registrar exactamente la misma transición, se devuelve el evento ya existente en
vez de crear uno duplicado (probado).

**Limitación abierta, no resuelta todavía**: el diseño actual asume que las transiciones de una
misma operación las escribe un único actor a la vez. Si dos escrituras concurrentes para el
*mismo* `OPERATION_ID` llegasen a producirse (ej. un fallo en el propio proceso de Claudia que
lance dos workers para la misma operación), ambas podrían leer "sin evento anterior" al mismo
tiempo y generar dos eventos que referencian el mismo `HASH_EVENTO_ANTERIOR` -- una bifurcación
de la cadena, no detectada por la verificación actual (que solo comprueba el encadenamiento de
cada evento con su predecesor, no la ausencia de bifurcaciones). Mientras las transiciones sigan
siendo responsabilidad exclusiva de un único actor (Claudia, según el contrato ya aprobado), el
riesgo es bajo, pero no está eliminado por diseño. Si se considera relevante, habría que añadir
una comprobación explícita de bifurcaciones antes de dar esto por cerrado.

## 2. Plan de spike para la Opción A

A ejecutar por alguien con acceso al centro de cumplimiento (Purview) del tenant de LexGuardian
-- esto no lo puedo ejecutar yo sin ese acceso. Lista de verificación exacta pedida por Claudia:

1. **Licencia**: confirmar que el plan de Microsoft 365 de LexGuardian incluye etiquetas de
   retención / gestión de registros.
2. **Etiquetado automático o vía API**: comprobar si se puede aplicar la etiqueta de forma
   programática (Graph/API) al cerrar un paquete, no solo manualmente desde el centro de
   cumplimiento.
3. **Bloqueo real de edición y borrado**: crear un archivo de prueba, etiquetarlo como *record*,
   intentar editarlo y borrarlo -- confirmar que ambas cosas fallan.
4. **Desbloqueo**: confirmar qué rol exacto puede desbloquear un *record* normal, y si queda
   registrado en auditoría al hacerlo.
5. **Auditoría**: confirmar que el etiquetado, los intentos de edición/borrado bloqueados, y el
   desbloqueo quedan todos registrados de forma consultable.
6. **Concurrencia**: dos escrituras casi simultáneas al mismo paquete -- confirmar que no se
   corrompe ni se pierde ninguna, y qué pasa exactamente (error, cola, la segunda se rechaza).
7. **Latencia**: cuánto tarda en aplicarse la etiqueta tras la petición -- si hay una ventana en
   la que el archivo es editable antes de quedar sellado, hay que conocerla y diseñar en torno a
   ella (esta ventana ya deberíamos, en la práctica, mitigarla con el patrón `.partial` +
   renombrado atómico ya usado en el prototipo, que evita que un archivo a medio escribir
   aparente estar completo).
8. **Protección de eventos, no solo de paquetes**: los archivos de `ESTADOS/` (evento + hash)
   también deben poder etiquetarse igual que los paquetes -- confirmarlo específicamente, no
   asumir que aplica solo al paquete original.

Ninguno de estos ocho puntos está verificado todavía. El resultado de este spike decide si se
sigue con la Opción A o se pasa a la Opción B.

## 3. Ubicación e identidad técnica

- Sitio **corporativo de LexGuardian** (nunca personal), confirmado sin cambios desde V2.
- **Identidad técnica**: administrada (Managed Identity) o una aplicación con **certificado**
  (no secreto de cliente) y mínimo privilegio -- nunca credenciales personales. Nota: esto es más
  estricto que la app actual de Maira para Graph (que usa secreto de cliente, no certificado);
  para el componente que opere la carpeta puente habría que registrar esta identidad aparte, con
  autenticación por certificado.

## 4. Opción B (si el spike de A falla)

Se mantiene igual que en V2: servicio broker único escritor, alojado y operado por LexGuardian,
Maira/Claudia llaman solo a su API con mínimo privilegio, idempotencia y auditoría.

## 5. Ninguna prueba sintética habilita producción

Aunque el prototipo ya supera manipulación, duplicados, reintentos, y ahora también manipulación
de eventos y verificación de cadena -- **todo esto debe repetirse contra el sitio y el mecanismo
reales** una vez elegidos. Las pruebas sintéticas demuestran que el diseño es correcto, no que el
sistema real vaya a comportarse igual.

## Qué depende de quién

| Pendiente | De quién |
|---|---|
| Diseño de eventos corregido (independientes, encadenados) | Ya implementado y probado (sintético) |
| Ejecutar el spike de la Opción A (8 puntos) | LexGuardian (acceso a Purview) -- podemos ejecutarlo nosotros si se nos da ese acceso |
| Sitio SharePoint corporativo + identidad con certificado | LexGuardian (gobierno + creación) |
| Si el spike de A falla: construir/alojar/operar el broker (Opción B) | LexGuardian |
| Repetir las pruebas del prototipo contra el mecanismo real | Nuestra parte, una vez exista el entorno real |
