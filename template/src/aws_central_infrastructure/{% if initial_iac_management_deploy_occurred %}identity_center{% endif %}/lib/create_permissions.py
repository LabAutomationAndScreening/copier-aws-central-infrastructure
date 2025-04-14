import logging

from lab_auto_pulumi import AwsLogicalWorkload
from lab_auto_pulumi import AwsSsoPermissionSet
from lab_auto_pulumi import AwsSsoPermissionSetAccountAssignments
from lab_auto_pulumi import all_created_users
from pulumi_aws.iam import GetPolicyDocumentStatementArgs
from pulumi_aws.iam import get_policy_document

from aws_central_infrastructure.iac_management.lib import CODE_ARTIFACT_SERVICE_BEARER_STATEMENT
from aws_central_infrastructure.iac_management.lib import PULL_FROM_CENTRAL_ECRS_STATEMENTS

from ..permissions import create_permissions

logger = logging.getLogger(__name__)


def create_all_permissions(workloads_dict: dict[str, AwsLogicalWorkload]):
    create_permissions(workloads_dict)
    core_infra_base_access = AwsSsoPermissionSet(
        name="CoreInfraBaseAccess",
        description="Base access everyone should have for the Central/Core Infrastructure Account",
        inline_policy=get_policy_document(
            statements=[
                CODE_ARTIFACT_SERVICE_BEARER_STATEMENT,
                *PULL_FROM_CENTRAL_ECRS_STATEMENTS,
                GetPolicyDocumentStatementArgs(
                    sid="EcrConsoleReadAccess",
                    effect="Allow",
                    actions=[
                        "ecr:DescribeRepositories",
                        "ecr:DescribeImageScanFindings",
                        "ecr:ListTagsForResource",
                        "ecr:GetRepositoryPolicy",
                    ],
                    resources=["*"],
                ),
            ]
        ).json,
    )

    _ = AwsSsoPermissionSetAccountAssignments(
        account_info=workloads_dict["central-infra"].prod_accounts[0],
        permission_set=core_infra_base_access,
        users=list(all_created_users.values()),
    )
