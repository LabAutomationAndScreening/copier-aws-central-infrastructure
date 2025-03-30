from .lib import ROOT_GITHUB_ADMIN_USERNAME
from .lib import GithubOrgMembers
from .lib import GithubTeamConfig


def define_team_configs(
    *, configs: list[GithubTeamConfig], dev_sec_ops_team_config: GithubTeamConfig
) -> GithubOrgMembers:
    """Create the configurations for the repositories.

    example: `configs.append(GithubTeamConfig(name="Manhattan Project Team", description="Working on something big"))`
    """
    _ = configs  # this line can be removed once the first team is appended on to configs, it just temporarily helps linting when the template is instantiated
    _ = dev_sec_ops_team_config  # this line can be removed once any adjustments have been made to the DevSecOps team config
    org_members = GithubOrgMembers(org_admins=[ROOT_GITHUB_ADMIN_USERNAME])
    org_members.everyone.extend([])
    return org_members
