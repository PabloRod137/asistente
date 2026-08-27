# PROPUESTA_BROKER_ACL_MAIRA_CLAUDIA_V1

## Estado
Propuesta — pendiente de validación por Claudia. No implementado.

## Problema a resolver
El contrato V4 (ver `CONTRATO_MAIRA_CLAUDIA_V4_APROBADO.md`) exige que ningún paquete `READY`
pueda modificarse -- ni por Maira, ni por Claudia, ni por error. Hoy esa regla es solo una
promesa a nivel de código (ver `contrato_maira_claudia.py`, pruebas sintéticas). La carpeta
puente vive en el OneDrive personal de Alberto, y su cuenta (y todo lo que corre con ella,
incluida la vigilancia de Claudia) siempre tendrá permisos de dueño ahí -- ningún broker externo
puede quitarle eso desde fuera.

## Opción A -- Etiquetas de retención de Microsoft 365 (recomendada si está disponible)

Función de cumplimiento normativo nativa: un archivo marcado como "registro" (record) queda
bloqueado contra edición y borrado, sin programar nada.

- Ventaja: inmutabilidad real, impuesta por Microsoft, no por confianza en el código.
- **Precisión necesaria**: existen dos niveles, no uno. Un *record* normal puede ser desbloqueado
  por alguien con rol de administrador de cumplimiento -- no es inmutabilidad absoluta, es
  inmutabilidad frente a Maira/Claudia/uso normal. Un *regulatory record* sí queda bloqueado de
  forma irreversible, ni un administrador puede deshacerlo. Hay que decidir cuál de los dos
  nivele hace falta aquí (probablemente el nivel normal es suficiente para este caso, pero debe
  decidirse explícitamente, no asumirse).
- Riesgo a verificar: depende de si el plan de Microsoft 365 de LexGuardian incluye esta función
  (normalmente M365 E5 o el complemento de Cumplimiento).
- Riesgo técnico a verificar: un registro normalmente también bloquea que se pueda *mover* el
  archivo, no solo editarlo. Podría entrar en conflicto con que Claudia necesita mover paquetes
  entre `00_ORDENES_NUEVAS -> 01 -> ... -> 05_VALIDADAS`. Requiere prueba antes de adoptarla.

## Opción B -- Servicio broker propio

Un pequeño servicio intermediario que sea el único con permisos reales de escritura; Maira y
Claudia le piden las cosas a él en vez de tocar OneDrive directamente.

- Ventaja: control total, sin depender de licencias ni del comportamiento de una función de
  Microsoft.
- Coste real: hay que construirlo y mantenerlo, y el lado de Claudia también tendría que
  adoptarlo, cambiando su mecanismo actual (scripts propios que escriben directamente en
  OneDrive). No es algo que Maira pueda construir unilateralmente para el lado de Claudia.
- **Pendiente de definir**: quién alojaría y operaría este servicio (¿el servidor de Maira?
  ¿infraestructura de LexGuardian?). Un broker con permisos reales de escritura es en sí mismo
  un activo sensible que necesita su propia protección -- no resuelve el problema, lo traslada.

## Alcance -- pregunta adicional
Esta propuesta protege el canal nuevo de Maira (`03_MAIRA`). Los canales ya existentes de Alexia
(`01_ORDENES_ALEXIA` / `02_ENTREGAS_ALEXIA`) seguirían sin esta protección si no se extiende
también a ellos. ¿El objetivo es inmutabilidad real solo para Maira, o para todo `PUENTE_AGENTES`?

## Preguntas para Claudia
1. ¿Está disponible la función de etiquetas de retención en el plan de Microsoft 365 de
   LexGuardian, y sabes si es de nivel *record* o *regulatory record*?
2. Si no está disponible, ¿es viable que el lado de Claudia también adopte un broker común
   (Opción B), y quién lo alojaría?
3. ¿El alcance de esta protección debe cubrir solo `03_MAIRA` o todo `PUENTE_AGENTES`?
