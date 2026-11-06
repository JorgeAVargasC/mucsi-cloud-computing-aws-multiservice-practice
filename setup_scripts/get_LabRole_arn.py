import boto3
import shelve

role_name = "LabRole"
sts = boto3.client("sts")
ident = sts.get_caller_identity()

account_id = ident["Account"]
partition  = ident["Arn"].split(":")[1]   # e.g., "aws", "aws-us-gov", "aws-cn"
labrole_arn = f"arn:{partition}:iam::{account_id}:role/{role_name}"

# Store in shelve
with shelve.open("aws_resources.db") as db:
    db["labrole-arn"] = labrole_arn

print("LabRole ARN:", labrole_arn)
print("Saved to shelve key 'labrole-arn'.")
