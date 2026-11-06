# AWS Image Processing Project

Este proyecto integra varios servicios de AWS para procesar imágenes subidas a S3, generar thumbnails, guardar metadatos en DynamoDB y mostrar los resultados en una página web estática.

---

## **Arquitectura del Proyecto**

- **Amazon S3**: Almacena las imágenes originales y los thumbnails generados.
- **Amazon SQS**: Cola de mensajes que desencadena el procesamiento de imágenes.
- **AWS Lambda**: Procesa las imágenes, genera thumbnails y guarda los metadatos.
- **Amazon DynamoDB**: Almacena los metadatos de las imágenes.
- **Amazon API Gateway (HTTP API)**: Permite invocar la función Lambda a través de endpoints HTTP (además del trigger SQS).
- **Página Web Estática**: Muestra los thumbnails generados, alojada en S3.

---

## **Requisitos**

### Herramientas
- **AWS CLI** configurado con credenciales.
- **Python 3.8 o superior**.
- **Pillow** para manejo de imágenes.
- **Boto3** para interacción con AWS.

### Credenciales
Copia `.env.example` como `.env` en la raíz del proyecto y rellénalo con las credenciales de Learner Lab (**AWS Details → AWS CLI**). Los nombres van en mayúsculas, que es como los leen los scripts:
```plaintext
AWS_ACCESS_KEY_ID=YOUR_ACCESS_KEY
AWS_SECRET_ACCESS_KEY=YOUR_SECRET_KEY
AWS_SESSION_TOKEN=YOUR_SESSION_TOKEN
AWS_DEFAULT_REGION=us-east-1
```
Las credenciales del lab caducan al cerrar la sesión: cuando las renueves, actualiza el `.env` y vuelve a ejecutar `get_LabRole_arn.py`.

---

## **Instalación**

1. Instala las dependencias:
   ```bash
   pip install -r requirements.txt
   ```

---

## **Despliegue completo con un solo comando**

`deploy_all.py` ejecuta todos los pasos siguientes en orden (LabRole, buckets, cola, tabla, Lambda, trigger SQS, API Gateway, web estática y subida de imágenes), espera a que la Lambda procese las imágenes y prueba la API:

```bash
python deploy_all.py
python deploy_all.py --skip-images   # sin subir img/ ni esperar el procesamiento
python deploy_all.py --skip-test     # sin probar la API al final
```

Si un paso falla (por ejemplo, porque han caducado las credenciales), corrige el problema y vuelve a lanzarlo: los recursos que ya existen se reutilizan. Al final muestra las URLs de la API y de la web. Para borrarlo todo: `python remove_aws_resources.py --really-delete`.

Los apartados siguientes explican cada paso por separado.

---

## **Ejecución**

### 1. Crear Buckets de S3
Ejecuta el script para crear los buckets necesarios:
```bash
python setup_scripts/create_s3_buckets.py
```

Verifica que los buckets existen:
```bash
aws s3 ls
```

---

### 2. Configurar la Cola SQS
Crea la cola SQS:
```bash
python setup_scripts/create_sqs_queue.py
```

Verifica que la cola exista:
```bash
aws sqs list-queues
```
Esto sería un ejemplo de posible mensaje a enviar en la cola:
```json
{
  "Records": [
    {
      "messageId": "19dd0b57-b21e-4ac1-bd88-01bbb068cb78",
      "receiptHandle": "MessageReceiptHandle",
      "body": "{\"bucket_name\":\"image-uploads-bucket-20251017-fe41ce32\",\"image_key\":\"statue_small.jpg\"}",
      "attributes": {
        "ApproximateReceiveCount": "1",
        "SentTimestamp": "1523232000000",
        "SenderId": "123456789012",
        "ApproximateFirstReceiveTimestamp": "1523232000001"
      },
      "messageAttributes": {},
      "md5OfBody": "d41d8cd98f00b204e9800998ecf8427e",
      "eventSource": "aws:sqs",
      "eventSourceARN": "arn:aws:sqs:us-east-1:123456789012:MyQueue",
      "awsRegion": "us-east-1"
    }
  ]
}
```

---

### 3. Configurar la Tabla DynamoDB
Crea la tabla DynamoDB para los metadatos:
```bash
python setup_scripts/create_dynamodb_table.py
```

Observar que hay un shelve llamado aws_resources.db donde todos los resultados intermedios del workflow se van guardando.
Por ejemplo, nombre del bucket creado para guardar imágenes. El siguiente comando muestra sus contenidos.
```bash
python show_shelve.py
```

Verifica que la tabla exista:
```bash
aws dynamodb list-tables
```

---

### 4. Configurar la Función Lambda
0. Ejecutar comando para recuperar referencia a LabRole (vuelve a ejecutarlo cada vez que cambies las credenciales del `.env`, p. ej. al reiniciar el lab):
  ```bash
   python setup_scripts/get_LabRole_arn.py
   ```

1. Empaquetado: **no hace falta hacerlo a mano**. `configure_lambda.py` genera el ZIP en memoria con `lambda_function.py` (boto3 ya viene incluido en el runtime de Lambda, y el comando `zip` no existe en Git Bash para Windows).
Nota de esta versión: el procesamiento de miniaturas con Pillow está desactivado temporalmente para evitar incompatibilidades al empaquetar dependencias nativas en Windows. No se generan thumbnails hasta habilitar un paquete compatible con el runtime Linux de Lambda. API Gateway no cambia esta limitación.

2. Configura la función Lambda (la crea o, si ya existe, actualiza su código y configuración):
   ```bash
   python setup_scripts/configure_lambda.py
   ```
   El script configura estas variables de entorno de la Lambda a partir de `aws_resources.db`: `SOURCE_BUCKET` (bucket de imágenes), `THUMB_BUCKET` (bucket de thumbnails) y `TABLE_NAME` (tabla DynamoDB).

3. Configura el trigger de SQS para Lambda:
   ```bash
   python setup_scripts/add_sqs_trigger.py
   ```

---
### 5. Subir Imágenes y Enviar Mensajes
1. Asegúrate de tener imágenes en la carpeta `img/`.
2. Sube las imágenes y envía mensajes a SQS:
   ```bash
   python setup_scripts/upload_folder_images.py
   ```

---

### 6. Verificar Resultados
1. **Bucket de Thumbnails** (consulta el nombre real con `python show_shelve.py`, clave `thumbnails-bucket`):
   ```bash
   aws s3 ls s3://<thumbnails-bucket>/thumbnails/
   ```

2. **Tabla DynamoDB**:
   ```bash
   aws dynamodb scan --table-name ImageMetadata
   ```

3. **Logs de Lambda**:
   Revisa los logs para errores:
   ```bash
   aws logs describe-log-groups
   aws logs get-log-events --log-group-name /aws/lambda/ImageProcessingFunction --log-stream-name <log_stream_name>
   ```

---

### 7. Subir Página Web Estática
1. Asegúrate de que la página web esté configurada en `s3_static_website/`.
2. Ejecuta el script para subir la página:
   ```bash
   python setup_scripts/deploy_static_site.py
   ```

3. Accede a la página web con la URL que imprime el script (sustituye `<thumbnails-bucket>` por el nombre real):
   ```
   http://<thumbnails-bucket>.s3-website-us-east-1.amazonaws.com/
   https://<thumbnails-bucket>.s3.amazonaws.com/index.html
   ```


### 8. Queries over DynamoDB
Here’s the fast way to run queries against your DynamoDB table from the AWS Console.

1) Open the table

Go to DynamoDB in the AWS Console (make sure you’re in the same region where the table lives).

Tables → click your table (e.g., ImageMetadata).

2) Explore items (point-and-click)

Tab Explore items.

At the top, switch between:

Query – efficient, but it requires the partition key.

Scan – reads the whole table and can then filter (slower, costs more).

With your current schema

Your table has only a partition key ImageID (no sort key). That means:

Query works only when you provide an exact ImageID value.

In the left panel, set ImageID = "statue_small.jpg" → Run.

For anything else (e.g., “all images”, “all with ‘thumb’ in URL”), use Scan and add a Filter.

Useful filters (Scan)

Click Add new filter:

attribute_exists(ThumbnailURL)

contains(ThumbnailURL, "thumbnails/")

begins_with(ImageID, "statue_") (works, but still a Scan since you have no sort key)

Tip: Filters don’t reduce read capacity consumed by a Scan; they only reduce the results returned. Use sparingly on large tables.

3) Query with PartiQL (SQL-like)

In the table view, open PartiQL editor (top-right).

Run statements like:
```sql
-- Exact match by partition key (fast)
SELECT * FROM "ImageMetadata" WHERE ImageID = 'statue_small.jpg';

-- Return only certain attributes
SELECT ImageID, ThumbnailURL FROM "ImageMetadata" WHERE ImageID = 'statue_small.jpg';

-- Scan with a filter (because no sort key/index for these predicates)
SELECT * FROM "ImageMetadata" WHERE contains(ThumbnailURL, 'thumbnails/');

-- Update one item
UPDATE "ImageMetadata"
SET Note = 'Reprocessed'
WHERE ImageID = 'statue_small.jpg';

-- Delete one item
DELETE FROM "ImageMetadata" WHERE ImageID = 'old_image.jpg';
```

Click Run to execute, results appear below. PartiQL is great for quick ad-hoc reads/updates/deletes.

---

## **9. Publicar y probar la función Lambda mediante API Gateway (AWS Academy Learner Lab)**

> **Objetivo:** exponer `ImageProcessingFunction` como una **HTTP API**, sin eliminar el trigger de SQS. Estos pasos se realizan desde la **AWS Console** abierta a través de Learner Lab. Región utilizada: `us-east-1` (N. Virginia).
>
> **Importante:** API Gateway no convierte automáticamente una función que solo procesa mensajes SQS en una función HTTP. Para las rutas de este ejemplo, el `lambda_handler` desplegado debe reconocer eventos **API Gateway HTTP API (payload 2.0)** y devolver una respuesta HTTP adecuada. Si la versión actual de `lambda_function.py` solo procesa `event["Records"]`, hay que adaptar y volver a desplegar el código antes de seguir. No asumas que crear las rutas es suficiente.

### 9.1. Comprobaciones previas en la consola

1. En **AWS Academy Learner Lab**, inicia el laboratorio y selecciona **AWS Console**.
2. Comprueba que estás en **United States (N. Virginia) / us-east-1**.
3. Abre **Lambda → Functions → ImageProcessingFunction**. Comprueba que existe, que su última actualización está completada (`Last update status: Successful`) y que el **handler** corresponde al módulo y función realmente desplegados (por ejemplo, `lambda_function.lambda_handler`).
4. En **Configuration → Environment variables**, comprueba los valores que necesita el código para acceder a buckets, cola y tabla DynamoDB. Los nombres exactos dependen de la implementación; consulta el código de la función.
5. Comprueba que el **execution role** de Lambda tiene los permisos mínimos para los recursos utilizados (habitualmente S3, DynamoDB, CloudWatch Logs y, si procede, SQS). En Learner Lab suele usarse `LabRole`, siempre que la configuración del laboratorio lo permita.
6. Verifica los recursos creados mediante `python show_shelve.py`; `aws_resources.db` guarda nombres y URLs **localmente**, pero esos datos **no se transmiten automáticamente a Lambda**.

**Si `configure_lambda.py` termina con `TimeoutError` o `ConnectionClosedError`:** verifica primero si la función existe (puede haberse creado pese al error), con `aws lambda get-function --function-name ImageProcessingFunction --region us-east-1`. Evita crear duplicados. Si el ZIP es grande, súbelo a S3 y en Lambda usa **Code → Upload from → Amazon S3 location** indicando una URL `s3://...` del paquete compatible. Comprueba después el estado de actualización. **Subir el ZIP no garantiza que el código sea ejecutable**: comprueba su estructura y las dependencias de Linux.

### 9.2. Verificar la compatibilidad de la función con HTTP

Antes de crear API Gateway, en **Lambda → Test** ejecuta una prueba con un evento representativo de HTTP API v2:

```json
{
  "version": "2.0",
  "routeKey": "GET /health",
  "rawPath": "/health",
  "headers": {},
  "requestContext": { "http": { "method": "GET", "path": "/health" } },
  "isBase64Encoded": false
}
```

Una implementación compatible podría responder:

```json
{ "statusCode": 200, "headers": { "content-type": "application/json" }, "body": "{\"status\":\"ok\"}" }
```

Esto es un **ejemplo de contrato**, no una garantía de que la versión desplegada contenga esa ruta. `GET /health` es una comprobación sencilla **solo si se ha implementado en el código**.

Para `POST /process`, el handler puede esperar un JSON como `{"image_key":"statue_small.jpg"}` en el campo `body` del evento HTTP y obtener el bucket de una variable de entorno o de un parámetro explícito (según la implementación). Hay que analizar/decodificar `body`, validar los campos y devolver `statusCode` y `body`. El objeto solicitado **debe existir ya en el bucket de imágenes**. La función debe seguir distinguiendo los eventos SQS (`Records`) de los eventos HTTP.

### 9.2bis. Opción rápida: crear y probar la HTTP API con scripts (boto3)

Los apartados 9.3 y 9.4 se pueden automatizar por completo. El script hace lo mismo que la consola: crea la HTTP API `ImageProcessingAPI`, la integración Lambda proxy (payload 2.0), las rutas `GET /health` y `POST /process`, el stage `$default` con auto-deploy y el **permiso de invocación** de API Gateway sobre la Lambda.

```bash
python setup_scripts/create_api_gateway.py
```

Se puede ejecutar varias veces sin crear duplicados: si la API, la integración, las rutas, el stage o el permiso ya existen, los reutiliza. Guarda `api-id` y `api-endpoint` en `aws_resources.db` (consúltalos con `python show_shelve.py`).

Para probarla (la imagen tiene que estar ya en el bucket de imágenes, ver paso 5):
```bash
python setup_scripts/test_api_gateway.py                  # usa statue_small.jpg
python setup_scripts/test_api_gateway.py woodcutters.jpg  # otra imagen
```

Para borrar todo lo creado por la práctica (API, Lambda y su trigger SQS, cola, tabla DynamoDB y buckets), usa `remove_aws_resources.py`. Solo borra lo registrado en `aws_resources.db`; sin `--really-delete` solo muestra lo que borraría:
```bash
python remove_aws_resources.py                  # simulación
python remove_aws_resources.py --really-delete  # borrar
```

Si usas los scripts, puedes saltar a **9.6** para comprobar el resultado de extremo a extremo. Los apartados 9.3–9.5 explican el mismo proceso desde la consola.

### 9.3. Crear una HTTP API desde AWS Console

1. Abre **Services → API Gateway → APIs → Create API**.
2. En **HTTP API** selecciona **Build** (no REST API para este ejercicio).
3. Selecciona **Add integration → Lambda**, región `us-east-1`, función `ImageProcessingFunction`.
4. Asigna un nombre, por ejemplo `ImageProcessingAPI`.
5. Crea estas rutas **si están implementadas en la Lambda**:

   | Method | Route | Integración | Finalidad |
   |---|---|---|---|
   | `GET` | `/health` | `ImageProcessingFunction` | Comprobar disponibilidad |
   | `POST` | `/process` | `ImageProcessingFunction` | Solicitar procesamiento de una imagen de S3 |

6. Si el asistente ha creado una ruta `$default` o no ha creado las anteriores, abre **Develop → Routes**, crea las rutas que falten y asígnales la integración Lambda en **Develop → Integrations**.
7. Usa **Lambda proxy integration** y, para estos ejemplos de eventos, **Payload format version 2.0**. En la configuración de la integración comprueba **Invoke permissions**; cuando la consola lo solicite, concede a API Gateway permiso para invocar esta Lambda. Se trata de un permiso en la política basada en recursos de Lambda, **distinto** del execution role usado por Lambda para acceder a S3/DynamoDB.
8. Guarda los cambios.

### 9.4. Stages y despliegue: atención a *Auto-deploy*

En **Deploy → Stages** puedes encontrar `$default` y `test`. En la configuración de Learner Lab mostrada durante el ejercicio **ambos tienen `Auto-deploy enabled`**. En ese caso, al pulsar **Deploy**, el menú muestra los stages en gris: **es el comportamiento esperado, no un error**.

- **Opción recomendada (automática):** mantén **Auto-deploy** habilitado. Cierra el cuadro *Deploy API* con **Cancel** y prueba directamente la URL del stage. Las modificaciones de rutas e integraciones se publican automáticamente.
- **Opción manual:** abre **Stages → selecciona `$default` (o `test`) → Edit → desactiva Auto-deploy → Save**. Después utiliza **Deploy**, selecciona ese stage y confirma. Esta opción solo es necesaria si quieres practicar despliegues manuales.

**URLs de invocación (reemplaza `<api-id>` por el identificador real mostrado en la consola):**

| Stage | URL base | Ejemplo de prueba |
|---|---|---|
| `$default` | `https://<api-id>.execute-api.us-east-1.amazonaws.com` | `https://<api-id>.execute-api.us-east-1.amazonaws.com/health` |
| `test` | `https://<api-id>.execute-api.us-east-1.amazonaws.com/test` | `https://<api-id>.execute-api.us-east-1.amazonaws.com/test/health` |

No añadas literalmente `$default` a la ruta. La URL de `test` **sí** incluye `/test`. Copia siempre el **Invoke URL** desde el stage correcto, puesto que un stage puede no contener la misma versión desplegada que otro.

### 9.5. Probar el API Gateway

**Prueba 1: navegador (solo `GET /health`)**

Copia la URL de `$default` y añade `/health`. Si `GET /health` existe y Lambda lo implementa, debe devolver una respuesta 200 como `{"status":"ok"}`. Si da 404, revisa stage, método y ruta.

**Prueba 2: PowerShell (Windows)**

```powershell
$BASE_URL = "https://<api-id>.execute-api.us-east-1.amazonaws.com"
Invoke-RestMethod -Method Get -Uri "$BASE_URL/health"

$body = @{ image_key = "statue_small.jpg" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "$BASE_URL/process" -ContentType "application/json" -Body $body
```

Sustituye `<api-id>` por tu API ID. Si pruebas el stage `test`, establece `$BASE_URL` añadiendo `/test` al final. El `POST` funcionará **solo si** el código Lambda admite la entrada HTTP indicada y la imagen ya se ha subido a S3. El contenido concreto de la respuesta dependerá del handler.

**Prueba 3: cURL (terminal con curl real)**

```bash
curl -i "https://<api-id>.execute-api.us-east-1.amazonaws.com/health"
curl -i -X POST "https://<api-id>.execute-api.us-east-1.amazonaws.com/process" \
  -H "Content-Type: application/json" \
  -d '{"image_key":"statue_small.jpg"}'
```

En PowerShell, usa `curl.exe` en lugar del alias `curl` si quieres el comportamiento real de cURL; alternativamente, usa `Invoke-RestMethod` como arriba.

### 9.6. Comprobar si la integración funciona de extremo a extremo

1. En **API Gateway → Develop → Routes**, comprueba que `GET /health` y `POST /process` están definidos para la HTTP API.
2. En **Integrations**, comprueba que apuntan a **ImageProcessingFunction** y que la Lambda tiene permiso de invocación desde API Gateway.
3. Abre **Lambda → Monitor → View CloudWatch logs** y examina `/aws/lambda/ImageProcessingFunction` para identificar excepciones, problemas de permisos o campos de entrada incorrectos.
4. Tras un `POST /process` exitoso, revisa **DynamoDB → Tables → ImageMetadata → Explore items** y el bucket de salida correspondiente. **Ojo:** en esta versión del ejercicio la generación real de thumbnails con Pillow puede estar desactivada; no asumas que aparecerá un archivo thumbnail.
5. Si el código HTTP usa un flujo diferente del SQS, comprueba **qué recursos modifica realmente**. No confundas «API respondió 200» con «procesamiento y persistencia completados».

### 9.7. Problemas habituales

| Síntoma | Causa probable | Acción recomendada |
|---|---|---|
| Stages `$default` y `test` deshabilitados en el diálogo **Deploy API** | **Auto-deploy enabled** | Cierra el diálogo y usa el Invoke URL; o desactiva Auto-deploy para desplegar manualmente |
| `404 Not Found` | Método/ruta o prefijo de stage incorrecto | Comprueba Routes y si `/test` debe preceder a `/health` o `/process` |
| `500 Internal Server Error` | Error de código, excepción o fallo de integración | Examina CloudWatch y comprueba el formato del evento HTTP |
| `500` con error de permisos de invocación | API Gateway no está autorizado a invocar Lambda | Revisa **Integrations → Invoke permissions** y la política de recursos de Lambda |
| `502 Bad Gateway` | Lambda lanza error o devuelve una respuesta incompatible con la integración | Revisa logs y `statusCode`/`body` en la respuesta del handler |
| `403 Forbidden` | Autorización, política o URL de invocación incorrecta | Revisa Authorization, permisos y URL |
| `POST /process` falla aunque SQS funciona | Lambda solo implementa formato SQS | Añade tratamiento de eventos HTTP API v2 y vuelve a desplegar |
| `TimeoutError` / `ConnectionClosedError` al ejecutar `configure_lambda.py` | Timeout al subir el paquete de despliegue | Comprueba si la función ya existe; utiliza ZIP en S3 y actualiza el código desde allí |
| `labrole-arn is from account X but your .env credentials are for account Y` | El ARN de LabRole guardado es de una sesión o cuenta anterior | Ejecuta `python setup_scripts/get_LabRole_arn.py` y repite |
| `FileNotFoundError: lambda_function.zip` | Versión antigua de `configure_lambda.py` | Actualiza el script: ahora genera el ZIP en memoria |
| `TableName=None` al crear DynamoDB | Falta `dynamodb-table` en `aws_resources.db` | Usa `db.get("dynamodb-table") or "ImageMetadata"` y guarda el nombre en el shelve |
| `sts:AssumeRole AccessDenied` | Restricción IAM de Learner Lab | Usa el rol y los permisos autorizados por el laboratorio; no intentes eludir la restricción |

**Seguridad:** para esta práctica se puede configurar temporalmente un endpoint sin autenticación **solo para pruebas y con datos no sensibles**, si la política de Learner Lab lo permite. Evita dejar público un endpoint de procesamiento que pueda consumir recursos o generar costes. Para despliegues reales, añade autenticación/autorización y controles de uso.

### 9.8. Referencias oficiales de AWS

- [Crear una HTTP API en AWS Console](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-develop.html)
- [Stages y despliegues automáticos de HTTP APIs](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-stages.html)
- [Permisos de API Gateway para invocar Lambda](https://docs.aws.amazon.com/lambda/latest/dg/services-apigateway.html)

---

## **Solución de Problemas**

1. **Mensajes en SQS no procesados**:
   - Asegúrate de que Lambda tiene configurado el trigger de SQS.

2. **Thumbnails no generados**:
   - Verifica los logs de Lambda para errores.

3. **No se muestran imágenes en la página web**:
   - Asegúrate de que el hosting estático está habilitado.
   - Confirma que los thumbnails están subidos al bucket.

---

## **Licencia**
Este proyecto está bajo la licencia MIT. Consulta el archivo `LICENSE` para más detalles.
