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

- **Pendiente de definir**: ¿cómo se entera Maira de la identidad ya resuelta para mensajes
  futuros del mismo teléfono? Si la resolución se queda solo en el lado de Claudia y nunca
  vuelve a Maira, cada mensaje nuevo de ese cliente seguiría marcándose
  `IDENTIDAD_PENDIENTE` indefinidamente, aunque ya se sepa quién es. Posibles caminos: que el
  acuse o una futura salida lleve de vuelta el `CLIENTE_ID` resuelto para que Maira lo recuerde,
  o aceptar que se resuelve de cero en cada entrega (más simple, pero repite trabajo).

## Opción 2 -- Índice derivado, mínimo y de solo lectura

Si se prefiere que Maira pueda resolverlo sola (por ejemplo, para responder más rápido al
cliente sin esperar a que Claudia procese), se generaría un índice aparte con **solo** estos
campos (minimización de datos):

```text
TELEFONO -> CLIENTE_ID, EXPEDIENTE_ID(s) activos, NUMERO_VISIBLE
```

Sin NIF, sin direcciones, sin datos bancarios, sin ningún otro campo de
`Archivo_Maestro_Clientes`.

- **Precisión sobre el mecanismo**: este índice debe ser una **exportación derivada periódica**
  (un archivo que Claudia/M365 genera y actualiza), no credenciales para que Maira consulte la
  lista en vivo -- si Maira tuviera acceso de consulta en vivo a `Archivo_Maestro_Clientes`,
  aunque fuera de solo lectura, seguiría siendo "Maira consultando SharePoint directamente",
  justo lo que el contrato prohíbe. La exportación evita eso por diseño.
- **Precisión sobre `EXPEDIENTE_ID`**: cuando un cliente tiene varios expedientes abiertos a la
  vez, el índice solo puede resolver de forma fiable el `CLIENTE_ID`. Cuál de sus expedientes
  corresponde a un mensaje concreto sigue siendo una suposición (como ya hace la captura
  estructurada hoy), no algo que el índice resuelva por sí solo.
- Queda por definir: quién genera/actualiza la exportación, con qué periodicidad, y dónde vive
  el archivo (¿la propia carpeta puente, en una ubicación aparte?).

## Preguntas para Claudia
1. ¿Opción 1 o Opción 2?
2. Si es la 1: ¿cómo debe enterarse Maira de una identidad ya resuelta, si es que debe enterarse?
3. Si es la 2: ¿quién generaría la exportación, con qué periodicidad, y dónde viviría?
