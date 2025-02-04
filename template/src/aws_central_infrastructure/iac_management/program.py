import logging
from typing import TYPE_CHECKING

import boto3
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
from .shared_lib import WORKLOAD_INFO_SSM_PARAM_PREFIX
from .shared_lib import AwsLogicalWorkload

if TYPE_CHECKING:
    from mypy_boto3_ssm.type_defs import ParameterMetadataTypeDef
logger = logging.getLogger(__name__)


class AwsWorkloadPulumiBootstrap(ComponentResource):
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
                principals=[
                    GetPolicyDocumentStatementPrincipalArgs(
                        type="*",
                        identifiers=["*"],  # Allows all principals
                    )
                ],
                actions=["s3:PutObject", "s3:GetObject", "s3:DeleteObject"],
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

    ssm_client = boto3.client("ssm", region_name=organization_home_region)

    parameters: list[ParameterMetadataTypeDef] = []
    next_token = None

    while True:
        # API call with optional pagination
        response = ssm_client.describe_parameters(
            ParameterFilters=[{"Key": "Name", "Option": "BeginsWith", "Values": [WORKLOAD_INFO_SSM_PARAM_PREFIX]}],
            MaxResults=50,  # AWS allows up to 50 results per call
            NextToken=next_token if next_token else "",
        )

        # Add parameters from this page
        parameters.extend(response.get("Parameters", []))

        # Check if more pages exist
        next_token = response.get("NextToken")
        if not next_token:
            break

    def get_parameter_value(name: str) -> str:
        response = ssm_client.get_parameter(  # TODO: consider using get_parameters for just a single API call
            Name=name,
        )
        param_dict = response["Parameter"]
        assert "Value" in param_dict, f"Value not found in parameter {param_dict}"
        return param_dict["Value"]

    param_values: list[str] = []
    for param in parameters:
        assert "Name" in param, f"Name not found in parameter {param}"
        param_name = param["Name"]
        param_value = get_parameter_value(param_name)
        param_values.append(param_value)

    workloads_info = [AwsLogicalWorkload.model_validate_json(param) for param in param_values]

    for workload_info in workloads_info:
        _ = AwsWorkloadPulumiBootstrap(
            workload=workload_info,
            organization_home_region=organization_home_region,
            central_state_bucket_name=central_state_bucket_name,
            central_iac_kms_key_arn=kmy_key_arn,
        )
