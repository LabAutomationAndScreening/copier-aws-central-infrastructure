from collections import defaultdict

from ephemeral_pulumi_deploy import append_resource_suffix
from pulumi import ResourceOptions
from pulumi_okta import Provider
from pulumi_okta import UserGroupMemberships
from pulumi_okta.group import Group
from pulumi_okta.user import User
from pydantic import BaseModel
from pydantic import Field

from .users import EmailAddress


class OktaGroupConfig(BaseModel, frozen=True):
    name: str
    description: str
    assigned_users: list[EmailAddress] = Field(default_factory=list[EmailAddress])


def create_groups(
    *, group_configs: list[OktaGroupConfig], user_objects: dict[EmailAddress, User], provider: Provider
) -> dict[str, Group]:
    user_group_memberships: dict[EmailAddress, list[Group]] = defaultdict(list)
    groups: dict[str, Group] = {}
    for group_config in group_configs:
        group = Group(
            append_resource_suffix(group_config.name.lower().replace(" ", "-")),
            name=group_config.name,
            description=group_config.description,
            opts=ResourceOptions(provider=provider),
        )
        groups[group_config.name] = group
        for user_email in group_config.assigned_users:
            user_group_memberships[user_email].append(group)
    for user_email, user_groups in user_group_memberships.items():
        _ = UserGroupMemberships(
            append_resource_suffix(
                f"{user_email.lower().replace('@', '-').replace('.', '-')}-group-membership", max_length=200
            ),
            user_id=user_objects[user_email].id,
            groups=[group.id for group in user_groups],
            opts=ResourceOptions(provider=provider),
        )
    return groups
