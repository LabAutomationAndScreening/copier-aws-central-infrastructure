import logging

from ..collaborators import define_repository_collaborators
from ..repos import create_repo_configs
from ..teams import define_team_configs
from .collaborators import RepositoryCollaboratorConfig
from .collaborators import create_repository_collaborators
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
