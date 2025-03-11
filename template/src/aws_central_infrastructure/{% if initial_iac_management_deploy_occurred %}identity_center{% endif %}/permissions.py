from aws_central_infrastructure.iac_management.lib import AwsLogicalWorkload

from .lib import LOW_RISK_ADMIN_PERM_SET_CONTAINER
from .lib import VIEW_ONLY_PERM_SET_CONTAINER
from .lib import create_org_admin_permissions
from .lib import create_read_state_inline_policy


def create_permissions(workloads_dict: dict[str, AwsLogicalWorkload]) -> None:
    _ = LOW_RISK_ADMIN_PERM_SET_CONTAINER.create_permission_set()

    _ = VIEW_ONLY_PERM_SET_CONTAINER.create_permission_set(inline_policy=create_read_state_inline_policy())

    create_org_admin_permissions(workloads_dict=workloads_dict, users=[])
