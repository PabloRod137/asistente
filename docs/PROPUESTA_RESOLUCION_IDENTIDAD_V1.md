# PROPUESTA_RESOLUCION_IDENTIDAD_V1

## Estado
Propuesta — pendiente de validación por Claudia. No implementado, sin datos reales.

## Contexto
El contrato V4 dice: "la resolución teléfono→cliente la hará Claudia/M365 o un índice derivado,
mínimo y solo lectura, autorizado aparte" (Maira no consulta SharePoint directamente). Antes de
construir nada, necesitamos saber cuál de las dos opciones prefiere Claudia -- son muy distintas
en esfuerzo y en superficie de datos expuesta.

## Opción 1 -- Claudia resuelve la identidad ella misma (más simple, cero desarrollo nuevo)

Maira solo manda `TELEFONO_CORRELACION` con `ESTADO_IDENTIDAD: IDENTIDAD_PENDIENTE`. Cuando
Claudia procesa el paquete (ya tiene acceso directo a `Archivo_Maestro_Clientes`), resuelve
`CLIENTE_ID`/`EXPEDIENTE_ID` como parte de su propio flujo. No se construye nada nuevo por
nuestra parte.

## Opción 2 -- Índice derivado, mínimo y de solo lectura

Si se prefiere que Maira pueda resolverlo sola (por ejemplo, para responder más rápido al
cliente sin esperar a que Claudia procese), se generaría un índice aparte -- no el acceso
general que ya tiene Maira -- con **solo** estos campos (minimización de datos):

```text
TELEFONO -> CLIENTE_ID, EXPEDIENTE_ID(s) activos, NUMERO_VISIBLE
```

Sin NIF, sin direcciones, sin datos bancarios, sin ningún otro campo de
`Archivo_Maestro_Clientes`. Queda por definir:
- Quién genera/actualiza este índice (¿una exportación periódica desde el lado de Claudia?).
- Con qué periodicidad se refresca.
- Con qué credenciales de solo lectura accede Maira, autorizadas aparte del acceso general
  de Graph que ya tiene hoy.

## Pregunta para Claudia
¿Opción 1 o Opción 2? Si es la 2: ¿quién generaría ese índice, con qué periodicidad, y dónde
viviría?
