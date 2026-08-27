# RESOLUCION_IDENTIDAD_V1 -- APROBADA

## Estado
APROBADA con Opción 1 y addendum vinculante (27/08/2026). Implementación NO autorizada, datos
reales NO autorizados -- solo pruebas sintéticas (mismo régimen que el contrato principal).

## Diseño aprobado

- **Maira nunca resuelve identidad por sí sola.** Envía `TELEFONO_CORRELACION` y
  `ESTADO_IDENTIDAD: IDENTIDAD_PENDIENTE`. No consulta SharePoint, no mantiene ningún índice
  propio (la Opción 2, el índice derivado, queda descartada por ahora).
- Claudia responde con una **operación nueva** (nunca editando la original):
  ```text
  TIPO: RESOLUCION_IDENTIDAD
  DIRECCION: CLAUDIA_A_MAIRA
  PARENT_OPERATION_ID: {operación original de Maira}
  CLIENTE_ID: {canónico, o vacío}
  RESULTADO: UNICO | AMBIGUO | NO_ENCONTRADO
  EXPEDIENTE_ID: {solo si hay correspondencia inequívoca -- si hay varios expedientes, vacío}
  ```
- **Uso estrictamente puntual**: Maira solo puede usar esa resolución para la conversación/operación
  enlazada por ese `PARENT_OPERATION_ID`. **No crea ninguna asociación permanente
  teléfono→cliente** -- el número puede cambiar de dueño, reciclarse o compartirse.
- **Cada mensaje futuro se resuelve de nuevo**, sin excepción. Claudia puede optimizar esto con
  caché interna de su lado; esa caché nunca se expone a Maira ni Maira depende de ella.
- Con varios expedientes abiertos y sin correspondencia inequívoca: `RESULTADO: AMBIGUO`,
  exige selección o revisión humana -- Maira nunca elige uno por su cuenta.

## Implicación directa para el código

`contrato_maira_claudia.py` no debe implementar ningún tipo de caché, tabla o diccionario que
persista una relación teléfono→cliente entre operaciones. Cada resolución se consume una vez,
para la operación que la originó, y se descarta.
