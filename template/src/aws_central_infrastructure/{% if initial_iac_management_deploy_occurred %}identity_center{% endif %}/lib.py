from functools import cached_property
from typing import Any
from typing import override

from pulumi import ComponentResource
from pulumi import ResourceOptions
from pulumi_aws import identitystore as identitystore_classic
from pulumi_aws import ssoadmin
from pydantic import BaseModel

from ..iac_management.shared_lib import AwsAccountInfo


class OrgInfo(BaseModel):
    @cached_property
    def sso_instances(self) -> ssoadmin.AwaitableGetInstancesResult:
        instances = ssoadmin.get_instances()
        assert len(instances.arns) == 1, f"Expected a single AWS SSO instance to exist, but found {len(instances.arns)}"
        return instances

    @cached_property
    def sso_instance_arn(self) -> str:
        return self.sso_instances.arns[0]

    @cached_property
    def identity_store_id(self) -> str:
        all_ids = self.sso_instances.identity_store_ids
        assert len(all_ids) == 1, f"Expected a single identity store id, but found {len(all_ids)}"
        return self.sso_instances.identity_store_ids[0]


ORG_INFO = OrgInfo()


def lookup_user_id(username: str) -> str:
    """Convert a username name into an AWS SSO User ID."""
    return identitystore_classic.get_user(
        alternate_identifier=identitystore_classic.GetUserAlternateIdentifierArgs(
            unique_attribute=identitystore_classic.GetUserAlternateIdentifierUniqueAttributeArgs(
                attribute_path="UserName", attribute_value=username
            )
        ),
        identity_store_id=ORG_INFO.identity_store_id,
    ).user_id


class AwsSsoPermissionSet(ComponentResource):
    def __init__(
        self,
        *,
        name: str,
        description: str,
        managed_policies: list[str],
    ):
        super().__init__("labauto:AwsSsoPermissionSet", name, None)
        self.name = name
        permission_set = ssoadmin.PermissionSet(
            name,
            instance_arn=ORG_INFO.sso_instance_arn,
            name=name,
            description=description,
            session_duration="PT12H",
            opts=ResourceOptions(parent=self),
        )
        self.permission_set_arn = permission_set.arn
        for policy_name in managed_policies:
            _ = ssoadmin.ManagedPolicyAttachment(
                f"{name}-{policy_name}",
                instance_arn=ORG_INFO.sso_instance_arn,
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
        users = list(set(users))  # Remove any duplicates in the list

        for user in users:
            _ = ssoadmin.AccountAssignment(
                f"{resource_name}-{user}",
                instance_arn=ORG_INFO.sso_instance_arn,
                permission_set_arn=permission_set.permission_set_arn,
                principal_id=lookup_user_id(user),
                principal_type="USER",
                target_id=account_info.id,
                target_type="AWS_ACCOUNT",
                opts=ResourceOptions(parent=self),
            )


class User(BaseModel):  # NOT RECOMMENDED TO USE THIS IF YOU HAVE AN EXTERNAL IDENTITY PROVIDER!!
    first_name: str
    last_name: str
    email: str
    _user: identitystore_classic.User | None = None

    @override
    def model_post_init(self, _: Any) -> None:
        self._user = identitystore_classic.User(
            f"{self.first_name}-{self.last_name}",
            identity_store_id=ORG_INFO.identity_store_id,
            display_name=f"{self.first_name} {self.last_name}",
            user_name=f"{self.first_name}.{self.last_name}",
            name=identitystore_classic.UserNameArgs(
                given_name=self.first_name,
                family_name=self.last_name,
            ),
            emails=identitystore_classic.UserEmailsArgs(primary=True, value=self.email),
        )

    @property
    def user(self) -> identitystore_classic.User:
        assert self._user is not None
        return self._user
