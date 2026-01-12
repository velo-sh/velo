import boto3

# Create client with dummy credentials to avoid looking for ~/.aws/credentials
s3 = boto3.client(
    "s3",
    region_name="us-east-1",
    aws_access_key_id="dummy",
    aws_secret_access_key="dummy",
)
print(f"Boto3 version: {boto3.__version__}")
