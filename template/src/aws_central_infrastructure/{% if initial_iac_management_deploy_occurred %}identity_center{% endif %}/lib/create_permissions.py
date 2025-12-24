import logging
from pathlib import Path
from typing import TYPE_CHECKING

from lab_auto_pulumi import AwsLogicalWorkload
from lab_auto_pulumi import AwsSsoPermissionSet
from lab_auto_pulumi import AwsSsoPermissionSetAccountAssignments
from lab_auto_pulumi import UserInfo
from lab_auto_pulumi import all_created_users
from pulumi_aws.iam import GetPolicyDocumentStatementArgs
from pulumi_aws.iam import get_policy_document

from aws_central_infrastructure.iac_management.lib import CODE_ARTIFACT_SERVICE_BEARER_STATEMENT
from aws_central_infrastructure.iac_management.lib import PULL_FROM_CENTRAL_ECRS_STATEMENTS

from ..permissions import create_permissions
from .permissions import MANUAL_ARTIFACTS_UPLOAD_PERM_SET_CONTAINER

OKTA_EXISTS = (Path(__file__).parent.parent.parent / "okta").exists()

if OKTA_EXISTS:
    from aws_central_infrastructure.okta.users import define_user_configs

    if TYPE_CHECKING:
        from aws_central_infrastructure.okta.lib.program import OktaUserConfig


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
    user_info_from_okta: list[UserInfo] = []
    if OKTA_EXISTS:
        all_okta_users: list[
            OktaUserConfig  # pyright: ignore[reportPossiblyUnboundVariable] # it matches the if condition above
        ] = []
        define_user_configs(  # pyright: ignore[reportPossiblyUnboundVariable] # it matches the if condition above
            all_okta_users
        )
        user_info_from_okta.extend([UserInfo(username=user_config.username) for user_config in all_okta_users])

    _ = (
        AwsSsoPermissionSetAccountAssignments(
            account_info=workloads_dict["central-infra"].prod_accounts[0],
            permission_set=core_infra_base_access,
            users=[
                *list(all_created_users.values()),
                *user_info_from_okta,
            ],
        ),
    )
    manual_artifacts_perm_set = MANUAL_ARTIFACTS_UPLOAD_PERM_SET_CONTAINER.permission_set
    _ = (
        AwsSsoPermissionSetAccountAssignments(
            account_info=workloads_dict["central-infra"].prod_accounts[0],
            permission_set=manual_artifacts_perm_set,
            users=[
                *list(all_created_users.values()),
                *user_info_from_okta,
            ],
        ),
    )
