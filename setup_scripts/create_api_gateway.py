"""
Create (or reuse) an API Gateway HTTP API in front of ImageProcessingFunction.

Script equivalent of README section 9.3/9.4 (done there from the AWS Console):
  - HTTP API "ImageProcessingAPI"
  - Lambda proxy integration, payload format 2.0
  - Routes GET /health and POST /process
  - Stage $default with auto-deploy
  - Resource-based permission so API Gateway can invoke the Lambda

Idempotent: running it again reuses what already exists instead of creating duplicates.
Saves 'api-id' and 'api-endpoint' in aws_resources.db.
"""
import os
import shelve
import boto3
from dotenv import load_dotenv

load_dotenv()

FUNCTION_NAME = "ImageProcessingFunction"
API_NAME = "ImageProcessingAPI"
ROUTES = ["GET /health", "POST /process"]
STAGE_NAME = "$default"

session = boto3.Session(
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    aws_session_token=os.getenv("AWS_SESSION_TOKEN"),
    region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
)
apigw = session.client("apigatewayv2")
lambda_client = session.client("lambda")
sts = session.client("sts")


def paginate(method, key, **kwargs):
    """apigatewayv2 has no paginators for these calls: follow NextToken by hand."""
    token = None
    while True:
        if token:
            kwargs["NextToken"] = token
        resp = method(**kwargs)
        yield from resp.get(key, [])
        token = resp.get("NextToken")
        if not token:
            return


def get_or_create_api():
    for api in paginate(apigw.get_apis, "Items"):
        if api["Name"] == API_NAME and api["ProtocolType"] == "HTTP":
            print(f"HTTP API '{API_NAME}' already exists (id {api['ApiId']}), reusing it.")
            return api
    api = apigw.create_api(Name=API_NAME, ProtocolType="HTTP")
    print(f"HTTP API '{API_NAME}' created (id {api['ApiId']}).")
    return api


def get_or_create_integration(api_id, lambda_arn):
    for integ in paginate(apigw.get_integrations, "Items", ApiId=api_id):
        if integ.get("IntegrationType") == "AWS_PROXY" and integ.get("IntegrationUri") == lambda_arn:
            if integ.get("PayloadFormatVersion") != "2.0":
                apigw.update_integration(ApiId=api_id, IntegrationId=integ["IntegrationId"],
                                         PayloadFormatVersion="2.0")
                print("Existing integration switched to payload format 2.0.")
            print(f"Lambda integration already exists (id {integ['IntegrationId']}).")
            return integ["IntegrationId"]
    integ = apigw.create_integration(
        ApiId=api_id,
        IntegrationType="AWS_PROXY",       # Lambda proxy integration
        IntegrationUri=lambda_arn,
        PayloadFormatVersion="2.0",        # event format lambda_handler expects
    )
    print(f"Lambda integration created (id {integ['IntegrationId']}).")
    return integ["IntegrationId"]


def ensure_routes(api_id, integration_id):
    target = f"integrations/{integration_id}"
    existing = {r["RouteKey"]: r for r in paginate(apigw.get_routes, "Items", ApiId=api_id)}
    for route_key in ROUTES:
        route = existing.get(route_key)
        if route is None:
            apigw.create_route(ApiId=api_id, RouteKey=route_key, Target=target)
            print(f"Route '{route_key}' created.")
        elif route.get("Target") != target:
            apigw.update_route(ApiId=api_id, RouteId=route["RouteId"], Target=target)
            print(f"Route '{route_key}' re-pointed to the Lambda integration.")
        else:
            print(f"Route '{route_key}' already exists.")


def ensure_stage(api_id):
    stages = {s["StageName"]: s for s in paginate(apigw.get_stages, "Items", ApiId=api_id)}
    stage = stages.get(STAGE_NAME)
    if stage is None:
        apigw.create_stage(ApiId=api_id, StageName=STAGE_NAME, AutoDeploy=True)
        print(f"Stage '{STAGE_NAME}' created with auto-deploy.")
    elif stage.get("AutoDeploy"):
        print(f"Stage '{STAGE_NAME}' already exists with auto-deploy.")
    else:
        # Auto-deploy disabled (e.g. changed by hand in the console): publish the changes explicitly.
        apigw.create_deployment(ApiId=api_id, StageName=STAGE_NAME)
        print(f"Stage '{STAGE_NAME}' has no auto-deploy: new deployment created.")


def ensure_invoke_permission(api_id, account_id, partition):
    """Resource-based policy on the Lambda (NOT the execution role): lets API Gateway invoke it."""
    region = session.region_name
    try:
        lambda_client.add_permission(
            FunctionName=FUNCTION_NAME,
            StatementId=f"apigw-invoke-{api_id}",
            Action="lambda:InvokeFunction",
            Principal="apigateway.amazonaws.com",
            SourceArn=f"arn:{partition}:execute-api:{region}:{account_id}:{api_id}/*/*",
        )
        print("Invoke permission for API Gateway added to the Lambda.")
    except lambda_client.exceptions.ResourceConflictException:
        print("Invoke permission for API Gateway already present.")


def main():
    ident = sts.get_caller_identity()
    account_id = ident["Account"]
    partition = ident["Arn"].split(":")[1]

    try:
        lambda_arn = lambda_client.get_function(FunctionName=FUNCTION_NAME)["Configuration"]["FunctionArn"]
    except lambda_client.exceptions.ResourceNotFoundException:
        raise RuntimeError(f"Lambda '{FUNCTION_NAME}' not found. Run setup_scripts/configure_lambda.py first.")

    api = get_or_create_api()
    api_id = api["ApiId"]
    integration_id = get_or_create_integration(api_id, lambda_arn)
    ensure_routes(api_id, integration_id)
    ensure_stage(api_id)
    ensure_invoke_permission(api_id, account_id, partition)

    endpoint = api["ApiEndpoint"]
    with shelve.open("aws_resources.db") as db:
        db["api-id"] = api_id
        db["api-endpoint"] = endpoint

    print("\nSaved 'api-id' and 'api-endpoint' to aws_resources.db.")
    print(f"API URL:  {endpoint}")
    print(f"  GET  {endpoint}/health")
    print(f"  POST {endpoint}/process   body: {{\"image_key\": \"statue_small.jpg\"}}")
    print("Test it with: python setup_scripts/test_api_gateway.py")


if __name__ == "__main__":
    main()
