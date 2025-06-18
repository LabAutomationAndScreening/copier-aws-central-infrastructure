import logging

from ephemeral_pulumi_deploy import append_resource_suffix
from ephemeral_pulumi_deploy.utils import common_tags_native
from pulumi import ResourceOptions
from pulumi_aws_native import secretsmanager

from ..apps import define_app_configs
from ..groups import define_group_configs
from ..users import define_user_configs
from .apps import SamlAppConfig
from .apps import create_apps
from .constants import OKTA_TOKENS_CREATED
from .groups import OktaGroupConfig
from .groups import create_groups
from .provider import OKTA_DEPLOY_TOKEN_SECRET_NAME
from .provider import OKTA_PREVIEW_TOKEN_SECRET_NAME
from .provider import create_okta_provider
from .users import OktaUserConfig
from .users import create_users

logger = logging.getLogger(__name__)


def pulumi_program() -> None:
    """Execute creating the stack."""
    _ = secretsmanager.Secret(
        append_resource_suffix("okta-deploy-access-token"),
        name=OKTA_DEPLOY_TOKEN_SECRET_NAME,
        description="Okta access token",
        secret_string="will-need-to-be-manually-entered",  # noqa: S106 # this is not a real secret
        tags=common_tags_native(),
        opts=ResourceOptions(ignore_changes=["secret_string"]),
    )
    _ = secretsmanager.Secret(
        append_resource_suffix("okta-preview-access-token"),
        name=OKTA_PREVIEW_TOKEN_SECRET_NAME,
        description="Okta access token (preview permissions)",
        secret_string="will-need-to-be-manually-entered",  # noqa: S106 # this is not a real secret
        tags=common_tags_native(),
        opts=ResourceOptions(ignore_changes=["secret_string"]),
    )
    user_configs: list[OktaUserConfig] = []
    define_user_configs(user_configs)
    group_configs: list[OktaGroupConfig] = []
    define_group_configs(group_configs)
    app_configs: list[SamlAppConfig] = []
    define_app_configs(app_configs)
    if OKTA_TOKENS_CREATED:
        provider = create_okta_provider()
        user_objects = create_users(user_configs=user_configs, provider=provider)
        group_objects = create_groups(group_configs=group_configs, user_objects=user_objects, provider=provider)
        create_apps(app_configs=app_configs, group_objects=group_objects, provider=provider)
