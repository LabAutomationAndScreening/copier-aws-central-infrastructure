from uuid import uuid4

import pytest

# separate internal imports from external imports with this comment, because otherwise ruff in the copier template doesn't recognize them as internal and reformats them
from aws_central_infrastructure.github_repos.lib import GithubOrgAdminAsTeamMemberError
from aws_central_infrastructure.github_repos.lib import GithubOrgMembers
from aws_central_infrastructure.github_repos.lib import GithubTeamConfig
from aws_central_infrastructure.github_repos.lib import fully_configure_teams


class TestFullyConfigureTeams:
    def test_Given_auto_set_admins_as_members_left_as_default_kwarg_value__When_org_member_listed_as_member__Then_switched_to_maintainer(
        self,
    ):
        root_team = GithubTeamConfig(name=str(uuid4()), description=str(uuid4()))
        admin_username = str(uuid4())
        team_name = str(uuid4())
        org_members = GithubOrgMembers(org_admins=[admin_username])
        team = GithubTeamConfig(
            name=team_name,
            description=str(uuid4()),
            members=[admin_username],
        )

        fully_configure_teams(org_members=org_members, configs=[team], root_team=root_team)

        assert team.maintainers == [admin_username]
        assert team.members == []

    def test_Given_auto_set_admins_as_members_False__When_org_member_listed_as_team_member__Then_error(self):
        root_team = GithubTeamConfig(name=str(uuid4()), description=str(uuid4()))
        admin_username = str(uuid4())
        team_name = str(uuid4())
        org_members = GithubOrgMembers(org_admins=[admin_username])
        team = GithubTeamConfig(
            name=team_name,
            description=str(uuid4()),
            members=[admin_username],
            auto_convert_org_admins_to_maintainers=False,
        )

        with pytest.raises(GithubOrgAdminAsTeamMemberError, match=rf"{admin_username}.*{team_name}"):
            fully_configure_teams(org_members=org_members, configs=[team], root_team=root_team)
