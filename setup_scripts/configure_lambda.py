import io
import os
import time
import shelve
import zipfile
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
    SOURCE_BUCKET = db.get("images-bucket")
    TABLE_NAME = db.get("dynamodb-table") or "ImageMetadata"

if not ROLE_ARN:
    raise RuntimeError("Missing 'labrole-arn' in aws_resources.db (run get_LabRole_arn.py)")
if not THUMB_BUCKET or not SOURCE_BUCKET:
    raise RuntimeError("Missing buckets in aws_resources.db (run create_s3_buckets.py)")

# Variables the Lambda code reads (see lambda_function/lambda_function.py)
LAMBDA_ENV = {
    "THUMB_BUCKET": THUMB_BUCKET,
    "SOURCE_BUCKET": SOURCE_BUCKET,
    "TABLE_NAME": TABLE_NAME,
}

lambda_client = boto3.client(
    "lambda",
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    aws_session_token=os.getenv("AWS_SESSION_TOKEN"),
    region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
)

# The ZIP only needs lambda_function.py: boto3 is already included in the Lambda
# runtime. It is built here with zipfile, so the `zip` command (missing in Git Bash
# on Windows) is not needed.
LAMBDA_SOURCE = os.path.join(os.path.dirname(__file__), "..", "lambda_function", "lambda_function.py")


def build_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(LAMBDA_SOURCE, arcname="lambda_function.py")
    return buf.getvalue()


LAMBDA_CODE = build_zip()


def check_role_account():
    """LabRole must belong to the same account as the current credentials."""
    sts = boto3.client(
        "sts",
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        aws_session_token=os.getenv("AWS_SESSION_TOKEN"),
        region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
    )
    account = sts.get_caller_identity()["Account"]
    role_account = ROLE_ARN.split(":")[4]
    if account != role_account:
        raise RuntimeError(
            f"labrole-arn is from account {role_account} but your .env credentials are "
            f"for account {account}. Run: python setup_scripts/get_LabRole_arn.py"
        )

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
        Environment={"Variables": LAMBDA_ENV},
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

    # 2) Update configuration (including env vars)
    print(f"Updating configuration for {FUNCTION_NAME} …")
    # Merge any existing env vars:
    cfg = lambda_client.get_function_configuration(FunctionName=FUNCTION_NAME)
    env_vars = dict(cfg.get("Environment", {}).get("Variables", {}))
    env_vars.update(LAMBDA_ENV)

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

check_role_account()
print(f"Lambda package built ({len(LAMBDA_CODE)} bytes)")

# Record the function so remove_aws_resources.py knows it belongs to this project.
with shelve.open("aws_resources.db") as db:
    db["lambda-function"] = FUNCTION_NAME

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

