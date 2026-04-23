from uuid import uuid4

import pytest

# separate internal imports from external imports with this comment, because otherwise ruff in the copier template doesn't recognize them as internal and reformats them
from aws_central_infrastructure.github_repos.lib import GithubOrgAdminAsTeamMemberError
from aws_central_infrastructure.github_repos.lib import GithubOrgMembers
from aws_central_infrastructure.github_repos.lib import GithubTeamConfig
from aws_central_infrastructure.github_repos.lib import GithubTeamMemberNotInOrgMembersError
from aws_central_infrastructure.github_repos.lib import fully_configure_teams
from aws_central_infrastructure.github_repos.teams import define_team_configs


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


class TestDefineTeamConfigs:
    def test_all_team_members_are_in_org_members(self):
        root_team = GithubTeamConfig(name="Everyone", description="Everyone in the organization.")
        dev_sec_ops_team_config = GithubTeamConfig(
            name="DevSecOps", description="DevSecOps Team", parent_team=root_team
        )
        team_configs: list[GithubTeamConfig] = [dev_sec_ops_team_config]

        org_members = define_team_configs(configs=team_configs, dev_sec_ops_team_config=dev_sec_ops_team_config)

        # This raises GithubTeamMemberNotInOrgMembersError if any team member is missing from org_members
        fully_configure_teams(configs=team_configs, org_members=org_members, root_team=root_team)


class TestTeamMemberInOrgValidation:
    @pytest.mark.parametrize("role_field", ["members", "maintainers"])
    def test_Given_user_not_in_org__When_fully_configure_teams__Then_error(self, role_field: str):
        root_team = GithubTeamConfig(name=str(uuid4()), description=str(uuid4()))
        user_not_in_root_team = str(uuid4())
        team_name = str(uuid4())
        org_members = GithubOrgMembers(everyone=["someone-else"])
        team = GithubTeamConfig.model_validate(
            {"name": team_name, "description": str(uuid4()), role_field: [user_not_in_root_team]}
        )

        with pytest.raises(GithubTeamMemberNotInOrgMembersError, match=rf"{user_not_in_root_team}.*{team_name}"):
            fully_configure_teams(org_members=org_members, configs=[team], root_team=root_team)

    @pytest.mark.parametrize("role_field", ["members", "maintainers"])
    @pytest.mark.parametrize("org_field", ["everyone", "org_admins"])
    def test_Given_user_in_org__When_fully_configure_teams__Then_no_error(self, role_field: str, org_field: str):
        root_team = GithubTeamConfig(name=str(uuid4()), description=str(uuid4()))
        username = str(uuid4())
        org_members = GithubOrgMembers.model_validate({org_field: [username]})
        team = GithubTeamConfig.model_validate(
            {"name": str(uuid4()), "description": str(uuid4()), role_field: [username]}
        )

        fully_configure_teams(org_members=org_members, configs=[team], root_team=root_team)
