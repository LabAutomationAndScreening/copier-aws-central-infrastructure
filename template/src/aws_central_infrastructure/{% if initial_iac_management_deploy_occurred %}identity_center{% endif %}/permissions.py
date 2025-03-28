from lab_auto_pulumi import AwsLogicalWorkload

from .lib import LOW_RISK_ADMIN_PERM_SET_CONTAINER
from .lib import VIEW_ONLY_PERM_SET_CONTAINER
from .lib import create_org_admin_permissions


def create_permissions(workloads_dict: dict[str, AwsLogicalWorkload]) -> None:
    _ = LOW_RISK_ADMIN_PERM_SET_CONTAINER.permission_set

    _ = VIEW_ONLY_PERM_SET_CONTAINER.permission_set

    create_org_admin_permissions(workloads_dict=workloads_dict, users=[])
