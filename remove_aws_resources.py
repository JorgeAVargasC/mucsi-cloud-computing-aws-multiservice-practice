#!/usr/bin/env python3
import argparse, sys, shelve
from typing import Iterable, List, Dict
import boto3
from botocore.exceptions import ClientError

def parse_args():
    ap = argparse.ArgumentParser(description="Remove S3 buckets and SQS queues (tries LabRole, falls back if denied).")
    ap.add_argument("--prefix", default="", help="Only delete names starting with this prefix (list-mode).")
    ap.add_argument("--region", default=None, help="Default region for SQS (fallback AWS_DEFAULT_REGION/us-east-1).")
    ap.add_argument("--all-regions", action="store_true", help="Operate across all available regions for S3 and SQS.")
    ap.add_argument("--services", default="s3,sqs", help="Comma list: s3,sqs")
    ap.add_argument("--really-delete", action="store_true", help="Required to actually delete.")
    ap.add_argument("--quiet", action="store_true", help="Less logging.")
    ap.add_argument("--role-name", default="LabRole", help="Role to assume (default: LabRole).")
    ap.add_argument("--session-name", default="nuke-resources-session", help="STS RoleSessionName.")
    ap.add_argument("--from-shelve", action="store_true",
                    help="Delete ONLY resources recorded in aws_resources.db (no List* calls).")
    return ap.parse_args()

def log(msg, quiet=False):
    if not quiet: print(msg)

# ---------- Assume role (optional) ----------
def build_role_arn(sts_client, role_name: str) -> str:
    ident = sts_client.get_caller_identity()
    account = ident["Account"]
    partition = ident["Arn"].split(":")[1]
    return f"arn:{partition}:iam::{account}:role/{role_name}"

def assume_role_session(role_arn: str, session_name: str, region: str | None):
    sts = boto3.client("sts", region_name=region or "us-east-1")
    creds = sts.assume_role(RoleArn=role_arn, RoleSessionName=session_name)["Credentials"]
    return boto3.Session(
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
        region_name=region or boto3.session.Session().region_name or "us-east-1",
    )

# ---------- S3 helpers ----------
def s3_bucket_region(s3_global, bucket_name) -> str:
    loc = s3_global.get_bucket_location(Bucket=bucket_name).get("LocationConstraint")
    return "us-east-1" if loc in (None, "", "US") else loc

def empty_bucket(session: boto3.Session, bucket: str, region: str, quiet=False):
    s3 = session.client("s3", region_name=region)
    # versions + delete markers
    paginator = s3.get_paginator("list_object_versions")
    for page in paginator.paginate(Bucket=bucket):
        objs: List[Dict] = []
        for v in page.get("Versions", []): objs.append({"Key": v["Key"], "VersionId": v["VersionId"]})
        for m in page.get("DeleteMarkers", []): objs.append({"Key": m["Key"], "VersionId": m["VersionId"]})
        for i in range(0, len(objs), 1000):
            if objs[i:i+1000]:
                s3.delete_objects(Bucket=bucket, Delete={"Objects": objs[i:i+1000], "Quiet": True})
                log(f"  - Deleted {len(objs[i:i+1000])} versioned keys", quiet)
    # plain listing
    paginator2 = s3.get_paginator("list_objects_v2")
    for page in paginator2.paginate(Bucket=bucket):
        keys = [{"Key": o["Key"]} for o in page.get("Contents", [])]
        for i in range(0, len(keys), 1000):
            if keys[i:i+1000]:
                s3.delete_objects(Bucket=bucket, Delete={"Objects": keys[i:i+1000], "Quiet": True})
                log(f"  - Deleted {len(keys[i:i+1000])} keys", quiet)
    # abort MPUs
    try:
        mp = s3.get_paginator("list_multipart_uploads")
        for page in mp.paginate(Bucket=bucket):
            for u in page.get("Uploads", []):
                s3.abort_multipart_upload(Bucket=bucket, Key=u["Key"], UploadId=u["UploadId"])
                log(f"  - Aborted MPU for {u['Key']}", quiet)
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") not in ("NoSuchUpload","NoSuchBucket"): raise

def delete_bucket_by_name(session: boto3.Session, bucket: str, quiet=False, really=False):
    s3_global = session.client("s3")
    try:
        region = s3_bucket_region(s3_global, bucket)
    except ClientError as e:
        log(f"[S3] {bucket}: cannot get region ({e}). Skipping.", quiet); return
    log(f"[S3] Bucket: {bucket} (region {region})", quiet)
    if not really:
        log("  DRY-RUN: would empty and delete bucket", quiet); return
    try:
        empty_bucket(session, bucket, region, quiet)
        session.client("s3", region_name=region).delete_bucket(Bucket=bucket)
        log("  Deleted bucket.", quiet)
    except ClientError as e:
        log(f"  Error deleting {bucket}: {e}", quiet)

def delete_all_buckets(session: boto3.Session, prefix: str, really: bool, quiet=False):
    s3_global = session.client("s3")
    try:
        buckets = s3_global.list_buckets().get("Buckets", [])
    except ClientError as e:
        print(f"Failed to list buckets: {e}"); return
    names = [b["Name"] for b in buckets if not prefix or b["Name"].startswith(prefix)]
    if not names:
        log("No S3 buckets match the criteria.", quiet); return
    for name in names:
        delete_bucket_by_name(session, name, quiet=quiet, really=really)

# ---------- SQS helpers ----------
def available_regions_for(session: boto3.Session, service: str) -> Iterable[str]:
    return session.get_available_regions(service)

def delete_queue_by_url(session: boto3.Session, queue_url: str, region: str | None, quiet=False, really=False):
    r = region or session.region_name or "us-east-1"
    sqs = session.client("sqs", region_name=r)
    log(f"[SQS {r}] Queue: {queue_url}", quiet)
    if not really:
        log("  DRY-RUN: would delete queue", quiet); return
    try:
        sqs.delete_queue(QueueUrl=queue_url)
        log("  Deleted queue.", quiet)
    except ClientError as e:
        log(f"  Error deleting queue: {e}", quiet)

def delete_all_queues(session: boto3.Session, prefix: str, region: str | None, all_regions: bool, really: bool, quiet=False):
    if all_regions:
        regions = available_regions_for(session, "sqs")
    else:
        regions = [region or session.region_name or "us-east-1"]
    for r in regions:
        sqs = session.client("sqs", region_name=r)
        try:
            resp = sqs.list_queues(QueueNamePrefix=prefix) if prefix else sqs.list_queues()
            urls = resp.get("QueueUrls", [])
        except ClientError as e:
            log(f"[SQS {r}] list_queues failed: {e}", quiet); continue
        if not urls:
            log(f"[SQS {r}] No queues found.", quiet); continue
        for url in urls:
            delete_queue_by_url(session, url, r, quiet=quiet, really=really)

# ---------- Shelve-based targeted delete (no List* calls) ----------
def delete_from_shelve(session: boto3.Session, region_hint: str | None, really: bool, quiet=False):
    try:
        with shelve.open("aws_resources.db", flag="r") as db:
            images_bucket     = db.get("images-bucket")
            thumbnails_bucket = db.get("thumbnails-bucket")
            queue_url         = db.get("messages-queue")
    except Exception as e:
        raise RuntimeError(f"Cannot open aws_resources.db: {e}")

    if images_bucket:
        delete_bucket_by_name(session, images_bucket, quiet=quiet, really=really)
    else:
        log("[S3] No 'images-bucket' in aws_resources.db", quiet)

    if thumbnails_bucket:
        delete_bucket_by_name(session, thumbnails_bucket, quiet=quiet, really=really)
    else:
        log("[S3] No 'thumbnails-bucket' in aws_resources.db", quiet)

    if queue_url:
        delete_queue_by_url(session, queue_url, region_hint, quiet=quiet, really=really)
    else:
        log("[SQS] No 'messages-queue' in aws_resources.db", quiet)

# ---------- main ----------
def main():
    args = parse_args()
    services = {s.strip().lower() for s in args.services.split(",") if s.strip()}

    if not args.really_delete:
        print("DRY RUN (use --really-delete to actually delete).")

    # Show caller before assume
    base_ident = boto3.client("sts").get_caller_identity()
    print(f"Current caller: {base_ident['Arn']} (account {base_ident['Account']})")

    # Try to assume role
    session = None
    try:
        role_arn = build_role_arn(boto3.client("sts"), args.role_name)
        print(f"Assuming role: {role_arn}")
        session = assume_role_session(role_arn, args.session_name, args.region)
        assumed_ident = session.client("sts").get_caller_identity()
        print(f"Assumed as: {assumed_ident['Arn']} (account {assumed_ident['Account']})")
    except ClientError as e:
        print(f"AssumeRole failed ({e}). Falling back to current credentials.")
        session = boto3.Session(region_name=args.region or boto3.session.Session().region_name or "us-east-1")

    if args.from_shelve:
        # Target only known resources, no List* calls
        delete_from_shelve(session, args.region, really=args.really_delete, quiet=args.quiet)
    else:
        # Use list + delete flows (requires List permissions)
        if "s3" in services:
            delete_all_buckets(session, prefix=args.prefix, really=args.really_delete, quiet=args.quiet)
        if "sqs" in services:
            delete_all_queues(session, prefix=args.prefix, region=args.region,
                              all_regions=args.all_regions, really=args.really_delete, quiet=args.quiet)

    print("Done.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nAborted by user."); sys.exit(1)
