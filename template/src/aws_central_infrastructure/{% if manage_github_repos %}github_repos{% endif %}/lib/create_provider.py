import os

import boto3
from lab_auto_pulumi import GITHUB_DEPLOY_TOKEN_SECRET_NAME
from lab_auto_pulumi import GITHUB_PREVIEW_TOKEN_SECRET_NAME
from pulumi.runtime import is_dry_run
from pulumi_github import Provider
from pydantic import BaseModel
from pydantic import Field

from aws_central_infrastructure.iac_management.lib import CENTRAL_INFRA_GITHUB_ORG_NAME

from .constants import USE_REPO_SECRET_FOR_GITHUB_IAC_TOKENS

# preview token permissions: all repositories, Administration:Read, Contents: Read, Environments: Read, OrgMembers: Read
# not sure where the rest of the info went for the deploy token permissions, but also need: Actions: Read (needed for dealing with Environments)

TOKENS_ENV_VAR_NAME = "IAC_GITHUB_API_TOKENS"


class GithubOrgApiTokens(BaseModel):
    deploy_token: str


type GithubOrgName = str


class IacGithubApiTokens(BaseModel):
    org_tokens: dict[GithubOrgName, GithubOrgApiTokens] = Field(default_factory=dict[GithubOrgName, GithubOrgApiTokens])


# example to set envvar locally: export IAC_GITHUB_API_TOKENS='{"org_tokens": {"LabAutomationAndScreening": {"deploy_token": "my-deploy-token"}}}'


def github_token_secret_name(*, org_name: str, is_preview: bool) -> str:
    base_name = GITHUB_PREVIEW_TOKEN_SECRET_NAME if is_preview else GITHUB_DEPLOY_TOKEN_SECRET_NAME
    if org_name == CENTRAL_INFRA_GITHUB_ORG_NAME:
        return base_name
    return f"{base_name}-{org_name}"


def _get_token(*, org_name: str) -> str:
    if USE_REPO_SECRET_FOR_GITHUB_IAC_TOKENS:
        if TOKENS_ENV_VAR_NAME in os.environ:
            raw_json_token_info = os.environ[TOKENS_ENV_VAR_NAME]
            if not raw_json_token_info:
                raise Exception(  # noqa: TRY003,TRY002 # not worth custom exception
                    f"The environment variable {TOKENS_ENV_VAR_NAME} is set, but it is empty. Please set it to the GitHub API token."
                )
            tokens = IacGithubApiTokens.model_validate_json(raw_json_token_info, strict=True)
            if org_name not in tokens.org_tokens:
                raise Exception(  # noqa: TRY003,TRY002 # not worth custom exception
                    f"No token found for organization '{org_name}' in {TOKENS_ENV_VAR_NAME}. Found: {sorted(tokens.org_tokens.keys())}"
                )
            return tokens.org_tokens[org_name].deploy_token
        if is_dry_run() and "CI" not in os.environ:
            return ""  # if this is just a local pulumi preview, then a 'real' token is probably not needed
        raise Exception(  # noqa: TRY003,TRY002 # not worth custom exception
            f"If you are running a deployment locally (which you shouldn't be doing), then it appears you forgot to set the {TOKENS_ENV_VAR_NAME} environment variable to the GitHub API token."
        )
    secrets_client = boto3.client("secretsmanager")
    secrets_response = secrets_client.list_secrets(
        Filters=[
            {
                "Key": "name",
                "Values": [github_token_secret_name(org_name=org_name, is_preview=is_dry_run())],
            }
        ]
    )
    secrets = secrets_response["SecretList"]
    assert len(secrets) == 1, f"expected only 1 matching secret, but found {len(secrets)}"
    assert "ARN" in secrets[0], f"expected 'ARN' in secrets[0], but found {secrets[0].keys()}"
    secret_id = secrets[0]["ARN"]
    return secrets_client.get_secret_value(SecretId=secret_id)["SecretString"]


def create_github_provider(*, org_name: str) -> Provider:
    # Trying to use pulumi_aws GetSecretVersionResult isn't working because it still returns an Output, and Provider requires a string. Even attempting to use apply

    token = _get_token(org_name=org_name)

    return Provider(  # TODO: figure out why this isn't getting automatically picked up from the config
        "default", token=token, owner=org_name
    )
