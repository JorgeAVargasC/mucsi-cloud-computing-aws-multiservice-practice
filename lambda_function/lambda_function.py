"""Image copy/metadata worker invoked by SQS or API Gateway HTTP API (payload v2)."""
import json
import os
import boto3
from urllib.parse import quote

s3_client = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")
THUMB_BUCKET = os.environ["THUMB_BUCKET"]
TABLE_NAME = os.getenv("TABLE_NAME", "ImageMetadata")
table = dynamodb.Table(TABLE_NAME)


def process_image(src_bucket, image_key):
    """Copy an already-uploaded image and write metadata; does NOT resize pixels."""
    head = s3_client.head_object(Bucket=src_bucket, Key=image_key)
    content_type = head.get("ContentType", "application/octet-stream")
    size_bytes = head.get("ContentLength", 0)
    thumbnail_key = f"thumbnails/{image_key}"
    s3_client.copy_object(
        Bucket=THUMB_BUCKET,
        Key=thumbnail_key,
        CopySource={"Bucket": src_bucket, "Key": image_key},
        MetadataDirective="REPLACE",
        ContentType=content_type,
    )
    original_url = f"https://{src_bucket}.s3.amazonaws.com/{quote(image_key, safe='/')}"
    thumbnail_url = f"https://{THUMB_BUCKET}.s3.amazonaws.com/{quote(thumbnail_key, safe='/')}"
    table.put_item(Item={
        "ImageID": image_key,
        "OriginalURL": original_url,
        "ThumbnailURL": thumbnail_url,
        "Bytes": size_bytes,
        "Note": "No resize performed (pure-Python build).",
    })
    print(f"Processed s3://{src_bucket}/{image_key} -> s3://{THUMB_BUCKET}/{thumbnail_key}")
    return {"image_key": image_key, "thumbnail_key": thumbnail_key,
            "thumbnail_url": thumbnail_url, "bytes": size_bytes}


def http_response(status, data):
    return {"statusCode": status, "headers": {"content-type": "application/json"},
            "body": json.dumps(data)}


def handle_http(event):
    # API Gateway HTTP API payload format v2.0 (Lambda proxy integration).
    request = event.get("requestContext", {}).get("http", {})
    method = request.get("method", "")
    path = event.get("rawPath", "/")
    if method == "GET" and path == "/health":
        return http_response(200, {"status": "ok", "service": "image-processing"})
    if method != "POST" or path != "/process":
        return http_response(404, {"error": "Use GET /health or POST /process"})

    # The source bucket is configured server-side: API callers cannot select arbitrary buckets.
    source_bucket = os.getenv("SOURCE_BUCKET", "")
    if not source_bucket:
        return http_response(500, {"error": "SOURCE_BUCKET not configured in Lambda"})
    try:
        payload = json.loads(event.get("body") or "{}")
    except (ValueError, TypeError):
        return http_response(400, {"error": "Request body must be valid JSON"})
    if not isinstance(payload, dict):
        return http_response(400, {"error": "Request body must be a JSON object"})
    image_key = payload.get("image_key")
    if not isinstance(image_key, str) or not image_key.strip() or len(image_key) > 1024:
        return http_response(400, {"error": "image_key must be a nonempty string (max 1024 chars)"})
    try:
        result = process_image(source_bucket, image_key)
        return http_response(200, {"message": "Image processed", **result})
    except s3_client.exceptions.ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("404", "NoSuchKey", "NotFound"):
            return http_response(404, {"error": "Image not found in the configured source bucket"})
        print(f"AWS S3 error: {exc}")
        return http_response(500, {"error": "Image processing failed; check CloudWatch logs"})
    except Exception as exc:
        print(f"Image processing failed: {exc}")
        return http_response(500, {"error": "Image processing failed; check CloudWatch logs"})


def lambda_handler(event, context):
    if "requestContext" in event and "http" in event.get("requestContext", {}):
        return handle_http(event)

    # Preserve the existing SQS trigger/event contract.
    try:
        for record in event["Records"]:
            body = json.loads(record["body"])
            process_image(body["bucket_name"], body["image_key"])
        return {"statusCode": 200, "body": json.dumps("Processing completed.")}
    except Exception as exc:
        # A failed Lambda SQS batch should be retried; never hide failures as 200.
        print(f"SQS processing failed: {exc}")
        raise
