import pulumi
import pulumi_aws
from ephemeral_pulumi_deploy import append_resource_suffix
from ephemeral_pulumi_deploy import common_tags
from lab_auto_pulumi import ORG_MANAGED_PARAMS_AND_SECRETS_PREFIX
from pulumi import ComponentResource
from pulumi import ResourceOptions
from pulumi_aws import iam as aws_iam
from pulumi_aws import secretsmanager as aws_secretsmanager
from pulumi_aws.iam import GetPolicyDocumentStatementArgs
from pulumi_aws.iam import get_policy_document
from pydantic import BaseModel
from pydantic import model_validator

from aws_central_infrastructure.iac_management.lib import ECR_AUTH_STATEMENT
from aws_central_infrastructure.iac_management.lib.constants import CENTRAL_INFRA_PROD_ACCOUNT_ID


EXTERNAL_CREDS_SECRET_PREFIX = f"{ORG_MANAGED_PARAMS_AND_SECRETS_PREFIX}/external-creds"


class EcrRepo(BaseModel):
    name: str
    dangerously_accept_wildcard_match: bool = False

    @model_validator(mode="after")
    def no_wildcards_unless_accepted(self) -> "EcrRepo":
        if not self.dangerously_accept_wildcard_match and ("*" in self.name or "?" in self.name):
            raise ValueError(f"Wildcards not allowed in ECR repo name: {self.name!r}")  # noqa: TRY003  # it is in fact a value error and this doesn't warrant a custom exception
        return self


class ExternalCredConfig(BaseModel):
    organization: str
    description: str
    ecr_repos: list[EcrRepo]

    @property
    def user_name(self) -> str:
        return f"external-creds-{self.organization}"


class ExternalCred(ComponentResource):
    def __init__(self, *, config: ExternalCredConfig):
        super().__init__(
            "labauto:ExternalCred",
            append_resource_suffix(config.user_name),
            None,
        )

        tags = {**common_tags(), "Description": config.description}

        user = aws_iam.User(
            append_resource_suffix(config.user_name),
            name=config.user_name,
            opts=ResourceOptions(parent=self),
            tags=tags,
        )

        repo_arns = [
            f"arn:aws:ecr:{pulumi_aws.config.region}:{CENTRAL_INFRA_PROD_ACCOUNT_ID}:repository/{repo.name}"
            for repo in config.ecr_repos
        ]

        _ = aws_iam.UserPolicy(
            append_resource_suffix(config.user_name),
            user=user.name,
            # pylint: disable=duplicate-code
            # TODO: decide whether ECR policy statements belong in a shared library
            policy=get_policy_document(
                statements=[
                    ECR_AUTH_STATEMENT,
                    GetPolicyDocumentStatementArgs(
                        sid="EcrPull",
                        effect="Allow",
                        actions=[
                            "ecr:BatchGetImage",
                            "ecr:GetDownloadUrlForLayer",
                            "ecr:DescribeImages",
                            "ecr:ListImages",
                        ],
                        resources=repo_arns,
                    ),
                ]
            ).json,
            # pylint: enable=duplicate-code
            opts=ResourceOptions(parent=self),
        )

        access_key = aws_iam.AccessKey(
            append_resource_suffix(config.user_name),
            user=user.name,
            opts=ResourceOptions(parent=self),
        )

        secret = aws_secretsmanager.Secret(
            append_resource_suffix(config.user_name),
            name=f"{EXTERNAL_CREDS_SECRET_PREFIX}/{config.user_name}",
            opts=ResourceOptions(parent=self),
            tags=tags,
        )

        _ = aws_secretsmanager.SecretVersion(
            append_resource_suffix(f"{config.user_name}-version", max_length=100),
            secret_id=secret.id,
            secret_string=pulumi.Output.json_dumps(
                {
                    "access_key_id": access_key.id,
                    "secret_access_key": access_key.secret,
                }
            ),
            opts=ResourceOptions(parent=self),
        )


def create_external_creds(*, external_cred_configs: list[ExternalCredConfig]) -> None:
    for config in external_cred_configs:
        _ = ExternalCred(config=config)
