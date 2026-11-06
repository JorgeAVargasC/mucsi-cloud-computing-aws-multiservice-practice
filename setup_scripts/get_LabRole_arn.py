import os
import shelve
import boto3
from dotenv import load_dotenv

load_dotenv()  # use the Learner Lab credentials from .env, like the other scripts

role_name = "LabRole"
sts = boto3.client(
    "sts",
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    aws_session_token=os.getenv("AWS_SESSION_TOKEN"),
    region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
)
ident = sts.get_caller_identity()

account_id = ident["Account"]
partition  = ident["Arn"].split(":")[1]   # e.g., "aws", "aws-us-gov", "aws-cn"
labrole_arn = f"arn:{partition}:iam::{account_id}:role/{role_name}"

# Store in shelve
with shelve.open("aws_resources.db") as db:
    db["labrole-arn"] = labrole_arn

print("Account:", account_id)
print("LabRole ARN:", labrole_arn)
print("Saved to shelve key 'labrole-arn'.")
