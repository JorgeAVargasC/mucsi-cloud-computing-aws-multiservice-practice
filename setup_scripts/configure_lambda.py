import os
import time
import shelve
import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

load_dotenv()

FUNCTION_NAME = "ImageProcessingFunction"
RUNTIME = "python3.12"                     # use a supported runtime
HANDLER = "lambda_function.lambda_handler"
TIMEOUT = 15
MEMORY = 128

# --- Read values from shelve ---
with shelve.open("aws_resources.db", flag="r") as db:
    ROLE_ARN = db.get("labrole-arn")
    THUMB_BUCKET = db.get("thumbnails-bucket")

if not ROLE_ARN:
    raise RuntimeError("Missing 'labrole-arn' in aws_resources.db")
if not THUMB_BUCKET:
    raise RuntimeError("Missing 'thumbnails-bucket' in aws_resources.db")

lambda_client = boto3.client(
    "lambda",
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    aws_session_token=os.getenv("AWS_SESSION_TOKEN"),
    region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
)

with open("lambda_function/lambda_function.zip", "rb") as f:
    LAMBDA_CODE = f.read()

def wait_until_ready(name, timeout=300, poll=3):
    """Wait until the function is Active and last update is Successful."""
    deadline = time.time() + timeout
    while True:
        cfg = lambda_client.get_function_configuration(FunctionName=name)
        state = cfg.get("State")
        update = cfg.get("LastUpdateStatus")
        if state == "Active" and update == "Successful":
            return
        if update == "Failed":
            reason = cfg.get("LastUpdateStatusReason", "Unknown")
            raise RuntimeError(f"Lambda update failed: {reason}")
        if time.time() > deadline:
            raise TimeoutError(f"Timed out waiting for {name} to become Active/Successful (state={state}, lastUpdate={update}).")
        time.sleep(poll)

def create():
    print(f"Creating Lambda {FUNCTION_NAME} …")
    resp = lambda_client.create_function(
        FunctionName=FUNCTION_NAME,
        Runtime=RUNTIME,
        Role=ROLE_ARN,
        Handler=HANDLER,
        Code={"ZipFile": LAMBDA_CODE},
        Timeout=TIMEOUT,
        MemorySize=MEMORY,
        Environment={"Variables": {"THUMB_BUCKET": THUMB_BUCKET}},
        Publish=True,
    )
    # Wait until it's ready before returning
    wait_until_ready(FUNCTION_NAME)
    return resp

def overwrite():
    # 1) Update code
    print(f"Function exists. Updating code for {FUNCTION_NAME} …")
    while True:
        try:
            lambda_client.update_function_code(
                FunctionName=FUNCTION_NAME,
                ZipFile=LAMBDA_CODE,
                Publish=True,
            )
            break
        except lambda_client.exceptions.ResourceConflictException:
            # Another update in progress: wait and retry
            time.sleep(3)
    wait_until_ready(FUNCTION_NAME)

    # 2) Update configuration (including env var THUMB_BUCKET)
    print(f"Updating configuration for {FUNCTION_NAME} …")
    # Merge any existing env vars:
    cfg = lambda_client.get_function_configuration(FunctionName=FUNCTION_NAME)
    env_vars = dict(cfg.get("Environment", {}).get("Variables", {}))
    env_vars["THUMB_BUCKET"] = THUMB_BUCKET

    while True:
        try:
            resp = lambda_client.update_function_configuration(
                FunctionName=FUNCTION_NAME,
                Role=ROLE_ARN,
                Runtime=RUNTIME,
                Handler=HANDLER,
                Timeout=TIMEOUT,
                MemorySize=MEMORY,
                Environment={"Variables": env_vars},
            )
            break
        except lambda_client.exceptions.ResourceConflictException:
            time.sleep(3)
    wait_until_ready(FUNCTION_NAME)
    return resp

try:
    resp = create()
    print("Lambda function created:", resp)
except lambda_client.exceptions.ResourceConflictException:
    # Function already exists → overwrite
    resp = overwrite()
    print("Lambda function overwritten (updated):", resp)
except ClientError as e:
    code = e.response.get("Error", {}).get("Code")
    if code == "ResourceConflictException":
        resp = overwrite()
        print("Lambda function overwritten (updated):", resp)
    else:
        raise

"""
import os
import boto3
from dotenv import load_dotenv

load_dotenv()  # loads .env into environment

# simplest: rely on boto3's default provider chain (reads the env vars above)
lambda_client = boto3.client(
     "lambda",
     aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
     aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
     aws_session_token=os.getenv("AWS_SESSION_TOKEN"),  # may be None if not set
     region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
)

with open('lambda_function/lambda_function.zip', 'rb') as f:
    lambda_code = f.read()

response = lambda_client.create_function(
    FunctionName='ImageProcessingFunction',
    Runtime='python3.8',
    Role='arn:aws:iam::590183788851:role/LabRole',
    Handler='lambda_function.lambda_handler',
    Code={'ZipFile': lambda_code},
    Timeout=15,
    MemorySize=128
)

print("Función Lambda creada:", response)
"""