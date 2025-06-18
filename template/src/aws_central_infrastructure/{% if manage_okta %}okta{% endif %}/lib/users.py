from ephemeral_pulumi_deploy import append_resource_suffix
from pulumi import ResourceOptions
from pulumi_okta import Provider
from pulumi_okta.user import User
from pydantic import BaseModel

type EmailAddress = str


class OktaUserConfig(BaseModel):
    username: str
    email: str
    first_name: str
    last_name: str


def create_users(*, user_configs: list[OktaUserConfig], provider: Provider) -> dict[EmailAddress, User]:
    user_objects: dict[EmailAddress, User] = {}
    for user_config in user_configs:
        user_objects[user_config.email] = User(
            append_resource_suffix(f"{user_config.first_name.lower()}-{user_config.last_name.lower()}"),
            first_name=user_config.first_name,
            last_name=user_config.last_name,
            login=user_config.username,
            email=user_config.email,
            opts=ResourceOptions(provider=provider),
        )
    return user_objects
