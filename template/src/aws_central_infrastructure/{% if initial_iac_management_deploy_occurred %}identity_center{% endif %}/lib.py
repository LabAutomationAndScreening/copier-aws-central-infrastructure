from pulumi import ComponentResource
from pulumi import ResourceOptions
from pulumi_aws import identitystore as identitystore_classic
from pulumi_aws import ssoadmin

from ..iac_management.shared_lib import AwsAccountInfo


class AwsSsoPermissionSet(ComponentResource):
    def __init__(
        self,
        *,
        name: str,
        description: str,
        managed_policies: list[str],
    ):
        super().__init__("labauto:AwsSsoPermissionSet", name, None)
        sso_instances = ssoadmin.get_instances()
        assert len(sso_instances.arns) == 1, "Expected a single AWS SSO instance to exist"
        sso_instance_arn = sso_instances.arns[0]
        self.name = name
        permission_set = ssoadmin.PermissionSet(
            name,
            instance_arn=sso_instance_arn,
            name=name,
            description=description,
            session_duration="PT12H",
            opts=ResourceOptions(parent=self),
        )
        self.permission_set_arn = permission_set.arn
        for policy_name in managed_policies:
            _ = ssoadmin.ManagedPolicyAttachment(
                f"{name}-{policy_name}",
                instance_arn=sso_instance_arn,
                managed_policy_arn=f"arn:aws:iam::aws:policy/{policy_name}",
                permission_set_arn=self.permission_set_arn,
                opts=ResourceOptions(parent=self),
            )
        self.register_outputs(
            {
                "permission_set_arn": self.permission_set_arn,
            }
        )


class AwsSsoPermissionSetAccountAssignments(ComponentResource):
    def __init__(
        self,
        *,
        account_info: AwsAccountInfo,
        permission_set: AwsSsoPermissionSet,
        users: list[str],
    ):
        resource_name = f"{permission_set.name}-{account_info.name}"
        super().__init__(
            "labauto:AwsSsoPermissionSetAccountAssignments",
            resource_name,
            None,
        )
        sso_instances = ssoadmin.get_instances()
        assert len(sso_instances.arns) == 1, "Expected a single AWS SSO instance to exist"
        sso_instance_arn = sso_instances.arns[0]
        self.identity_store_id = sso_instances.identity_store_ids[0]
        users = list(set(users))  # Remove any duplicates in the list

        for user in users:
            _ = ssoadmin.AccountAssignment(
                f"{resource_name}-{user}",
                instance_arn=sso_instance_arn,
                permission_set_arn=permission_set.permission_set_arn,
                principal_id=self.lookup_user_id(user),
                principal_type="USER",
                target_id=account_info.id,
                target_type="AWS_ACCOUNT",
                opts=ResourceOptions(parent=self),
            )

    def lookup_user_id(self, name: str) -> str:
        """Convert a username <first>.<last> name into an AWS SSO User ID."""
        return identitystore_classic.get_user(
            alternate_identifier=identitystore_classic.GetUserAlternateIdentifierArgs(
                unique_attribute=identitystore_classic.GetUserAlternateIdentifierUniqueAttributeArgs(
                    attribute_path="UserName", attribute_value=name
                )
            ),
            identity_store_id=self.identity_store_id,
        ).user_id
