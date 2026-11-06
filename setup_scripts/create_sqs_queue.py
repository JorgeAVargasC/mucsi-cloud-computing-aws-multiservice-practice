import os
import boto3
import shelve
from dotenv import load_dotenv

load_dotenv()  # loads .env into environment

# Use env vars if present; otherwise boto3's default chain
sqs = boto3.client(
    "sqs",
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    aws_session_token=os.getenv("AWS_SESSION_TOKEN"),  # may be None if not set
    region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
)

response = sqs.create_queue(QueueName="image-processing-queue")
queue_url = response["QueueUrl"]
print(f"Queue URL: {queue_url}")

# Persist the queue URL into a local shelve
with shelve.open("aws_resources.db") as db:
    db["messages-queue"] = queue_url

print("Saved to shelve: messages-queue =", queue_url)

