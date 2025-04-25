import logging
from collections.abc import Callable
from typing import Any
from typing import override

from ephemeral_pulumi_deploy import get_config_str
from lab_auto_pulumi import AwsLogicalWorkload
from lab_auto_pulumi import AwsSsoPermissionSet
from lab_auto_pulumi import AwsSsoPermissionSetAccountAssignments
from lab_auto_pulumi import UserInfo
from pulumi_aws.iam import GetPolicyDocumentStatementArgs
from pulumi_aws.iam import GetPolicyDocumentStatementConditionArgs
from pulumi_aws.iam import get_policy_document
from pydantic import BaseModel
from pydantic import Field

from .lib import create_read_state_inline_policy

logger = logging.getLogger(__name__)


class AwsSsoPermissionSetContainer(BaseModel):
    name: str
    description: str
    managed_policies: list[str] = Field(
        default_factory=list,
        max_length=10,  # AWS default limit
    )
    inline_policy_callable: Callable[[], str] | None = None
    relay_state: Callable[[], str] | str | None = None
    _permission_set: AwsSsoPermissionSet | None = None

    def create_permission_set(self, inline_policy: str | None = None) -> AwsSsoPermissionSet:
        if inline_policy is None and self.inline_policy_callable is not None:
            inline_policy = self.inline_policy_callable()  # TODO: unit test this
        relay_state = self.relay_state
        if callable(relay_state):
            relay_state = relay_state()
        self._permission_set = AwsSsoPermissionSet(
            name=self.name,
            description=self.description,
            managed_policies=self.managed_policies,
            inline_policy=inline_policy,
            relay_state=relay_state,
        )
        return self._permission_set

    @property
    def permission_set(self) -> AwsSsoPermissionSet:
        assert self._permission_set is not None
        return self._permission_set


def create_manual_secrets_entry_inline_policy() -> str:
    return get_policy_document(
        statements=[
            GetPolicyDocumentStatementArgs(
                sid="AllResources",
                effect="Allow",
                actions=[
                    "secretsmanager:ListSecrets",  # when trying to use `secretsmanager:Name` and `secretsmanager:SecretId` to restrict this, it wouldn't let any be listed
                ],
                resources=["*"],
            ),
            GetPolicyDocumentStatementArgs(
                sid="SpecificSecrets",
                effect="Allow",
                actions=[
                    "secretsmanager:DescribeSecret",
                    "secretsmanager:GetSecretValue",
                    "secretsmanager:ListSecretVersionIds",
                    "secretsmanager:PutSecretValue",
                ],
                resources=["arn:aws:secretsmanager:*:*:secret:/manually-entered-secrets/*"],
            ),
        ]
    ).json


MANUAL_SECRETS_ENTRY_PERM_SET_CONTAINER = (
    AwsSsoPermissionSetContainer(  # TODO: set relay state to SecretsManager landing page
        name="ManualSecretsEntry",
        description="The ability to manually update secrets into the secrets manager.",
        inline_policy_callable=create_manual_secrets_entry_inline_policy,
    )
)
LOW_RISK_ADMIN_PERM_SET_CONTAINER = AwsSsoPermissionSetContainer(
    name="LowRiskAccountAdminAccess",
    description="Low Risk Account Admin Access",
    managed_policies=["AdministratorAccess"],
)

VIEW_ONLY_PERM_SET_CONTAINER = AwsSsoPermissionSetContainer(
    name="ViewOnlyAccess",
    description="The ability to view logs and other resource details in protected environments for troubleshooting.",
    managed_policies=[
        "AWSSupportAccess",  # Allow users to request AWS support for technical questions.
        "job-function/ViewOnlyAccess",  # wide ranging attribute view access across a variety of services
        "CloudWatchReadOnlyAccess",  # be able to read CloudWatch logs/metrics/etc
        "AmazonSSMReadOnlyAccess",  # look at SSM fleet/hybrid activation details
        "AWSLambda_ReadOnlyAccess",  # review traces and logs for debugging Lambdas easily through the console
        "AmazonEventBridgeReadOnlyAccess",  # see basic metrics about Event Bridges to troubleshoot
        "AmazonEC2ContainerRegistryReadOnly",  # describe ECR images,
        "AWSBillingReadOnlyAccess",  # view billing information to help optimize costs
        "CostOptimizationHubReadOnlyAccess",  # view actual costs and usage
        # TODO: figure out how to add back in AmazonEventBridgeSchemasReadOnlyAccess permission...but we're at the limit of managed policies that can be attached currently
        # TODO: figure out how to add back in "AmazonAppStreamReadOnlyAccess",  # look at the details of stack/fleet information to troubleshoot any issues
        # TODO: "CloudWatchEventsReadOnlyAccess",  # see information about event rules and patterns
    ],
    inline_policy_callable=create_read_state_inline_policy,
)

EC2_SSO_PER_SET_CONTAINER = AwsSsoPermissionSetContainer(  # based on https://aws.amazon.com/blogs/security/how-to-enable-secure-seamless-single-sign-on-to-amazon-ec2-windows-instances-with-aws-sso/
    name="SsoIntoEc2",
    description="The ability to SSO Login into EC2 instances via Systems Manager",
    relay_state=lambda: f"https://{get_config_str('proj:aws_org_home_region')}.console.aws.amazon.com/ec2/home?#Instances:v=3;$case=tags:true%5C,client:false;$regex=tags:false%5C,client:false",
    inline_policy_callable=lambda: get_policy_document(
        statements=[
            GetPolicyDocumentStatementArgs(
                sid="SSO",
                effect="Allow",
                actions=["sso:ListDirectoryAssociations*", "identitystore:DescribeUser"],
                resources=["*"],
            ),
            GetPolicyDocumentStatementArgs(
                sid="EC2",
                effect="Allow",
                actions=[
                    "ec2:Describe*",
                    "ec2:GetPasswordData",
                    "cloudwatch:DescribeAlarms",  # view alarms in EC2 Instances console
                    "cloudwatch:GetMetricData",  # view metrics in EC2 Instances console
                    "compute-optimizer:GetEnrollmentStatus",  # view recommendations in EC2 Instances console
                ],
                resources=["*"],
            ),
            GetPolicyDocumentStatementArgs(
                sid="EC2Management",
                effect="Allow",
                actions=[
                    "ec2:StartInstances",
                    "ec2:StopInstances",
                    "ec2:RebootInstances",
                    "ec2:GetConsoleOutput",
                    "ssm:GetConnectionStatus",
                ],
                resources=["arn:aws:ec2:*:*:instance/*"],
                conditions=[
                    GetPolicyDocumentStatementConditionArgs(
                        test="StringLike", variable="ec2:ResourceTag/UserAccess", values=["*--Everyone--*"]
                    )
                ],
                # TODO: figure out how to lock this down to the intended instances...in theory a condition using ec2:ResourceTag/UserAccess and a value of sts:RoleSessionName is supposed to work, but it didn't seem to principalArn may be a potential option
            ),
            GetPolicyDocumentStatementArgs(
                sid="SSM",
                effect="Allow",
                actions=[
                    "ssm:DescribeInstanceProperties",
                    "ssm:GetCommandInvocation",
                    "ssm:GetInventorySchema",
                    "ssm:DescribeInstanceInformation",
                ],
                resources=["*"],
            ),
            GetPolicyDocumentStatementArgs(
                sid="SSMMiscConsolePerms",
                effect="Allow",
                actions=[
                    "ssm:GetConnectionStatus",
                ],
                resources=[
                    "*"
                ],  # TODO: lock this down to the intended instances via a tag...maybe...maybe it doesn't matter it's just a read attribute
            ),
            GetPolicyDocumentStatementArgs(
                sid="TerminateSession",
                effect="Allow",
                actions=["ssm:TerminateSession"],
                resources=["*"],
                conditions=[
                    GetPolicyDocumentStatementConditionArgs(
                        test="StringLike",
                        variable="ssm:resourceTag/aws:ssmmessages:session-id",
                        values=["${aws:userName}"],
                    ),
                ],
            ),
            GetPolicyDocumentStatementArgs(
                sid="SSMGetDocument",
                effect="Allow",
                actions=["ssm:GetDocument"],
                resources=[
                    "arn:aws:ssm:*:*:document/AWS-StartPortForwardingSession",
                    "arn:aws:ssm:*:*:document/SSM-SessionManagerRunShell",
                ],
            ),
            GetPolicyDocumentStatementArgs(
                sid="SSMStartSession",
                effect="Allow",
                actions=["ssm:StartSession"],
                resources=[
                    "arn:aws:ec2:*:*:instance/*",
                    "arn:aws:ssm:*:*:managed-instance/*",
                    "arn:aws:ssm:*:*:document/AWS-StartPortForwardingSession",
                    "arn:aws:ssm:*:*:document/SSM-SessionManagerRunShell",
                ],
                conditions=[
                    GetPolicyDocumentStatementConditionArgs(
                        test="BoolIfExists",
                        variable="ssm:SessionDocumentAccessCheck",
                        values=["true"],
                    ),
                ],
            ),
            GetPolicyDocumentStatementArgs(
                sid="SSMSendCommand",
                effect="Allow",
                actions=["ssm:SendCommand"],
                resources=[
                    "arn:aws:ec2:*:*:instance/*",
                    "arn:aws:ssm:*:*:managed-instance/*",
                    "arn:aws:ssm:*:*:document/AWSSSO-CreateSSOUser",
                ],
                conditions=[
                    GetPolicyDocumentStatementConditionArgs(
                        test="BoolIfExists",
                        variable="ssm:SessionDocumentAccessCheck",
                        values=["true"],
                    ),
                ],
            ),
            GetPolicyDocumentStatementArgs(
                sid="GuiConnect",
                effect="Allow",
                actions=[
                    "ssm-guiconnect:CancelConnection",
                    "ssm-guiconnect:GetConnection",
                    "ssm-guiconnect:StartConnection",
                ],
                resources=["*"],
            ),
            GetPolicyDocumentStatementArgs(
                sid="TerminalConnect",
                effect="Allow",
                actions=[
                    "ssmmessages:CreateControlChannel",
                    "ssmmessages:CreateDataChannel",
                    "ssmmessages:OpenControlChannel",
                    "ssmmessages:OpenDataChannel",
                ],
                resources=[
                    "*"
                ],  # resources must be *.  TODO: figure out if there are relevant conditions that can lock it down
            ),
            GetPolicyDocumentStatementArgs(
                sid="GlobalS3",
                effect="Allow",
                actions=[
                    "s3:ListAllMyBuckets",
                    "s3:GetBucketLocation",
                ],
                resources=["*"],
            ),
        ]
    ).json,
)

ALL_PERM_SET_CONTAINERS = (
    MANUAL_SECRETS_ENTRY_PERM_SET_CONTAINER,
    LOW_RISK_ADMIN_PERM_SET_CONTAINER,
    VIEW_ONLY_PERM_SET_CONTAINER,
    EC2_SSO_PER_SET_CONTAINER,
)


class DefaultWorkloadPermissionAssignments(BaseModel):
    workload_info: AwsLogicalWorkload
    users: list[UserInfo] | None = None

    @override
    def model_post_init(self, _: Any) -> None:
        for protected_env_account in [*self.workload_info.prod_accounts, *self.workload_info.staging_accounts]:
            _ = AwsSsoPermissionSetAccountAssignments(
                account_info=protected_env_account,
                permission_set=VIEW_ONLY_PERM_SET_CONTAINER.permission_set,
                users=self.users,
            )
        for unprotected_env_account in self.workload_info.dev_accounts:
            _ = AwsSsoPermissionSetAccountAssignments(
                account_info=unprotected_env_account,
                permission_set=LOW_RISK_ADMIN_PERM_SET_CONTAINER.permission_set,
                users=self.users,
            )


def create_org_admin_permissions(
    *, workloads_dict: dict[str, AwsLogicalWorkload], users: list[UserInfo] | None = None
) -> None:
    view_only_permission_set = VIEW_ONLY_PERM_SET_CONTAINER.permission_set
    manual_secrets_entry_permission_set = MANUAL_SECRETS_ENTRY_PERM_SET_CONTAINER.permission_set

    _ = AwsSsoPermissionSetAccountAssignments(
        account_info=workloads_dict["central-infra"].prod_accounts[0],
        permission_set=view_only_permission_set,
        users=users,
    )
    _ = AwsSsoPermissionSetAccountAssignments(
        account_info=workloads_dict["central-infra"].prod_accounts[0],
        permission_set=manual_secrets_entry_permission_set,
        users=users,
    )
    _ = AwsSsoPermissionSetAccountAssignments(
        account_info=workloads_dict["identity-center"].prod_accounts[0],
        permission_set=view_only_permission_set,
        users=users,
    )

    _ = AwsSsoPermissionSetAccountAssignments(
        account_info=workloads_dict["billing-delegate"].prod_accounts[0],
        permission_set=view_only_permission_set,
        users=users,
    )
