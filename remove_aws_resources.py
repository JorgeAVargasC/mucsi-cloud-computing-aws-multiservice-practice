#!/usr/bin/env python3
"""
Delete ONLY the AWS resources this project created, as recorded in aws_resources.db.

Nothing is listed or searched in the account: if a resource is not in the shelve, it is
not touched. Order (dependents first):
  1. HTTP API (API Gateway) + its invoke permission on the Lambda   key: api-id
  2. SQS -> Lambda trigger (event source mappings) + Lambda          key: lambda-function
  3. SQS queue                                                      key: messages-queue
  4. DynamoDB table                                                 key: dynamodb-table
  5. S3 buckets (emptied first)                                     keys: images-bucket, thumbnails-bucket

DRY RUN by default. Use --really-delete to delete. Deleted (or already missing) resources
are removed from aws_resources.db, so running it again only retries what failed.
"""
import argparse
import os
import shelve
import sys

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

# Use the Learner Lab credentials from .env, like the setup scripts. Without this, boto3
# falls back to ~/.aws/credentials, which usually holds an expired token from an old session.
# override=True so stale AWS_* variables already set in the shell don't win over .env.
load_dotenv(override=True)

SHELVE = "aws_resources.db"
# Older runs of configure_lambda.py did not record the function name in the shelve.
DEFAULT_LAMBDA = "ImageProcessingFunction"
NOT_FOUND = {"ResourceNotFoundException", "NotFoundException", "NoSuchBucket",
             "AWS.SimpleQueueService.NonExistentQueue", "QueueDoesNotExist", "404"}


def parse_args():
    ap = argparse.ArgumentParser(description="Delete the AWS resources recorded in aws_resources.db.")
    ap.add_argument("--really-delete", action="store_true", help="Actually delete (default: dry run).")
    return ap.parse_args()


def error_code(e: ClientError) -> str:
    return e.response.get("Error", {}).get("Code", "")


class Remover:
    def __init__(self, session: boto3.Session, really: bool):
        self.s = session
        self.really = really
        self.done_keys = []   # shelve keys whose resource is gone

    def step(self, label, keys, action):
        """Run one delete: dry-run print, or run action() treating 'not found' as already deleted."""
        print(label)
        if not self.really:
            print("  DRY-RUN: would delete")
            return
        try:
            action()
            print("  Deleted.")
        except ClientError as e:
            if error_code(e) not in NOT_FOUND:
                print(f"  ERROR: {e}")
                return
            print("  Already gone.")
        self.done_keys += keys

    # 1. API Gateway
    def api(self, api_id, function_name):
        def action():
            self.s.client("apigatewayv2").delete_api(ApiId=api_id)
            try:  # permission added by create_api_gateway.py
                self.s.client("lambda").remove_permission(
                    FunctionName=function_name, StatementId=f"apigw-invoke-{api_id}")
            except ClientError as e:
                if error_code(e) not in NOT_FOUND:
                    raise
        self.step(f"[API Gateway] HTTP API {api_id}", ["api-id", "api-endpoint"], action)

    # 2. Lambda (+ SQS trigger)
    def lambda_function(self, name, recorded):
        lam = self.s.client("lambda")

        def action():
            # Event source mappings are NOT deleted together with the function.
            for m in lam.list_event_source_mappings(FunctionName=name).get("EventSourceMappings", []):
                lam.delete_event_source_mapping(UUID=m["UUID"])
                print(f"  Deleted SQS trigger {m['UUID']}")
            lam.delete_function(FunctionName=name)
        self.step(f"[Lambda] {name}", ["lambda-function"] if recorded else [], action)

    # 3. SQS
    def queue(self, url):
        self.step(f"[SQS] {url}", ["messages-queue"],
                  lambda: self.s.client("sqs").delete_queue(QueueUrl=url))

    # 4. DynamoDB
    def table(self, name):
        def action():
            ddb = self.s.client("dynamodb")
            ddb.delete_table(TableName=name)
            ddb.get_waiter("table_not_exists").wait(TableName=name)
        self.step(f"[DynamoDB] {name}", ["dynamodb-table", "dynamodb-table-arn"], action)

    # 5. S3
    def bucket(self, name, key):
        def action():
            b = self.s.resource("s3").Bucket(name)
            b.object_versions.delete()   # also covers non-versioned objects
            b.objects.all().delete()
            b.delete()
        self.step(f"[S3] {name} (emptied first)", [key], action)


def main():
    args = parse_args()
    if not os.path.exists(SHELVE + ".dat") and not os.path.exists(SHELVE):
        sys.exit(f"{SHELVE} not found: nothing recorded to delete.")

    with shelve.open(SHELVE, flag="r") as db:
        rec = dict(db)

    session = boto3.Session(region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"))
    ident = session.client("sts").get_caller_identity()
    print(f"Account {ident['Account']} as {ident['Arn']}")
    print("DRY RUN (add --really-delete to delete).\n" if not args.really_delete else "DELETING.\n")

    r = Remover(session, args.really_delete)
    function_name = rec.get("lambda-function") or DEFAULT_LAMBDA

    if rec.get("api-id"):
        r.api(rec["api-id"], function_name)
    r.lambda_function(function_name, recorded="lambda-function" in rec)
    if rec.get("messages-queue"):
        r.queue(rec["messages-queue"])
    if rec.get("dynamodb-table"):
        r.table(rec["dynamodb-table"])
    for key in ("images-bucket", "thumbnails-bucket"):
        if rec.get(key):
            r.bucket(rec[key], key)

    if r.done_keys:
        with shelve.open(SHELVE) as db:
            for k in r.done_keys:
                db.pop(k, None)
        print(f"\nRemoved from {SHELVE}: {', '.join(r.done_keys)}")
    print("Done.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nAborted by user.")
