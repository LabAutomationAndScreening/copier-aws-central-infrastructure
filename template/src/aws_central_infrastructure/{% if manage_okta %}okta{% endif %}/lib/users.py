from typing import override

from ephemeral_pulumi_deploy import append_resource_suffix
from pulumi import Input
from pulumi import Resource
from pulumi import ResourceOptions
from pulumi_okta import Provider
from pulumi_okta.user import User
from pulumi_okta.user import UserType
from pydantic import BaseModel
from pydantic import Field
from pydantic import field_validator

from .constants import COMPANY_EMAIL_DOMAIN
from .constants import OKTA_ORG_NAME
from .constants import OktaUserType

type EmailAddress = str


class OktaUserConfig(BaseModel):
    username: str
    email: str
    first_name: str
    last_name: str
    user_type: OktaUserType = Field(default=OktaUserType.DEFAULT, frozen=True)

    @field_validator("email", mode="after")
    @classmethod
    def validate_email(cls, v: str) -> str:
        if not v.endswith(f"@{COMPANY_EMAIL_DOMAIN}"):
            raise ValueError(f"Email must end with @{COMPANY_EMAIL_DOMAIN}")  # noqa: TRY003  # ValueError is appropriate for pydantic field validators
        return v

    @field_validator("user_type")
    @classmethod
    def validate_user_type(cls, v: OktaUserType) -> OktaUserType:
        """Ensure user_type is always DEFAULT for OktaUserConfig."""
        if v != OktaUserType.DEFAULT:
            raise ValueError("OktaUserConfig user_type must be OktaUserType.DEFAULT")  # noqa: TRY003  # ValueError is appropriate for pydantic field validators
        return v


class ExternalUserConfig(OktaUserConfig):
    user_type: OktaUserType = Field(default=OktaUserType.EXTERNAL, frozen=True)
    organization: str  # required; used as aws:PrincipalTag/organization in IAM policies

    @field_validator("organization", mode="after")
    @classmethod
    def validate_organization(cls, v: str) -> str:
        if v.casefold() == OKTA_ORG_NAME.casefold():
            raise ValueError(f"External users cannot use the company organization name ({OKTA_ORG_NAME})")  # noqa: TRY003  # ValueError is appropriate for pydantic field validators
        return v

    @override
    @field_validator("email", mode="after")
    @classmethod
    def validate_email(cls, v: str) -> str:
        if v.endswith(f"@{COMPANY_EMAIL_DOMAIN}"):
            raise ValueError(f"External users cannot have company email domain (@{COMPANY_EMAIL_DOMAIN})")  # noqa: TRY003  # ValueError is appropriate for pydantic field validators
        return v

    @override
    @field_validator("user_type")
    @classmethod
    def validate_user_type(cls, v: OktaUserType) -> OktaUserType:
        """Ensure user_type is always EXTERNAL for ExternalUserConfig."""
        if v != OktaUserType.EXTERNAL:
            raise ValueError("ExternalUserConfig user_type must be OktaUserType.EXTERNAL")  # noqa: TRY003  # ValueError is appropriate for pydantic field validators
        return v


def create_external_user_type(*, provider: Provider) -> UserType:
    return UserType(
        append_resource_suffix("external-user-type"),
        name=OktaUserType.EXTERNAL.value,
        description="External contractors/employees",
        display_name=OktaUserType.EXTERNAL.value,
        opts=ResourceOptions(provider=provider),
    )


def create_users(
    *,
    user_configs: list[OktaUserConfig],
    provider: Provider,
    depends_on: list[Input[Resource]] | None = None,
) -> dict[EmailAddress, User]:
    user_objects: dict[EmailAddress, User] = {}
    for user_config in user_configs:
        user_objects[user_config.email] = User(
            append_resource_suffix(f"{user_config.first_name.lower()}-{user_config.last_name.lower()}"),
            first_name=user_config.first_name,
            last_name=user_config.last_name,
            login=user_config.username,
            email=user_config.email,
            user_type=user_config.user_type,
            organization=user_config.organization if isinstance(user_config, ExternalUserConfig) else None,
            opts=ResourceOptions(provider=provider, depends_on=depends_on),
        )
    return user_objects
