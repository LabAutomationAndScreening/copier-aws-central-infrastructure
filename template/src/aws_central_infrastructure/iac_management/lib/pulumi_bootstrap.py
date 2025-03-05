import logging

from ephemeral_pulumi_deploy import get_config_str
from ephemeral_pulumi_deploy.utils import common_tags
from pulumi import ComponentResource
from pulumi import ResourceOptions
from pulumi_aws.iam import GetPolicyDocumentStatementArgs
from pulumi_aws.iam import GetPolicyDocumentStatementConditionArgs
from pulumi_aws.iam import GetPolicyDocumentStatementPrincipalArgs
from pulumi_aws.iam import get_policy_document
from pulumi_aws.organizations import get_organization
from pulumi_aws_native import Provider
from pulumi_aws_native import ProviderAssumeRoleArgs
from pulumi_aws_native import ssm

from .constants import CENTRAL_INFRA_REPO_NAME
from .github_oidc_lib import AwsAccountId
from .shared_lib import ORG_MANAGED_SSM_PARAM_PREFIX
from .shared_lib import AwsAccountInfo
from .shared_lib import AwsLogicalWorkload

logger = logging.getLogger(__name__)


def create_providers(*, aws_accounts: list[AwsAccountInfo], parent: ComponentResource) -> dict[AwsAccountId, Provider]:
    providers: dict[AwsAccountId, Provider] = {}
    organization_home_region = get_config_str("proj:aws_org_home_region")
    for account in aws_accounts:
        role_arn = f"arn:aws:iam::{account.id}:role/InfraDeploy--{CENTRAL_INFRA_REPO_NAME}"
        assume_role = ProviderAssumeRoleArgs(role_arn=role_arn, session_name="pulumi")
        provider = Provider(
            f"central-infra-provider-for-{account.name}",
            assume_role=assume_role,
            allowed_account_ids=[account.id],
            region=organization_home_region,
            opts=ResourceOptions(parent=parent),
        )
        providers[account.id] = provider
    return providers


class AwsWorkloadPulumiBootstrap(ComponentResource):
    providers: dict[AwsAccountId, Provider]

    def __init__(
        self,
        *,
        workload: AwsLogicalWorkload,
        central_state_bucket_name: str,
        central_iac_kms_key_arn: str,
    ):
        super().__init__("labauto:AwsWorkloadPulumiBootstrap", workload.name, None)
        all_accounts = [*workload.prod_accounts, *workload.staging_accounts, *workload.dev_accounts]
        self.providers = create_providers(aws_accounts=all_accounts, parent=self)
        for account in all_accounts:
            _ = ssm.Parameter(
                f"central-infra-state-bucket-name-in-{account.name}",
                type=ssm.ParameterType.STRING,
                name=f"{ORG_MANAGED_SSM_PARAM_PREFIX}/infra-state-bucket-name",
                value=central_state_bucket_name,
                opts=ResourceOptions(provider=self.providers[account.id], parent=self, delete_before_replace=True),
                tags=common_tags(),
            )
            _ = ssm.Parameter(
                f"shared-kms-key-arn-in-{account.name}",
                type=ssm.ParameterType.STRING,
                name=f"{ORG_MANAGED_SSM_PARAM_PREFIX}/infra-state-kms-key-arn",
                value=central_iac_kms_key_arn,
                opts=ResourceOptions(provider=self.providers[account.id], parent=self, delete_before_replace=True),
                tags=common_tags(),
            )


def create_bucket_policy(bucket_name: str) -> str:
    org_id = get_organization().id
    return get_policy_document(
        statements=[
            GetPolicyDocumentStatementArgs(
                effect="Allow",
                actions=["s3:PutObject", "s3:GetObject", "s3:DeleteObject"],
                principals=[
                    GetPolicyDocumentStatementPrincipalArgs(
                        type="*",
                        identifiers=["*"],  # Allows all principals
                    )
                ],
                resources=[f"arn:aws:s3:::{bucket_name}/${{aws:PrincipalAccount}}/*"],
                conditions=[
                    GetPolicyDocumentStatementConditionArgs(
                        test="StringEquals",
                        variable="aws:PrincipalOrgID",
                        values=[org_id],  # Limit to the AWS Organization
                    ),
                ],
            ),
            GetPolicyDocumentStatementArgs(
                effect="Allow",
                principals=[GetPolicyDocumentStatementPrincipalArgs(type="*", identifiers=["*"])],
                actions=["s3:ListBucket"],
                resources=[f"arn:aws:s3:::{bucket_name}"],
                conditions=[
                    GetPolicyDocumentStatementConditionArgs(
                        test="StringEquals", variable="aws:PrincipalOrgID", values=[org_id]
                    ),
                    GetPolicyDocumentStatementConditionArgs(
                        test="StringLike", variable="s3:prefix", values=["${aws:PrincipalAccount}/*"]
                    ),
                ],
            ),
        ]
    ).json
