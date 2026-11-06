import os
import boto3
import uuid, time
import shelve
from dotenv import load_dotenv

load_dotenv()  # loads .env into environment

# simplest: rely on boto3's default provider chain (reads the env vars above)
s3 = boto3.client(
     "s3",
     aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
     aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
     aws_session_token=os.getenv("AWS_SESSION_TOKEN"),  # may be None if not set
     region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
)

from botocore.exceptions import ClientError


def recorded_buckets_exist():
    """Reuse the buckets from a previous run instead of creating new ones (avoids orphan buckets)."""
    with shelve.open("aws_resources.db") as db:
        names = [db.get("images-bucket"), db.get("thumbnails-bucket")]
    if not all(names):
        return False
    try:
        for name in names:
            s3.head_bucket(Bucket=name)
    except ClientError:
        return False  # recorded but gone (e.g. deleted or new lab account): create new ones
    print(f"Buckets already exist, reusing them: {names}")
    return True


if recorded_buckets_exist():
    raise SystemExit(0)

base_names = [
    "image-uploads-bucket",
    "image-thumbnails-bucket",
]

suffix = f"{time.strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}"
buckets = [f"{base}-{suffix}" for base in base_names]
print(buckets)

# Create the buckets
for bucket in buckets:
    # NOTE: If you're NOT in us-east-1, you should pass CreateBucketConfiguration with the region.
    s3.create_bucket(Bucket=bucket)
    print(f"Bucket {bucket} creado.")

# Map them to your desired shelve keys
images_bucket, thumbnails_bucket = buckets[0], buckets[1]

# Persist to a local shelve file
with shelve.open("aws_resources.db") as db:
    db["images-bucket"] = images_bucket
    db["thumbnails-bucket"] = thumbnails_bucket  # intentional spelling per request

print("Saved to shelve: images-bucket =", images_bucket, "; thumbnails-bucket =", thumbnails_bucket)
