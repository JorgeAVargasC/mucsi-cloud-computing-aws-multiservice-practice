"""
Call the HTTP API created by create_api_gateway.py: GET /health and POST /process.

Usage:
    python setup_scripts/test_api_gateway.py                 # processes statue_small.jpg
    python setup_scripts/test_api_gateway.py woodcutters.jpg # processes another image

The image must already be in the images bucket (upload_folder_images.py uploads img/).
"""
import json
import shelve
import sys
import urllib.error
import urllib.request


def call(method, url, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            status, body = resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:  # 4xx/5xx still carry a useful JSON body
        status, body = e.code, e.read().decode()
    try:
        body = json.dumps(json.loads(body), indent=2, ensure_ascii=False)
    except ValueError:
        pass
    print(f"{method} {url} -> {status}\n{body}\n")
    return status


def main():
    with shelve.open("aws_resources.db", flag="r") as db:
        base = db.get("api-endpoint")
    if not base:
        sys.exit("No 'api-endpoint' in aws_resources.db. Run setup_scripts/create_api_gateway.py first.")

    image_key = sys.argv[1] if len(sys.argv) > 1 else "statue_small.jpg"

    ok = call("GET", f"{base}/health") == 200
    ok = call("POST", f"{base}/process", {"image_key": image_key}) == 200 and ok
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
