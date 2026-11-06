#!/usr/bin/env python3
"""
Deploy the whole project end to end, running the setup scripts in README order:

   1. get_LabRole_arn.py        LabRole ARN of the current lab account
   2. create_s3_buckets.py      images + thumbnails buckets
   3. create_sqs_queue.py       image-processing-queue
   4. create_dynamodb_table.py  ImageMetadata
   5. configure_lambda.py       ImageProcessingFunction (code + env vars)
   6. add_sqs_trigger.py        SQS -> Lambda trigger
   7. create_api_gateway.py     HTTP API (GET /health, POST /process)
   8. deploy_static_site.py     index.html + static hosting on the thumbnails bucket
   9. upload_folder_images.py   uploads img/ and sends one SQS message per image
  then waits for the Lambda to process the images and tests the API.

Every step can be re-run safely: if something fails (e.g. expired credentials),
fix it and run this script again; existing resources are reused.

Usage:
    python deploy_all.py               # full deployment
    python deploy_all.py --skip-images # don't upload img/ nor wait for processing
    python deploy_all.py --skip-test   # don't call the API at the end
Clean up afterwards with:  python remove_aws_resources.py --really-delete
"""
import argparse
import os
import shelve
import subprocess
import sys
import time

import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.abspath(__file__))
SETUP = os.path.join(ROOT, "setup_scripts")
IMG_DIR = os.path.join(ROOT, "img")
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp")


def banner(text):
    print(f"\n{'=' * 70}\n{text}\n{'=' * 70}", flush=True)


def check_credentials():
    """Fail fast with a clear message instead of a traceback in step 1."""
    if not os.path.exists(os.path.join(ROOT, ".env")):
        sys.exit("No .env file. Copy .env.example to .env and paste the Learner Lab credentials "
                 "(AWS Details -> AWS CLI).")
    load_dotenv(os.path.join(ROOT, ".env"), override=True)
    try:
        ident = boto3.client("sts").get_caller_identity()
    except (ClientError, NoCredentialsError) as e:
        sys.exit(f"The credentials in .env don't work ({e}).\n"
                 "If the lab session expired, start the lab again and copy the new credentials into .env.")
    print(f"AWS account {ident['Account']} ({ident['Arn']})")


def run(script, *args):
    banner(f"> {script} {' '.join(args)}".rstrip())
    result = subprocess.run([sys.executable, os.path.join(SETUP, script), *args], cwd=ROOT)
    if result.returncode != 0:
        sys.exit(f"\nStep '{script}' failed (exit code {result.returncode}). "
                 "Fix the error above and run deploy_all.py again: completed steps reuse what exists.")


def wait_for_processing(expected, timeout=120):
    """SQS -> Lambda is asynchronous: poll DynamoDB until every uploaded image has metadata."""
    banner(f"> Waiting for the Lambda to process {expected} image(s) (max {timeout}s)")
    with shelve.open(os.path.join(ROOT, "aws_resources.db"), flag="r") as db:
        table = db.get("dynamodb-table") or "ImageMetadata"
    ddb = boto3.client("dynamodb", region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"))
    deadline = time.time() + timeout
    count = 0
    while time.time() < deadline:
        count = ddb.scan(TableName=table, Select="COUNT")["Count"]
        print(f"  {count}/{expected} items in {table}", flush=True)
        if count >= expected:
            return True
        time.sleep(5)
    print("  Timed out. Check the Lambda logs in CloudWatch: /aws/lambda/ImageProcessingFunction")
    return False


def summary(processed_ok, test_ok):
    with shelve.open(os.path.join(ROOT, "aws_resources.db"), flag="r") as db:
        rec = dict(db)
    region = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
    thumbs = rec.get("thumbnails-bucket")
    banner("Deployment finished")
    print(f"  Images bucket:     {rec.get('images-bucket')}")
    print(f"  Thumbnails bucket: {thumbs}")
    print(f"  SQS queue:         {rec.get('messages-queue')}")
    print(f"  DynamoDB table:    {rec.get('dynamodb-table')}")
    print(f"  Lambda:            {rec.get('lambda-function', 'ImageProcessingFunction')}")
    print(f"  API:               {rec.get('api-endpoint')}  (GET /health, POST /process)")
    print(f"  Website:           https://{thumbs}.s3.amazonaws.com/index.html")
    print(f"                     http://{thumbs}.s3-website-{region}.amazonaws.com/")
    if processed_ok is not None:
        print(f"  Image processing:  {'OK' if processed_ok else 'NOT CONFIRMED (see above)'}")
    if test_ok is not None:
        print(f"  API test:          {'OK' if test_ok else 'FAILED (see above)'}")
    print("\nTo delete everything: python remove_aws_resources.py --really-delete")


def main():
    ap = argparse.ArgumentParser(description="Deploy the whole AWS image-processing project.")
    ap.add_argument("--skip-images", action="store_true", help="Don't upload img/ nor wait for processing.")
    ap.add_argument("--skip-test", action="store_true", help="Don't test the API at the end.")
    args = ap.parse_args()

    check_credentials()

    for script in ("get_LabRole_arn.py",
                   "create_s3_buckets.py",
                   "create_sqs_queue.py",
                   "create_dynamodb_table.py",
                   "configure_lambda.py",
                   "add_sqs_trigger.py",
                   "create_api_gateway.py",
                   "deploy_static_site.py"):
        run(script)

    processed_ok = None
    if not args.skip_images:
        images = [f for f in os.listdir(IMG_DIR) if f.lower().endswith(IMAGE_EXT)]
        run("upload_folder_images.py")
        processed_ok = wait_for_processing(len(images))

    test_ok = None
    if not args.skip_test:
        # The default test image only exists in the bucket if img/ was uploaded.
        banner("> test_api_gateway.py")
        test_ok = subprocess.run([sys.executable, os.path.join(SETUP, "test_api_gateway.py")],
                                 cwd=ROOT).returncode == 0

    summary(processed_ok, test_ok)
    sys.exit(0 if processed_ok is not False and test_ok is not False else 1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nAborted by user.")
