import logging

from ephemeral_pulumi_deploy import get_aws_account_id
from ephemeral_pulumi_deploy import get_config
from ephemeral_pulumi_deploy import get_config_str
from ephemeral_pulumi_deploy.utils import common_tags
from pulumi import ComponentResource
from pulumi import ResourceOptions
from pulumi import export
from pulumi.runtime import is_dry_run
from pulumi_aws.iam import GetPolicyDocumentStatementArgs
from pulumi_aws.iam import GetPolicyDocumentStatementConditionArgs
from pulumi_aws.iam import GetPolicyDocumentStatementPrincipalArgs
from pulumi_aws.iam import get_policy_document
from pulumi_aws.organizations import get_organization
from pulumi_aws_native import Provider
from pulumi_aws_native import ProviderAssumeRoleArgs
from pulumi_aws_native import s3
from pulumi_aws_native import ssm

from ..constants import CENTRAL_INFRA_REPO_NAME
from .github_oidc import generate_all_oidc
from .github_oidc_lib import AwsAccountId
from .github_oidc_lib import deploy_all_oidc
from .shared_lib import AwsLogicalWorkload
from .workload_params import WorkloadParams
from .workload_params import load_workload_info

logger = logging.getLogger(__name__)


class AwsWorkloadPulumiBootstrap(ComponentResource):
    providers: dict[AwsAccountId, Provider]

    def __init__(
        self,
        *,
        workload: AwsLogicalWorkload,
        organization_home_region: str,
        central_state_bucket_name: str,
        central_iac_kms_key_arn: str,
    ):
        super().__init__("labauto:AwsWorkloadPulumiBootstrap", workload.name, None)
        all_accounts = [*workload.prod_accounts, *workload.staging_accounts, *workload.dev_accounts]
        run_type = "Preview" if is_dry_run() else "Deploy"
        self.providers = {}
        for account in all_accounts:
            role_arn = f"arn:aws:iam::{account.id}:role/Infra{run_type}--{CENTRAL_INFRA_REPO_NAME}"

            assume_role = ProviderAssumeRoleArgs(role_arn=role_arn, session_name=f"pulumi-{run_type.lower()}")
            provider = Provider(
                f"central-infra-provider-for-{account.name}",
                assume_role=assume_role,
                allowed_account_ids=[account.id],
                region=organization_home_region,
                opts=ResourceOptions(
                    parent=self,
                    # TODO: figure out why ignore_changes isn't working
                    ignore_changes=[
                        "assumeRole.roleArn",
                        "assumeRole.sessionName",
                    ],  # ignore the ARN changes since during a preview we use the Preview Role, not the Deploy Role
                ),
            )
            self.providers[account.id] = provider
            _ = ssm.Parameter(
                f"central-infra-state-bucket-name-in-{account.name}",
                type=ssm.ParameterType.STRING,
                name="/org-managed/infra-state-bucket-name",
                value=central_state_bucket_name,
                opts=ResourceOptions(provider=provider, parent=self, delete_before_replace=True),
                tags=common_tags(),
            )
            _ = ssm.Parameter(
                f"shared-kms-key-arn-in-{account.name}",
                type=ssm.ParameterType.STRING,
                name="/org-managed/infra-state-kms-key-arn",
                value=central_iac_kms_key_arn,
                opts=ResourceOptions(provider=provider, parent=self, delete_before_replace=True),
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


def pulumi_program() -> None:
    """Execute creating the stack."""
    aws_account_id = get_aws_account_id()
    export("aws-account-id", aws_account_id)
    env = get_config("proj:env")
    export("env", env)

    # Create Resources Here
    organization_home_region = "us-east-1"
    central_state_bucket_name = get_config_str("proj:backend_bucket_name")
    kmy_key_arn = get_config_str("proj:kms_key_id")
    _ = s3.BucketPolicy(
        "bucket-policy",
        bucket=central_state_bucket_name,
        policy_document=create_bucket_policy(central_state_bucket_name),
    )

    workloads_dict, params_dict = load_workload_info(organization_home_region=organization_home_region)
    providers: dict[AwsAccountId, Provider] = {}
    for workload_info in workloads_dict.values():
        bootstrap = AwsWorkloadPulumiBootstrap(
            workload=workload_info,
            organization_home_region=organization_home_region,
            central_state_bucket_name=central_state_bucket_name,
            central_iac_kms_key_arn=kmy_key_arn,
        )
        providers.update(bootstrap.providers)
    _ = WorkloadParams(
        name="identity-center",
        params_dict=params_dict,
        provider=providers[workloads_dict["identity-center"].prod_accounts[0].id],
    )
    all_oidc = generate_all_oidc(workloads_info=workloads_dict, kms_key_arn=kmy_key_arn)
    deploy_all_oidc(
        all_oidc=[(workloads_dict[workload_name], value) for workload_name, value in all_oidc.items()],
        providers=providers,
    )
