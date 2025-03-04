from aws_central_infrastructure.iac_management.lib import AwsLogicalWorkload

from .lib import LOW_RISK_ADMIN_PERM_SET_CONTAINER
from .lib import VIEW_ONLY_PERM_SET_CONTAINER
from .lib import AwsSsoPermissionSetAccountAssignments
from .lib import DefaultWorkloadPermissionAssignments
from .lib import all_created_users
from .lib import create_read_state_inline_policy


def create_permissions(workloads_dict: dict[str, AwsLogicalWorkload]) -> None:
    admin_permission_set = LOW_RISK_ADMIN_PERM_SET_CONTAINER.create_permission_set()

    _ = VIEW_ONLY_PERM_SET_CONTAINER.create_permission_set(inline_policy=create_read_state_inline_policy())

    _ = AwsSsoPermissionSetAccountAssignments(
        account_info=workloads_dict["central-infra"].prod_accounts[0],
        permission_set=admin_permission_set,
        users=[all_created_users["eli.fine"]],
    )
    _ = AwsSsoPermissionSetAccountAssignments(
        account_info=workloads_dict["biotasker"].dev_accounts[0],
        permission_set=admin_permission_set,
        users=[all_created_users["eli.fine"]],
    )
    _ = AwsSsoPermissionSetAccountAssignments(
        account_info=workloads_dict["identity-center"].prod_accounts[0],
        permission_set=admin_permission_set,
        users=[all_created_users["eli.fine"]],
    )
    _ = DefaultWorkloadPermissionAssignments(
        workload_info=workloads_dict["cloud-courier"],
        users=[all_created_users["eli.fine"]],
    )
