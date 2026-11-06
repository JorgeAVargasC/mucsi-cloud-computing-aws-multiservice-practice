import os
import time
import shelve
import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

class SqsTriggerConfigurator:
    def __init__(self, queue_arn):
        self.queue_arn = queue_arn

    def add_or_update_sqs_trigger(self, client, function_name, batch_size=3, enabled=True):
        """
        Create the event source mapping if missing; otherwise FORCE an update of all
        existing mappings for (queue_arn, function_name). Retries on in-progress updates.
        """
        # 1) Find existing mappings for this queue + function
        existing = client.list_event_source_mappings(
            FunctionName=function_name,
            EventSourceArn=self.queue_arn
        ).get("EventSourceMappings", [])

        if not existing:
            # 2) Create mapping if none exists
            try:
                resp = client.create_event_source_mapping(
                    EventSourceArn=self.queue_arn,
                    FunctionName=function_name,
                    Enabled=enabled,
                    BatchSize=batch_size
                )
                print(f"Cola SQS configurada como trigger para '{function_name}'.")
                print(f"Event Source Mapping ID: {resp['UUID']}")
                return
            except client.exceptions.ResourceConflictException:
                # Very rare race: mapping created between list and create — fall through to update path
                existing = client.list_event_source_mappings(
                    FunctionName=function_name,
                    EventSourceArn=self.queue_arn
                ).get("EventSourceMappings", [])
            except Exception as e:
                print(f"Error al crear el trigger para '{function_name}': {e}")
                return

        # 3) FORCE update on all existing mappings
        for mapping in existing:
            uuid = mapping["UUID"]
            print(f"Forzando actualización del trigger UUID: {uuid} para '{function_name}'…")
            while True:
                try:
                    resp = client.update_event_source_mapping(
                        UUID=uuid,
                        Enabled=enabled,
                        BatchSize=batch_size
                    )
                    print(f"Trigger actualizado (UUID: {uuid}) para '{function_name}'.")
                    break
                except client.exceptions.ResourceConflictException:
                    # Otro update en curso; espera y reintenta
                    time.sleep(2)
                except Exception as e:
                    print(f"Error al actualizar el trigger (UUID: {uuid}) para '{function_name}': {e}")
                    break


def resolve_queue_arn_from_shelve():
    """
    Lee 'messages-queue' (URL) o 'messages-queue-arn' de aws_resources.db.
    Si sólo hay URL, consulta SQS para obtener su ARN.
    """
    with shelve.open("aws_resources.db", flag="r") as db:
        queue_arn = db.get("messages-queue-arn")
        queue_url = db.get("messages-queue")

    if queue_arn:
        return queue_arn

    if not queue_url:
        raise RuntimeError(
            "No se encontró 'messages-queue' (URL) ni 'messages-queue-arn' en aws_resources.db."
        )

    sqs = boto3.client(
        "sqs",
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        aws_session_token=os.getenv("AWS_SESSION_TOKEN"),
        region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
    )
    attrs = sqs.get_queue_attributes(
        QueueUrl=queue_url,
        AttributeNames=["QueueArn"]
    )["Attributes"]
    return attrs["QueueArn"]


if __name__ == "__main__":
    load_dotenv()

    queue_arn = resolve_queue_arn_from_shelve()

    lambda_client = boto3.client(
        "lambda",
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        aws_session_token=os.getenv("AWS_SESSION_TOKEN"),
        region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
    )

    function_name = "ImageProcessingFunction"

    configurator = SqsTriggerConfigurator(queue_arn)
    configurator.add_or_update_sqs_trigger(
        lambda_client,
        function_name,
        batch_size=3,
        enabled=True
    )


"""
import os
import boto3
from dotenv import load_dotenv

class SqsTriggerConfigurator:
    def __init__(self, queue_arn):
        self.queue_arn = queue_arn

    def add_sqs_trigger_to_lambda(self, client, function_name):
        try:
            # Configurar el trigger SQS para Lambda
            response = client.create_event_source_mapping(
                EventSourceArn=self.queue_arn,  # ARN de la cola SQS
                FunctionName=function_name,    # Nombre de la función Lambda
                Enabled=True,                  # Habilitar el trigger
                BatchSize=3                    # Cantidad de mensajes por lote
            )
            print(f"Cola SQS configurada como trigger para la función Lambda '{function_name}'.")
            print(f"Event Source Mapping ID: {response['UUID']}")
        except client.exceptions.ResourceConflictException:
            print(f"El trigger ya existe para la función Lambda '{function_name}'.")
        except Exception as e:
            print(f"Error al configurar el trigger para la función Lambda '{function_name}': {e}")

if __name__ == "__main__":
    # ARN de la cola SQS
    queue_arn = "arn:aws:sqs:us-east-1:590183788851:image-processing-queue"  # Sustituye con tu ARN de cola

    # Cliente de Lambda
    load_dotenv()  # loads .env into environment
    # simplest: rely on boto3's default provider chain (reads the env vars above)
    lambda_client = boto3.client(
        "lambda",
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        aws_session_token=os.getenv("AWS_SESSION_TOKEN"),  # may be None if not set
        region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
    )

    # Nombre de la función Lambda
    function_name = "ImageProcessingFunction"

    # Configurar el trigger
    configurator = SqsTriggerConfigurator(queue_arn)
    configurator.add_sqs_trigger_to_lambda(lambda_client, function_name)
"""