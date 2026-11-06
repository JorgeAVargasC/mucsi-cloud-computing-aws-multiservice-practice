import os
import boto3
import shelve
from botocore.exceptions import ClientError
from dotenv import load_dotenv

load_dotenv()

dynamodb = boto3.client(
    "dynamodb",
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    aws_session_token=os.getenv("AWS_SESSION_TOKEN"),  # may be None
    region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
)

TABLE_NAME = "ImageMetadata"
# --- Read values from shelve ---

with shelve.open("aws_resources.db") as db:
    TABLE_NAME = db.get("dynamodb-table") or TABLE_NAME
    db["dynamodb-table"] = TABLE_NAME

def ensure_table():
    """
    Create the table if it doesn't exist.
    If it already exists, just proceed.
    Always return the table description once it's ACTIVE.
    """
    try:
        # Try to create (first run)
        resp = dynamodb.create_table(
            TableName=TABLE_NAME,
            KeySchema=[{"AttributeName": "ImageID", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "ImageID", "AttributeType": "S"}],
            ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
        )
        print(f"Creating table {TABLE_NAME}…")
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code")
        if code == "ResourceInUseException":
            # Table already exists, continue
            print(f"Table {TABLE_NAME} already exists. Continuing…")
        else:
            raise  # Unexpected error

    # Wait until the table exists/active (covers both create and already-exists)
    dynamodb.get_waiter("table_exists").wait(TableName=TABLE_NAME)

    # Fetch final description
    desc = dynamodb.describe_table(TableName=TABLE_NAME)["Table"]
    status = desc.get("TableStatus")
    print(f"Table {TABLE_NAME} status: {status}")

    # (Optional) If you want to guarantee ACTIVE:
    if status != "ACTIVE":
        # Rare, but you can loop/wait a bit more if needed
        dynamodb.get_waiter("table_exists").wait(TableName=TABLE_NAME)
        desc = dynamodb.describe_table(TableName=TABLE_NAME)["Table"]

    return desc

def store_in_shelve(desc):
    arn = desc["TableArn"]
    with shelve.open("aws_resources.db") as db:
        db["dynamodb-table"] = TABLE_NAME
        db["dynamodb-table-arn"] = arn
    print(f"Saved to shelve: dynamodb-table={TABLE_NAME}, dynamodb-table-arn={arn}")

if __name__ == "__main__":
    table_desc = ensure_table()
    print("Tabla DynamoDB disponible:", table_desc)
    store_in_shelve(table_desc)
