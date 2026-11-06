import os
import json
import shelve
import boto3
from dotenv import load_dotenv

class ImageUploader:
    def __init__(self, s3_client, sqs_client, queue_url):
        self.s3_client = s3_client
        self.sqs_client = sqs_client
        self.queue_url = queue_url  # pulled from shelve

    def upload_file_to_bucket(self, bucket_name, local_path, s3_key):
        """Sube un archivo local a un bucket S3."""
        try:
            self.s3_client.upload_file(local_path, bucket_name, s3_key)
            print(f"Archivo {local_path} subido a s3://{bucket_name}/{s3_key}")
        except Exception as e:
            raise Exception(f"Error al subir el archivo {local_path}: {e}")

    def send_message_to_sqs(self, message_dict):
        """Envía un mensaje JSON a la cola SQS (URL desde shelve)."""
        try:
            response = self.sqs_client.send_message(
                QueueUrl=self.queue_url,
                MessageBody=json.dumps(message_dict)
            )
            print(f"Mensaje enviado a SQS: {response['MessageId']}")
        except Exception as e:
            raise Exception(f"Error al enviar mensaje a SQS: {e}")

    def upload_folder_images(self, bucket_name, path):
        """Sube todas las imágenes de una carpeta a S3 y envía mensajes a SQS."""
        try:
            entries = os.listdir(path)
        except FileNotFoundError:
            raise RuntimeError(f"La carpeta local no existe: {path}")

        for file in entries:
            if file.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                try:
                    local_path = os.path.join(path, file)
                    s3_key = file

                    # 1) Subir archivo al bucket
                    self.upload_file_to_bucket(bucket_name, local_path, s3_key)

                    # 2) Enviar mensaje para procesamiento (coincide con tu Lambda: bucket_name + image_key)
                    message = {
                        "bucket_name": bucket_name,
                        "image_key": s3_key
                    }
                    self.send_message_to_sqs(message)

                except Exception as e:
                    print(f"Error al procesar la imagen {file}: {e}")


if __name__ == "__main__":
    # Cargar variables de entorno (opcional)
    load_dotenv()

    # --- Recuperar recursos desde shelve ---
    with shelve.open("aws_resources.db", flag="r") as db:
        queue_url = db.get("messages-queue")       # SQS QueueUrl
        images_bucket = db.get("images-bucket")    # S3 bucket para uploads

    if not queue_url:
        raise RuntimeError("Falta 'messages-queue' (QueueUrl) en aws_resources.db.")
    if not images_bucket:
        raise RuntimeError("Falta 'images-bucket' (nombre del bucket) en aws_resources.db.")

    # --- Clientes AWS (boto3) ---
    s3_client = boto3.client(
        "s3",
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        aws_session_token=os.getenv("AWS_SESSION_TOKEN"),
        region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
    )
    sqs_client = boto3.client(
        "sqs",
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        aws_session_token=os.getenv("AWS_SESSION_TOKEN"),
        region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
    )

    # Instanciar uploader con QueueUrl desde shelve
    uploader = ImageUploader(s3_client, sqs_client, queue_url)

    # Carpeta local y bucket desde shelve
    local_folder = "img"
    bucket_name = images_bucket

    # Subir imágenes y enviar mensajes
    uploader.upload_folder_images(bucket_name, local_folder)



"""
import os
import json
import boto3
from dotenv import load_dotenv

class ImageUploader:
    def __init__(self, s3_client, sqs_client, queue_name):
        self.s3_client = s3_client
        self.sqs_client = sqs_client
        self.queue_name = queue_name

    def upload_file_to_bucket(self, bucket_name, local_path, s3_key):
        
        try:
            self.s3_client.upload_file(local_path, bucket_name, s3_key)
            print(f"Archivo {local_path} subido a {bucket_name}/{s3_key}")
        except Exception as e:
            raise Exception(f"Error al subir el archivo {local_path}: {e}")

    def send_message_to_sqs(self, message, queue_name):
        #        Enviar un mensaje a la cola SQS.
        try:
            response = self.sqs_client.send_message(
                QueueUrl=f"https://sqs.us-east-1.amazonaws.com/590183788851/image-processing-queue", # recuperar como variable de entorno
                MessageBody=message
            )
            print(f"Mensaje enviado a SQS: {response['MessageId']}")
        except Exception as e:
            raise Exception(f"Error al enviar mensaje a SQS: {e}")

    def upload_folder_images(self, bucket_name, path):
        #        Subir todas las imágenes de una carpeta a S3 y enviar mensajes a SQS.
        files = os.listdir(path)

        for file in files:
            if file.lower().endswith(('.jpg', '.png', '.jpeg')):
                try:
                    local_path = os.path.join(path, file)
                    s3_key = file

                    # Subir archivo al bucket
                    self.upload_file_to_bucket(bucket_name, local_path, s3_key)

                    # Crear el mensaje JSON para SQS
                    message = {
                        'bucket': bucket_name,
                        'file_path': s3_key
                    }
                    json_message = json.dumps(message)

                    # Enviar mensaje a la cola SQS
                    self.send_message_to_sqs(json_message, self.queue_name)

                except Exception as e:
                    print(f"Error al procesar la imagen {file}: {e}")


if __name__ == "__main__":
    # Inicializar clientes de AWS
    load_dotenv()  # loads .env into environment

    # simplest: rely on boto3's default provider chain (reads the env vars above)
    s3_client = boto3.client(
        "s3",
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        aws_session_token=os.getenv("AWS_SESSION_TOKEN"),  # may be None if not set
        region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
    )

    sqs_client = boto3.client(
        'sqs',
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        aws_session_token=os.getenv("AWS_SESSION_TOKEN"),  # may be None if not set
        region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
    )

    # Instanciar el uploader con la cola SQS especificada
    uploader = ImageUploader(s3_client, sqs_client, 'upload_images')

    # Ruta local de las imágenes y nombre del bucket
    local_folder = "img"
    bucket_name = "image-uploads-bucket-20251017-96dbb68e" # cambia con tu nombre de bucket que se puede recuperar con aws s3 ls

    # Subir imágenes desde la carpeta local
    uploader.upload_folder_images(bucket_name, local_folder)
"""