import os
import json
import shelve
import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

load_dotenv()  # carga .env en el entorno

# 1) Recuperar el nombre del bucket de thumbnails desde la shelve
with shelve.open("aws_resources.db", flag="r") as db:
    bucket_name = db.get("thumbnails-bucket")

if not bucket_name:
    raise RuntimeError("No se encontró 'thumbnails-bucket' en aws_resources.db.")

# 2) Cliente S3
s3 = boto3.client(
    "s3",
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    aws_session_token=os.getenv("AWS_SESSION_TOKEN"),  # puede ser None
    region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
)

# 3) DESACTIVAR Block Public Access a nivel de bucket
s3.put_public_access_block(
    Bucket=bucket_name,
    PublicAccessBlockConfiguration={
        "BlockPublicAcls": False,
        "IgnorePublicAcls": False,
        "BlockPublicPolicy": False,
        "RestrictPublicBuckets": False,
    },
)

# 4) Establecer bucket policy:
#    - PublicReadObjects: s3:GetObject para todo el bucket
#    - PublicListThumbsPrefix: s3:ListBucket SOLO cuando se lista el prefijo thumbnails/
desired_policy = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "PublicReadObjects",
            "Effect": "Allow",
            "Principal": "*",
            "Action": ["s3:GetObject"],
            "Resource": f"arn:aws:s3:::{bucket_name}/*"
        },
        {
            "Sid": "PublicListThumbsPrefix",
            "Effect": "Allow",
            "Principal": "*",
            "Action": ["s3:ListBucket"],
            "Resource": f"arn:aws:s3:::{bucket_name}",
            "Condition": {
                "StringLike": {
                    "s3:prefix": ["thumbnails/*", "thumbnails/"]
                }
            }
        }
    ]
}

try:
    s3.put_bucket_policy(Bucket=bucket_name, Policy=json.dumps(desired_policy))
    print("Bucket policy aplicada: lectura pública y listado limitado a thumbnails/.")
except ClientError as e:
    print(f"Aviso: no se pudo establecer bucket policy pública ({e}).")

# 5) Subir el index.html con el content-type correcto
s3.upload_file(
    Filename="s3_static_website/index.html",
    Bucket=bucket_name,
    Key="index.html",
    ExtraArgs={"ContentType": "text/html"}
)

# 6) Configurar el hosting estático del bucket
s3.put_bucket_website(
    Bucket=bucket_name,
    WebsiteConfiguration={
        "IndexDocument": {"Suffix": "index.html"}
    }
)

# 7) Informar URLs
region = s3.meta.region_name or "us-east-1"
print(f"Página web subida a s3://{bucket_name}/index.html")
print(f"Website (HTTP):  http://{bucket_name}.s3-website-{region}.amazonaws.com/")
print(f"Objeto (HTTPS):  https://{bucket_name}.s3.amazonaws.com/index.html")
