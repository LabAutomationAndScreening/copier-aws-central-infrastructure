from .lib import GithubOrgMembers
from .lib import GithubTeamConfig


def define_team_configs(*, configs: list[GithubTeamConfig]) -> GithubOrgMembers:
    """Create the configurations for the repositories.

    example: `configs.append(GithubTeamConfig(name="Manhattan Project Team", description="Working on something big"))`
    """
    _ = configs  # this line can be removed once the first team is appended on to configs, it just temporarily helps linting when the template is instantiated
    org_members = GithubOrgMembers(org_admins=[])
    org_members.everyone.extend([])
    return org_members
