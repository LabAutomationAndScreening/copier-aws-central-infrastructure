import boto3
from ephemeral_pulumi_deploy import get_config_str
from lab_auto_pulumi import MANUAL_IAC_SECRETS_PREFIX
from pulumi.runtime import is_dry_run
from pulumi_okta import Provider

OKTA_DEPLOY_TOKEN_SECRET_NAME = f"{MANUAL_IAC_SECRETS_PREFIX}/deploy-tokens/okta-access-token"
OKTA_PREVIEW_TOKEN_SECRET_NAME = f"{MANUAL_IAC_SECRETS_PREFIX}/preview-tokens/okta-access-token"


def create_okta_provider() -> Provider:
    # Trying to use pulumi_aws GetSecretVersionResult isn't working because it still returns an Output, and Provider requires a string. Even attempting to use apply
    secrets_client = boto3.client("secretsmanager")
    secrets_response = secrets_client.list_secrets(
        Filters=[
            {
                "Key": "name",
                "Values": [OKTA_PREVIEW_TOKEN_SECRET_NAME if is_dry_run() else OKTA_DEPLOY_TOKEN_SECRET_NAME],
            }
        ]
    )
    secrets = secrets_response["SecretList"]
    assert len(secrets) == 1, f"expected only 1 matching secret, but found {len(secrets)}"
    assert "ARN" in secrets[0], f"expected 'ARN' in secrets, but found {secrets[0].keys()}"
    secret_id = secrets[0]["ARN"]
    token = secrets_client.get_secret_value(SecretId=secret_id)["SecretString"]

    return Provider(  # TODO: figure out why this isn't getting automatically picked up from the config
        "default", api_token=token, org_name=get_config_str("proj:okta_org_name"), base_url="okta.com"
    )
