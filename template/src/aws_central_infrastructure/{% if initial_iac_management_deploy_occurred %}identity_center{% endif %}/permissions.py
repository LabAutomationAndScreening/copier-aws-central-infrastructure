from ..iac_management.shared_lib import AwsLogicalWorkload
from .lib import AwsSsoPermissionSet


def create_permissions(workloads_dict: dict[str, AwsLogicalWorkload]) -> None:  # noqa: ARG001 # this argument will be used when the template is instantiated
    admin_permission_set = AwsSsoPermissionSet(  # noqa: F841 # this variable will be used when the template is instantiated
        name="LowRiskAccountAdminAccess",
        description="Low Risk Account Admin Access",
        managed_policies=["AdministratorAccess"],
    )
