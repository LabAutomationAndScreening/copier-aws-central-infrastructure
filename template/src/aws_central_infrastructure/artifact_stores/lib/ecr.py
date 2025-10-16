import json
import logging

from ephemeral_pulumi_deploy import append_resource_suffix
from ephemeral_pulumi_deploy import common_tags_native
from ephemeral_pulumi_deploy import get_aws_account_id
from pulumi import ComponentResource
from pulumi import ResourceOptions
from pulumi_aws.iam import GetPolicyDocumentStatementArgs
from pulumi_aws.iam import GetPolicyDocumentStatementPrincipalArgs
from pulumi_aws.iam import get_policy_document
from pulumi_aws_native import ecr
from pulumi_aws_native import iam
from pydantic import BaseModel
from pydantic import Field

from aws_central_infrastructure.iac_management.lib import CENTRAL_INFRA_GITHUB_ORG_NAME
from aws_central_infrastructure.iac_management.lib import ECR_AUTH_STATEMENT
from aws_central_infrastructure.iac_management.lib import ECR_PULL_STATEMENT
from aws_central_infrastructure.iac_management.lib import GithubOidcConfig
from aws_central_infrastructure.iac_management.lib import principal_in_org_condition

logger = logging.getLogger(__name__)


class RepoEcrClaims(BaseModel):
    repo_name: str
    repo_org: str = CENTRAL_INFRA_GITHUB_ORG_NAME
    ecr_repo_names: set[str] = Field(default_factory=set)


class EcrConfig(BaseModel):
    git_repo_name: str | None = None
    git_repo_org: str | None = CENTRAL_INFRA_GITHUB_ORG_NAME
    ecr_repo_name: str
    ecr_repo_namespace: str | None = None

    @property
    def ecr_repo_full_name_for_arn(self) -> str:
        return f"{self.ecr_repo_namespace}/{self.ecr_repo_name}" if self.ecr_repo_namespace else self.ecr_repo_name

    @property
    def ecr_repo_full_name_for_resource(self) -> str:
        return self.ecr_repo_full_name_for_arn.replace("/", "-")


class Ecr(ComponentResource):
    def __init__(self, *, config: EcrConfig, central_infra_oidc_provider_arn: str, org_id: str):
        super().__init__("labauto:Ecr", append_resource_suffix(config.ecr_repo_full_name_for_resource), None)

        self.repository = ecr.Repository(
            append_resource_suffix(config.ecr_repo_full_name_for_resource),
            repository_name=config.ecr_repo_full_name_for_arn,
            empty_on_delete=True,  # note, there's an upstream bug in CloudFormation that causes this to not work as expected https://github.com/pulumi/pulumi-aws-native/issues/1270
            image_tag_mutability=ecr.RepositoryImageTagMutability.IMMUTABLE,
            repository_policy_text=json.loads(
                get_policy_document(
                    statements=[
                        GetPolicyDocumentStatementArgs(
                            effect="Allow",
                            sid="CrossAccountRead",
                            actions=["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer", "ecr:DescribeImages"],
                            principals=[
                                GetPolicyDocumentStatementPrincipalArgs(
                                    type="*",
                                    identifiers=["*"],
                                )
                            ],
                            conditions=[principal_in_org_condition(org_id)],
                        ),
                        # TODO: allow allow creating image-based Lambda functions that pull from the ECR, additional permissions needed according to https://docs.aws.amazon.com/lambda/latest/dg/configuration-images.html#configuration-images-permissions
                        # this is going to need to enumerate the list of all accounts in the org and add them to the policy
                    ]
                ).json
            ),
            opts=ResourceOptions(parent=self),
            tags=common_tags_native(),
        )
        if config.git_repo_org is not None and config.git_repo_name is not None:
            _ = GithubOidcConfig(
                aws_account_id=get_aws_account_id(),
                repo_org=config.git_repo_org,
                repo_name=config.git_repo_name,
                restrictions="*",
                role_name=f"GHA-ECR-Push-{config.ecr_repo_full_name_for_resource}",
                role_policy=iam.RolePolicyArgs(
                    policy_name="PushToEcr",
                    policy_document=self.repository.arn.apply(
                        lambda ecr_arn: get_policy_document(
                            statements=[
                                ECR_AUTH_STATEMENT,
                                ECR_PULL_STATEMENT,
                                GetPolicyDocumentStatementArgs(
                                    effect="Allow",
                                    sid="ImagePush",
                                    actions=[
                                        "ecr:BatchCheckLayerAvailability",
                                        "ecr:InitiateLayerUpload",
                                        "ecr:UploadLayerPart",
                                        "ecr:CompleteLayerUpload",
                                        "ecr:PutImage",
                                    ],
                                    resources=[ecr_arn],
                                ),
                            ]
                        ).json
                    ),
                ),
            ).create_role(provider_arn=central_infra_oidc_provider_arn, parent=self)


def create_ecrs(*, ecr_configs: list[EcrConfig], central_infra_oidc_provider_arn: str, org_id: str):
    for config in [
        *ecr_configs,
        EcrConfig(  # TODO: allow uploading to this via the Manual Artifact Upload permission set
            ecr_repo_name="manual-artifacts"
        ),
    ]:
        _ = Ecr(config=config, central_infra_oidc_provider_arn=central_infra_oidc_provider_arn, org_id=org_id)
