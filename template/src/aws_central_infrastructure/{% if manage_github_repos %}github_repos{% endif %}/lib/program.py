import logging

from ephemeral_pulumi_deploy import append_resource_suffix
from ephemeral_pulumi_deploy.utils import common_tags_native
from lab_auto_pulumi import GITHUB_DEPLOY_TOKEN_SECRET_NAME
from lab_auto_pulumi import GITHUB_PREVIEW_TOKEN_SECRET_NAME
from pulumi import ResourceOptions
from pulumi_aws_native import secretsmanager

from ..collaborators import define_repository_collaborators
from ..repos import create_repo_configs
from ..teams import define_team_configs
from .collaborators import RepositoryCollaboratorConfig
from .collaborators import create_repository_collaborators
from .constants import GITHUB_TOKENS_CREATED
from .constants import USE_REPO_SECRET_FOR_GITHUB_IAC_TOKENS
from .repo import GithubRepoConfig
from .repo import create_github_provider
from .repo import create_repos
from .teams import GithubTeamConfig
from .teams import create_teams

logger = logging.getLogger(__name__)


def pulumi_program() -> None:
    """Execute creating the stack."""
    repo_configs: list[GithubRepoConfig] = []
    create_repo_configs(repo_configs)
    if not USE_REPO_SECRET_FOR_GITHUB_IAC_TOKENS:
        # Token permissions needed: All repositories, Administration: Read & write, Environments: Read & write, Contents: read & write
        # After the initial deployment which creates the secret, go in and use the Manual Secrets permission set to update the secret with the real token, then you can create repos
        _ = secretsmanager.Secret(
            append_resource_suffix("github-deploy-access-token"),
            name=GITHUB_DEPLOY_TOKEN_SECRET_NAME,
            description="GitHub access token",
            secret_string="will-need-to-be-manually-entered",  # noqa: S106 # this is not a real secret
            tags=common_tags_native(),
            opts=ResourceOptions(ignore_changes=["secret_string"]),
        )
        _ = secretsmanager.Secret(
            append_resource_suffix("github-preview-access-token"),
            name=GITHUB_PREVIEW_TOKEN_SECRET_NAME,
            description="GitHub access token",
            secret_string="will-need-to-be-manually-entered",  # noqa: S106 # this is not a real secret
            tags=common_tags_native(),
            opts=ResourceOptions(ignore_changes=["secret_string"]),
        )
    if not GITHUB_TOKENS_CREATED:
        return
    provider = create_github_provider()
    root_team = GithubTeamConfig(name="Everyone", description="Everyone in the organization, the root of all teams.")
    dev_sec_ops_team_config = GithubTeamConfig(name="DevSecOps", description="DevSecOps Team", parent_team=root_team)
    team_configs: list[GithubTeamConfig] = []
    collaborator_configs: list[RepositoryCollaboratorConfig] = []
    create_repos(configs=repo_configs, provider=provider)
    org_members = define_team_configs(configs=team_configs, dev_sec_ops_team_config=dev_sec_ops_team_config)
    create_teams(configs=team_configs, provider=provider, org_members=org_members, root_team=root_team)
    define_repository_collaborators(configs=collaborator_configs)
    create_repository_collaborators(configs=collaborator_configs, provider=provider)
