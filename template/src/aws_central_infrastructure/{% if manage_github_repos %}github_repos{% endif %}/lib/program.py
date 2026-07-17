import logging

from ephemeral_pulumi_deploy import append_resource_suffix
from ephemeral_pulumi_deploy.utils import common_tags_native
from pulumi import ResourceOptions
from pulumi_aws_native import secretsmanager

from aws_central_infrastructure.iac_management.lib import CENTRAL_INFRA_GITHUB_ORG_NAME
from aws_central_infrastructure.iac_management.lib import CENTRAL_INFRA_REPO_NAME

from ..collaborators import define_repository_collaborators
from ..repos import create_repo_configs
from ..teams import define_team_configs
from .collaborators import RepositoryCollaboratorConfig
from .collaborators import create_repository_collaborators
from .constants import ACTIVELY_IMPORT_AWS_ORG_REPOS
from .constants import AWS_ORG_REPOS_SUCCESSFULLY_IMPORTED
from .constants import AWS_ORGANIZATION_REPO_NAME
from .constants import GITHUB_TOKENS_CREATED
from .constants import USE_REPO_SECRET_FOR_GITHUB_IAC_TOKENS
from .create_provider import create_github_provider
from .create_provider import github_token_secret_name
from .repo import GLOBAL_AUTOLINKS
from .repo import AutoLinkConfig
from .repo import GithubRepoConfig
from .repo import create_repos
from .teams import GithubOrgMembers
from .teams import GithubTeamConfig
from .teams import create_teams

logger = logging.getLogger(__name__)


def build_org_github_resources(  # noqa: PLR0913 # this is a lot of arguments, but they're all kwargs
    *,
    org_name: str,
    repo_configs: list[GithubRepoConfig],
    team_configs: list[GithubTeamConfig],
    collaborator_configs: list[RepositoryCollaboratorConfig],
    org_members: GithubOrgMembers,
    root_team: GithubTeamConfig,
    include_aws_org_repos: bool,
    include_internal_packages: bool,
    root_team_push_repos: list[str] | None,
    global_autolinks: set[AutoLinkConfig] | None,
    tokens_created: bool,
) -> None:
    if not USE_REPO_SECRET_FOR_GITHUB_IAC_TOKENS:
        # Token permissions needed: All repositories, Administration: Read & write, Environments: Read & write, Contents: read & write.  Organization: Members Read&Write
        # After the initial deployment which creates the secret, go in and use the Manual Secrets permission set to update the secret with the real token, then you can create repos
        _ = secretsmanager.Secret(
            append_resource_suffix("github-deploy-access-token"),
            name=github_token_secret_name(org_name=org_name, is_preview=False),
            description="GitHub access token",
            secret_string="will-need-to-be-manually-entered",  # noqa: S106 # this is not a real secret
            tags=common_tags_native(),
            opts=ResourceOptions(ignore_changes=["secret_string"]),
        )
        _ = secretsmanager.Secret(
            append_resource_suffix("github-preview-access-token"),
            name=github_token_secret_name(org_name=org_name, is_preview=True),
            description="GitHub access token",
            secret_string="will-need-to-be-manually-entered",  # noqa: S106 # this is not a real secret
            tags=common_tags_native(),
            opts=ResourceOptions(ignore_changes=["secret_string"]),
        )
    if not tokens_created:
        return
    provider = create_github_provider(org_name=org_name)
    create_repos(
        configs=repo_configs,
        provider=provider,
        include_aws_org_repos=include_aws_org_repos,
        include_internal_packages=include_internal_packages,
        global_autolinks=global_autolinks,
    )
    create_teams(
        configs=team_configs,
        provider=provider,
        org_members=org_members,
        root_team=root_team,
        org_name=org_name,
        root_team_push_repos=root_team_push_repos,
    )
    create_repository_collaborators(configs=collaborator_configs, provider=provider)


def pulumi_program() -> None:
    """Execute creating the stack for the central company organization."""
    repo_configs: list[GithubRepoConfig] = []
    create_repo_configs(repo_configs)
    root_team = GithubTeamConfig(
        name="Everyone",
        description="Everyone in the organization, the root of all teams.",
    )
    dev_sec_ops_team_config = GithubTeamConfig(name="DevSecOps", description="DevSecOps Team", parent_team=root_team)
    team_configs: list[GithubTeamConfig] = [dev_sec_ops_team_config]
    org_members = define_team_configs(configs=team_configs, dev_sec_ops_team_config=dev_sec_ops_team_config)
    collaborator_configs: list[RepositoryCollaboratorConfig] = []
    define_repository_collaborators(configs=collaborator_configs)
    root_team_push_repos = (
        [
            CENTRAL_INFRA_REPO_NAME,
            AWS_ORGANIZATION_REPO_NAME,
        ]
        if AWS_ORG_REPOS_SUCCESSFULLY_IMPORTED
        else None
    )
    build_org_github_resources(
        org_name=CENTRAL_INFRA_GITHUB_ORG_NAME,
        repo_configs=repo_configs,
        team_configs=team_configs,
        collaborator_configs=collaborator_configs,
        org_members=org_members,
        root_team=root_team,
        include_aws_org_repos=ACTIVELY_IMPORT_AWS_ORG_REPOS or AWS_ORG_REPOS_SUCCESSFULLY_IMPORTED,
        include_internal_packages=True,
        root_team_push_repos=root_team_push_repos,
        global_autolinks=GLOBAL_AUTOLINKS,
        tokens_created=GITHUB_TOKENS_CREATED,
    )
