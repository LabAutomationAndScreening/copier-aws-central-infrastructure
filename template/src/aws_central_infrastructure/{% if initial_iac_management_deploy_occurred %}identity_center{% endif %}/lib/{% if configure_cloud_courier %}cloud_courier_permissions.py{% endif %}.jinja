from pulumi_aws.iam import GetPolicyDocumentStatementArgs
from pulumi_aws.iam import GetPolicyDocumentStatementConditionArgs
from pulumi_aws.iam import get_policy_document

from .lib import UserInfo
from .permissions import AwsLogicalWorkload
from .permissions import AwsSsoPermissionSet
from .permissions import AwsSsoPermissionSetAccountAssignments
from .permissions import DefaultWorkloadPermissionAssignments


def create_read_permission_set() -> AwsSsoPermissionSet:
    cloud_courier_bucket_pattern = "raw-data*--cloud-courier--*"  # TODO: consider if it's worth tagging the bucket with a specific tag to make this less dependent on naming
    return AwsSsoPermissionSet(
        name="CloudCourierRawDataReadAccess",
        description="Read access to raw data files uploaded by Cloud Courier",
        inline_policy=get_policy_document(
            statements=[
                GetPolicyDocumentStatementArgs(
                    sid="ObjectLevelPermissions",
                    effect="Allow",
                    actions=[
                        "s3:GetObject",
                        "s3:GetObjectVersion",
                        "s3:GetObjectVersionAttributes",
                        "s3:GetObjectTagging",
                    ],
                    resources=[f"arn:aws:s3:::{cloud_courier_bucket_pattern}/*"],
                ),
                GetPolicyDocumentStatementArgs(
                    sid="BucketLevelPermissions",
                    effect="Allow",
                    actions=[
                        "s3:ListBucket",
                        "s3:ListBucketVersions",
                        "s3:ListTagsForResource",
                        "s3:GetBucketLocation",
                        "s3:GetBucketTagging",
                        "s3:GetBucketMetadataTableConfiguration",
                    ],
                    resources=[f"arn:aws:s3:::{cloud_courier_bucket_pattern}"],
                ),
                GetPolicyDocumentStatementArgs(  # TODO: remove this if we can get the SSO Permission Set Relay working better
                    sid="TopLevelS3Permissions",
                    effect="Allow",
                    actions=[
                        "s3:ListAllMyBuckets",
                    ],
                    resources=["*"],
                ),
                GetPolicyDocumentStatementArgs(
                    sid="ReadBucketMetrics",
                    effect="Allow",
                    actions=[
                        "cloudwatch:ListMetrics",
                        "cloudwatch:GetMetricStatistics",
                    ],  # there doesn't appear to be a simple way to further lock these down with RequestConditions
                    resources=["*"],
                ),
            ]
        ).json,
    )


def create_ssm_permission_set() -> AwsSsoPermissionSet:
    project_tag_condition = GetPolicyDocumentStatementConditionArgs(
        test="StringEquals",
        variable="aws:ResourceTag/pulumi-project-name",
        values=["cloud-courier"],
    )
    ssm_logs_bucket_pattern = "arn:aws:s3:::ssm-logs--cloud-courier--*"
    return AwsSsoPermissionSet(
        # TODO: apparently a run command can still select other buckets besides the log bucket and logs will be written to them...need to figure out how to make sure logs can only be written to ssm-logs bucket
        name="CloudCourierUploadAgentAdmin",
        description="Permissions to install, stop, start, and update the Cloud Courier Upload Agent running on the Lab computers.",
        inline_policy=get_policy_document(
            statements=[
                GetPolicyDocumentStatementArgs(
                    sid="TopLevelS3Permissions",
                    effect="Allow",
                    actions=[
                        "s3:ListAllMyBuckets",  # TODO: see if there's a way to restrict the dropdown list for where to send the log to only the ssm-logs bucket
                    ],
                    resources=["*"],
                ),
                GetPolicyDocumentStatementArgs(
                    sid="ReadBucketMetrics",
                    effect="Allow",
                    actions=[
                        "cloudwatch:ListMetrics",
                        "cloudwatch:GetMetricStatistics",
                    ],  # there doesn't appear to be a simple way to further lock these down with RequestConditions
                    resources=["*"],
                ),
                GetPolicyDocumentStatementArgs(
                    sid="ViewSsmLogs",
                    effect="Allow",
                    actions=[
                        "s3:ListBucket",
                        "s3:ListBucketVersions",
                        "s3:ListTagsForResource",
                        "s3:GetBucketLocation",
                        "s3:GetBucketTagging",
                        "s3:GetBucketMetadataTableConfiguration",
                    ],
                    resources=[ssm_logs_bucket_pattern],
                ),
                GetPolicyDocumentStatementArgs(
                    sid="ViewSsmLogObjects",
                    effect="Allow",
                    actions=[
                        "s3:GetObject",
                        "s3:GetObjectVersion",
                        "s3:GetObjectVersionAttributes",
                        "s3:GetObjectTagging",
                    ],
                    resources=[f"{ssm_logs_bucket_pattern}/*"],
                ),
                GetPolicyDocumentStatementArgs(
                    sid="TopLevelSsmPermissions",
                    effect="Allow",
                    actions=[
                        "ssm:ListCommands",
                        "ssm:ListAssociations",
                        "ssm:ListTagsForResource",  # this could be locked down further...but low risk
                        "ssm:ListDocuments",  # attempting to lock this down further with a resource tag condition was causing issues in the console trying to view (using ssm:ResourceTag didn't seem to help either)
                        "ssm:ListCommandInvocations",
                    ],
                    resources=["*"],
                ),
                GetPolicyDocumentStatementArgs(
                    sid="SsmInstancePermissions",
                    effect="Allow",
                    actions=[
                        "ssm:ListInstanceAssociations",
                        "ssm:ListNodes",
                        "ssm:DescribeInstanceInformation",
                        "ssm:DescribeInstanceProperties",
                    ],
                    resources=["*"],
                ),
                GetPolicyDocumentStatementArgs(
                    sid="SsmDocumentPermissions",
                    effect="Allow",
                    actions=[
                        "ssm:ListDocumentMetadataHistory",
                        "ssm:DescribeDocument",
                        "ssm:ListDocumentVersions",
                        "ssm:DescribeDocumentParameters",
                        "ssm:GetDocument",
                        "ssm:DescribeDocumentPermission",  # there's errors in the console without this...which isn't the end of the world, but is annoying UX
                    ],
                    resources=["*"],
                    conditions=[project_tag_condition],
                ),
                GetPolicyDocumentStatementArgs(
                    sid="DistributorPermissions",  # TODO: figure out if there's a way to restrict the packages that can be installed to only CloudCourier...maybe ssm resource tags...?
                    effect="Allow",
                    actions=[
                        "ssm:ListDocumentVersions",
                        "ssm:DescribeDocumentParameters",
                        "ssm:GetDocument",
                        "ssm:DescribeDocumentPermission",  # there's errors in the console without this...which isn't the end of the world, but is annoying UX
                        "ssm:SendCommand",
                    ],
                    resources=[
                        "arn:aws:ssm:*::document/AWS-ConfigureAWSPackage",
                        ssm_logs_bucket_pattern,
                        "arn:aws:ssm:*:*:managed-instance/*",  # TODO: see if the account can be further locked down...but initially using `${aws:PrincipalAccount}` was giving errors during deploy],
                    ],
                ),
                GetPolicyDocumentStatementArgs(
                    sid="RunCommandPermissions",
                    effect="Allow",
                    actions=[
                        "ssm:SendCommand",
                    ],
                    resources=[
                        ssm_logs_bucket_pattern,
                        "arn:aws:ssm:*:*:managed-instance/*",  # TODO: see if the account can be further locked down...but initially using `${aws:PrincipalAccount}` was giving errors during deploy
                        "arn:aws:ssm:*:*:document/*",  # TODO: see if the account can be further locked down...but initially using `${aws:PrincipalAccount}` was giving errors during deploy
                    ],
                    conditions=[
                        project_tag_condition,
                    ],
                ),
            ]
        ).json,
    )


def create_cloud_courier_permissions(
    *,
    workload_info: AwsLogicalWorkload,
    end_users: list[UserInfo] | None = None,
    administrators: list[UserInfo] | None = None,
) -> None:
    read_access = create_read_permission_set()
    # Read access for end-users
    _ = AwsSsoPermissionSetAccountAssignments(
        account_info=workload_info.prod_accounts[0],
        permission_set=read_access,
        # TODO: add a relay to the S3 console for buckets....TBD what to do about region
        users=end_users,
    )

    _ = DefaultWorkloadPermissionAssignments(
        workload_info=workload_info,
        users=administrators,
    )
    ssm_access = create_ssm_permission_set()
    for protected_env_account in [
        *workload_info.prod_accounts,
        *workload_info.staging_accounts,
        *workload_info.dev_accounts,  # TODO: remove before merge
    ]:
        _ = AwsSsoPermissionSetAccountAssignments(
            account_info=protected_env_account,
            permission_set=ssm_access,
            users=administrators,
        )
