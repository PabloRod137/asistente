# GUIA_ENTORNO_MICROSOFT_SPIKE_V1 -- Paso a paso para montar el entorno de pruebas

## Para qué sirve esta guía
Monta en el tenant de Microsoft 365 de LexGuardian el entorno que pide el spike
(`SPIKE_SHAREPOINT_INSTRUCCIONES_V1.md`): un sitio de pruebas de SharePoint, dos aplicaciones
técnicas con certificado, una etiqueta de retención que bloquea archivos y la auditoría activada.
Está escrita para alguien que **no ha administrado Microsoft 365 antes**.

> **Aviso sobre los menús.** Microsoft cambia nombres y ubicaciones de sus portales con frecuencia.
> Los nombres de abajo son los que conozco; si algo no coincide, busca la opción por su nombre en el
> buscador del propio portal y **anota lo que ves** (captura de pantalla), porque eso también es
> evidencia del spike. No he podido probar estos pasos contra vuestro tenant.

## 0. Antes de empezar: qué permisos necesitas (y quién los tiene)

La mayoría de estos pasos **solo los puede hacer un administrador del tenant**. Lo más probable es
que tú no lo seas. Tienes dos caminos:

- **A) Que lo haga el administrador contigo al lado** (compartiendo pantalla). Es lo más rápido y
  lo más seguro. Tú diriges y él pulsa.
- **B) Que te asigne roles temporales** en `admin.microsoft.com` → Roles → Roles de Microsoft Entra.
  Los que se necesitan, en su versión mínima:

| Para hacer | Rol de administrador |
|---|---|
| Crear el sitio de SharePoint | Administrador de SharePoint |
| Registrar aplicaciones y subir certificados | Administrador de aplicaciones (Application Administrator) |
| **Conceder el consentimiento de administrador** a los permisos de las apps | Administrador de rol con privilegios o Administrador global |
| Crear etiquetas de retención, ver auditoría | Administrador de cumplimiento (Compliance Administrator) o grupo de roles *Records Management* en Purview |

Pide que te los den **con fecha de caducidad** y que se retiren al terminar (sección 9).

**Antes de tocar nada, pide por escrito la autorización de la ventana de pruebas** (regla 3 del
spike). Sin eso, no sigas.

## 1. Comprobar la licencia (punto 1 del spike)

1. Entra en <https://admin.microsoft.com> con la cuenta de administrador.
2. **Facturación → Licencias**. Anota qué planes tiene LexGuardian (p. ej. Microsoft 365 Business
   Premium, E3, E5) y cuántas licencias hay asignadas.
3. Haz **captura de pantalla** de esa página. Es la evidencia del punto 1.
4. Comprueba en la documentación oficial de licencias de Microsoft si ese plan incluye **etiquetas de
   retención con "marcar como registro" (records management)**. No lo doy por supuesto: varía por
   plan y por año. Si el plan no lo incluye, **el spike de la Opción A termina aquí** y se pasa a la
   Opción B o a la base de datos.

## 2. Crear el sitio de pruebas en SharePoint

1. Desde el centro de administración de Microsoft 365, entra en **Centros de administración →
   SharePoint**. Se abre `https://<vuestrodominio>-admin.sharepoint.com`.
2. **Sitios → Sitios activos → Crear**.
3. Elige **Sitio de equipo** (Team site). Nombre: `SPIKE-Maira-Claudia`. Privacidad: **Privado**.
   Idioma: español. Propietario: la persona que administre el spike. No añadas más miembros.
4. Abre el sitio y, en la biblioteca **Documentos**, crea la estructura directamente ahí (no la
   crees fuera para copiarla). Hay **dos grupos de carpetas al mismo nivel, en la raíz de Documentos**:

   ```text
   Documentos
   ├── PUENTE_AGENTES                 ← canal del contrato V4 (nombres canónicos)
   │   └── 03_MAIRA
   │       ├── 00_ORDENES_NUEVAS   01_ORDENES_ACEPTADAS   02_EN_EJECUCION   03_BLOQUEADAS
   │       └── 04_ENTREGADAS       05_VALIDADAS           90_CANCELADAS      99_ARCHIVO
   │
   ├── ESTADOS                        ← eventos de estado (Broker V4)
   ├── NOTIFICACIONES_CABEZA          ← anclaje externo (V3), puntos 14-26
   ├── ANCLAJE_EXTERNO
   ├── ACKS_ANCLAJE
   ├── CLAVES_VIGENTES
   └── CLAVES_REVOCADAS
   ```

   (Nuevo → Carpeta, una por una. Respeta mayúsculas y guiones bajos exactos.)

   > **Por qué están al mismo nivel.** Los documentos aprobados fijan solo `PUENTE_AGENTES/03_MAIRA/...`.
   > Las demás carpetas (`ESTADOS`, `ANCLAJE_EXTERNO`, etc.) salen del prototipo, donde cuelgan todas
   > de una misma raíz, y los documentos no dicen dónde van en el sistema real. Para el spike se
   > ponen aparte, junto a `PUENTE_AGENTES`, no dentro. En producción, `ANCLAJE_EXTERNO` y las
   > carpetas de claves deberían vivir **fuera del alcance de Maira**; aquí, al ser un sitio de
   > pruebas, comparten sitio para simplificar.
5. Comprueba que **nadie más** tiene acceso al sitio: engranaje → **Permisos del sitio**.

### Obtener el ID del sitio y de la biblioteca (`MS_SITE_ID`, `MS_DRIVE_ID`)

1. Abre <https://developer.microsoft.com/graph/graph-explorer> e inicia sesión con tu cuenta.
2. Ejecuta (cambia el dominio y el nombre del sitio por los vuestros):

   ```text
   GET https://graph.microsoft.com/v1.0/sites/<dominio>.sharepoint.com:/sites/SPIKE-Maira-Claudia
   ```

   Copia el campo `id` de la respuesta: es el `MS_SITE_ID`.
3. Después ejecuta:

   ```text
   GET https://graph.microsoft.com/v1.0/sites/<MS_SITE_ID>/drives
   ```

   Copia el `id` de la biblioteca llamada "Documentos": es el `MS_DRIVE_ID`.
4. La primera vez, Graph Explorer pide aceptar permisos (`Sites.Read.All`): acéptalos con la cuenta
   de administrador. Estos valores **no son secretos**, pero se envían por un canal seguro.

## 3. Crear un certificado para las aplicaciones (sin secreto de cliente)

El spike exige autenticación por **certificado**, no por secreto. Creas un par: la parte pública
(`.cer`) se sube a Microsoft; la parte privada (`.pfx`) **nunca sale de tu equipo** ni va a git.

En **PowerShell** (no como administrador), en una carpeta **fuera del repositorio**, por ejemplo
`C:\spike-secretos\`:

```powershell
$cert = New-SelfSignedCertificate -Subject "CN=spike-maira" `
  -CertStoreLocation "Cert:\CurrentUser\My" -KeyExportPolicy Exportable `
  -KeySpec Signature -KeyLength 2048 -HashAlgorithm SHA256 `
  -NotAfter (Get-Date).AddMonths(3)

Export-Certificate -Cert $cert -FilePath "C:\spike-secretos\spike-maira.cer"

$pwd = Read-Host -AsSecureString "Contraseña para el .pfx"
Export-PfxCertificate -Cert $cert -FilePath "C:\spike-secretos\spike-maira.pfx" -Password $pwd

$cert.Thumbprint   # anótalo: es la "huella" del certificado
```

Repite **cambiando `spike-maira` por `spike-claudia`** para la segunda aplicación. Caducidad de 3
meses a propósito: es un entorno de pruebas.

## 4. Registrar las dos aplicaciones en Microsoft Entra ID

Repite el bloque para `spike-maira` y luego para `spike-claudia`.

1. Entra en <https://entra.microsoft.com> → **Identidad → Aplicaciones → Registros de aplicaciones →
   Nuevo registro**.
2. Nombre: `spike-maira`. Tipos de cuenta: **solo este directorio (un solo inquilino)**. URI de
   redirección: **déjalo vacío**. Pulsa **Registrar**.
3. En la página de la app, anota **Id. de aplicación (cliente)** → será `MS_CLIENT_ID`, y **Id. de
   directorio (inquilino)** → `MS_TENANT_ID`.
4. **Certificados y secretos → Certificados → Cargar certificado**: sube el `.cer` de esa app.
   Comprueba que la huella que aparece coincide con la que anotaste. **No crees ningún secreto de
   cliente.**
5. **Permisos de API → Agregar un permiso → Microsoft Graph → Permisos de la aplicación** (no
   delegados) → busca y añade **`Sites.Selected`**. Este permiso no da acceso a nada por sí solo:
   solo a los sitios que se le concedan explícitamente (paso 6).
6. Pulsa **Conceder consentimiento de administrador** (necesita el rol de la tabla de la sección 0)
   y confirma que el estado pasa a verde.

### Conceder a cada app acceso solo al sitio del spike

En Graph Explorer, con la cuenta de administrador y con permiso `Sites.FullControl.All` consentido
para tu usuario en Graph Explorer:

```text
POST https://graph.microsoft.com/v1.0/sites/<MS_SITE_ID>/permissions
Content-Type: application/json

{
  "roles": ["write"],
  "grantedToIdentities": [
    { "application": { "id": "<Id. de aplicación de spike-maira>", "displayName": "spike-maira" } }
  ]
}
```

Repite para `spike-claudia`. **Anota el resultado**, porque contiene un hallazgo importante:

> **Hallazgo previsible para el spike.** Los roles de `Sites.Selected` son `read`, `write` y `owner`.
> Lo normal es que `write` permita **editar y borrar**, así que probablemente **no se pueda
> expresar "Maira solo puede crear"** a nivel de aplicación. No es un error tuyo: es justo lo que el
> punto 3 y el Addendum del Broker V4 quieren descubrir. Si es así, anótalo como hallazgo y dáselo a
> Claudia: es un argumento a favor de la Opción B o de la base de datos.

## 5. Activar la auditoría de Microsoft Purview

1. Entra en <https://purview.microsoft.com> (o <https://compliance.microsoft.com>, según cómo esté
   desplegado vuestro tenant).
2. Busca **Auditoría**. Si aparece un aviso de que la auditoría no está activada, pulsa **Iniciar
   registro de la actividad de usuarios y administradores**. Puede tardar hasta unas horas en
   empezar a registrar.
3. Anota la **hora exacta de activación** (UTC).

Los eventos no aparecen al instante en la búsqueda; ese retraso es dato para los puntos 5 y 7.

## 6. Crear la etiqueta de retención que bloquea archivos

1. En Purview: **Soluciones → Administración de registros (Records Management)**. Si no aparece,
   busca "etiquetas de retención" en el buscador. Si **no aparece nada**, vuelve al paso 1: probablemente
   la licencia no lo incluye.
2. **Plan de archivos (File plan) → Crear una etiqueta** (o **Etiquetas de retención → Crear**).
3. Nombre: `SPIKE-Registro-Sellado`.
4. Configuración de retención: **Retener elementos** durante, por ejemplo, **1 año** desde la fecha de
   creación (es de pruebas).
5. Al terminar la retención: **No hacer nada** (que no borre por sí sola).
6. **Muy importante -- clasificación de los elementos:** elige **"Marcar elementos como un registro"
   (Mark items as a record)**, y **NO "…como registro reglamentario" (regulatory record)**.

   > ⚠️ **Un registro reglamentario es irreversible**: ni el administrador puede desbloquearlo ni
   > borrarlo hasta que acabe la retención. Con "registro" normal, un administrador con el rol
   > adecuado sí puede desbloquearlo, y eso es lo que probamos en el punto 4.
7. Termina y **publica la etiqueta**: **Directivas de etiquetas → Publicar etiquetas**, selecciona
   `SPIKE-Registro-Sellado` y limita la ubicación **únicamente al sitio `SPIKE-Maira-Claudia`** de
   SharePoint (nada más).
8. **Anota la hora UTC de publicación.** La etiqueta no aparece al instante en el sitio; puede tardar
   desde minutos hasta un día. Ese tiempo es una medida real del punto 7.

## 7. Prueba de humo (antes de dar el entorno por bueno)

En Graph Explorer, con tu cuenta de administrador:

1. Sube un archivo de texto sintético `SPIKE-prueba-001.txt` a `03_MAIRA/00_ORDENES_NUEVAS`.
2. Aplica la etiqueta de forma manual desde SharePoint (Detalles del archivo → Etiqueta de retención
   → `SPIKE-Registro-Sellado`) y anota qué ocurre.
3. Intenta editarlo y borrarlo. **Debería fallar**: eso es el punto 3.
4. Busca en Purview → Auditoría (rango de fechas de hoy, tipos de actividad de archivos) que aparecen
   los eventos. Puede tardar; si no salen en un rato, no es necesariamente un fallo, anótalo.
5. Para el punto 2 (etiquetar por API) hay una operación de Graph para la etiqueta de retención de un
   archivo (`retentionLabel` sobre un `driveItem`). **Es un candidato a confirmar, no un dato
   comprobado:** busca en la documentación oficial de Graph el endpoint y los permisos exactos, y
   pruébalo con la identidad `spike-claudia` para ver si funciona con permisos de aplicación.

Si los pasos 2 y 3 funcionan, el entorno está listo. Si no, para y anótalo: ya tienes un `FAIL`
documentado del punto 2 o 3.

## 8. Qué nos tienes que pasar (y qué NO)

**Sí** (por un canal seguro, no por chat ni correo en claro):

| Dato | Ejemplo |
|---|---|
| `MS_TENANT_ID` | GUID |
| `MS_SITE_ID`, `MS_DRIVE_ID` | de la sección 2 |
| `MS_CLIENT_ID` de `spike-maira` y de `spike-claudia` | GUID |
| Huellas (*thumbprints*) de los certificados | 40 caracteres hex |
| Nombre exacto de la etiqueta | `SPIKE-Registro-Sellado` |
| Hora UTC de publicación de la etiqueta y de activación de la auditoría | |
| Capturas de licencias, permisos concedidos y estado de la etiqueta | |

**No**: los archivos `.pfx`, la contraseña del certificado, ni ningún token. Si el código de Maira
necesita el `.pfx` para autenticarse, se instala en la máquina que ejecute el spike, no se envía.

## 9. Al terminar: limpieza (obligatoria)

1. **Entra → Registros de aplicaciones**: elimina `spike-maira` y `spike-claudia` (o al menos borra
   sus certificados).
2. Borra los `.pfx` y `.cer` de `C:\spike-secretos\` y quita el certificado de tu almacén
   (`certmgr.msc` → Personal → Certificados).
3. En SharePoint, elimina el sitio `SPIKE-Maira-Claudia` **solo cuando el administrador lo confirme**.
   Los archivos etiquetados como registro pueden impedir el borrado hasta desbloquearlos (punto 4).
4. Pide que se retiren los roles temporales de la sección 0.
5. Confirma por escrito que no se ha tocado el `.env` de producción de Maira ni `PUENTE_AGENTES` del
   OneDrive personal de Alberto.

## 10. Si te atascas

- **No veo la opción X en el portal**: usa el buscador del portal; si no existe, casi seguro es falta
  de licencia o de rol. Anótalo, no lo saltes.
- **"Se requiere consentimiento de administrador"**: te falta el rol de la sección 0.
- **La etiqueta no aparece en el sitio**: espera; si pasa un día, revisa que la directiva esté
  publicada solo en ese sitio y sin errores.
- **Cualquier duda sobre si algo afecta a datos reales**: para y pregunta. Este entorno es solo para
  archivos sintéticos.

## 11. Qué gana el spike con esto

Con este entorno se pueden ejecutar los puntos 1 a 5 y 8 a mano, y sirve de base para el resto. Los
puntos de concurrencia y latencia (6 y 7) necesitan además el arnés de pruebas automáticas (tarea T2
del `SPIKE_SHAREPOINT_INSTRUCCIONES_V1.md`), que es trabajo nuestro y no de esta guía.
