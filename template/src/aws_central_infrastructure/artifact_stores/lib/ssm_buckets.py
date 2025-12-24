import logging

from ephemeral_pulumi_deploy import append_resource_suffix
from ephemeral_pulumi_deploy import common_tags
from lab_auto_pulumi import ORG_MANAGED_SSM_PARAM_PREFIX
from lab_auto_pulumi import AwsLogicalWorkload
from lab_auto_pulumi import ManualArtifactsBucket
from lab_auto_pulumi import create_worm_bucket
from pulumi import ComponentResource
from pulumi import ResourceOptions
from pulumi_aws.iam import GetPolicyDocumentStatementArgs
from pulumi_aws.iam import GetPolicyDocumentStatementConditionArgs
from pulumi_aws.iam import GetPolicyDocumentStatementPrincipalArgs
from pulumi_aws.iam import get_policy_document
from pulumi_aws.organizations import get_organization
from pulumi_aws_native import s3
from pulumi_aws_native import ssm

from aws_central_infrastructure.iac_management.lib import create_providers
from aws_central_infrastructure.iac_management.lib import load_workload_info
from aws_central_infrastructure.iac_management.lib import principal_in_org_condition

logger = logging.getLogger(__name__)


class DistributorPackagesBucket(ComponentResource):
    def __init__(
        self,
    ):
        super().__init__("labauto:SsmDistributorPackagesBucket", append_resource_suffix(), None)
        # These artifacts are deployed to machines and devices. It's too much of a security risk to let people overwrite them, so setting up WORM.
        self.bucket = create_worm_bucket(resource_name="ssm-distributor-packages", parent=self)
        org_id = get_organization().id
        principal_arns = [
            "arn:aws:iam::*:role/InfraDeploy*",
            "arn:aws:iam::*:role/InfraPreview*",
            # TODO: figure out if there's any way around this limitation, so that the `AWSReservedSSO_LowRiskAccountAdminAccess` role can be specified instead of just '*'    https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_elements_principal.html#principal-sessions
            "*",
        ]
        _ = s3.BucketPolicy(
            append_resource_suffix("distributor-packages"),
            opts=ResourceOptions(parent=self, delete_before_replace=True),
            bucket=self.bucket.bucket_name,  # type: ignore[reportArgumentType] # pyright somehow thinks a bucket name can be Output[None], which doesn't seem possible
            policy_document=self.bucket.bucket_name.apply(
                lambda bucket_name: get_policy_document(
                    statements=[
                        GetPolicyDocumentStatementArgs(
                            effect="Allow",
                            actions=["s3:PutObject", "s3:GetObject"],
                            principals=[
                                GetPolicyDocumentStatementPrincipalArgs(
                                    type="AWS",
                                    identifiers=["*"],
                                )
                            ],
                            conditions=[
                                GetPolicyDocumentStatementConditionArgs(
                                    variable="aws:PrincipalArn",
                                    test="StringLike",
                                    values=principal_arns,
                                ),
                                principal_in_org_condition(org_id),
                            ],
                            resources=[f"arn:aws:s3:::{bucket_name}/${{aws:PrincipalAccount}}/*"],
                        ),
                        GetPolicyDocumentStatementArgs(
                            effect="Allow",
                            actions=["s3:ListBucket"],
                            principals=[
                                GetPolicyDocumentStatementPrincipalArgs(
                                    type="AWS",
                                    identifiers=["*"],
                                )
                            ],
                            resources=[f"arn:aws:s3:::{bucket_name}"],
                            conditions=[
                                GetPolicyDocumentStatementConditionArgs(
                                    variable="aws:PrincipalArn",
                                    test="StringLike",
                                    values=principal_arns,
                                ),
                                principal_in_org_condition(org_id),
                                GetPolicyDocumentStatementConditionArgs(
                                    test="StringLike", variable="s3:prefix", values=["${aws:PrincipalAccount}/*"]
                                ),
                            ],
                        ),
                    ]
                ).json
            ),
        )


class SsmBucketsSsmParameters(ComponentResource):
    def __init__(
        self,
        *,
        workload_info: AwsLogicalWorkload,
        distributor_packages_bucket: DistributorPackagesBucket,
        manual_artifacts_bucket: ManualArtifactsBucket,
    ):
        super().__init__("labauto:SsmBucketsSsmParameters", append_resource_suffix(workload_info.name), None)
        all_accounts = [*workload_info.prod_accounts, *workload_info.staging_accounts, *workload_info.dev_accounts]
        for account in all_accounts:
            self.providers = create_providers(aws_accounts=[account], parent=self)

            _ = ssm.Parameter(
                append_resource_suffix(
                    f"distributor-packages-bucket-name-{workload_info.name}-{account.id}", max_length=100
                ),
                type=ssm.ParameterType.STRING,
                name=f"{ORG_MANAGED_SSM_PARAM_PREFIX}/ssm-distributor-packages-bucket-name",
                value=distributor_packages_bucket.bucket.bucket_name,  # type: ignore[reportArgumentType] # pyright thinks somehow the bucket name could be Output[None], which doesn't seem possible
                opts=ResourceOptions(provider=self.providers[account.id], parent=self, delete_before_replace=True),
                tags=common_tags(),
            )
            _ = ssm.Parameter(
                append_resource_suffix(
                    f"manual-artifacts-bucket-name-{workload_info.name}-{account.id}", max_length=100
                ),
                type=ssm.ParameterType.STRING,
                name=f"{ORG_MANAGED_SSM_PARAM_PREFIX}/manual-artifacts-bucket-name",
                value=manual_artifacts_bucket.bucket.bucket_name,  # type: ignore[reportArgumentType] # pyright thinks somehow the bucket name could be Output[None], which doesn't seem possible
                opts=ResourceOptions(provider=self.providers[account.id], parent=self, delete_before_replace=True),
                tags=common_tags(),
            )


def create_ssm_bucket_ssm_params(
    *, distributor_packages_bucket: DistributorPackagesBucket, manual_artifacts_bucket: ManualArtifactsBucket
) -> None:
    workloads_dict, _ = load_workload_info()
    for workload_info in workloads_dict.values():
        _ = SsmBucketsSsmParameters(
            workload_info=workload_info,
            distributor_packages_bucket=distributor_packages_bucket,
            manual_artifacts_bucket=manual_artifacts_bucket,
        )
