from random import randint
from uuid import uuid4

import pytest

# separate internal imports from external imports with this comment, because otherwise ruff in the copier template doesn't recognize them as internal and reformats them
from aws_central_infrastructure.github_repos.lib import GithubOrgAdminAsTeamMemberError
from aws_central_infrastructure.github_repos.lib import GithubOrganizationRoleNotFoundError
from aws_central_infrastructure.github_repos.lib import GithubOrgMembers
from aws_central_infrastructure.github_repos.lib import GithubOrgRoleUserNotInOrgMembersError
from aws_central_infrastructure.github_repos.lib import GithubTeamConfig
from aws_central_infrastructure.github_repos.lib import GithubTeamMemberNotInOrgMembersError
from aws_central_infrastructure.github_repos.lib import fully_configure_teams
from aws_central_infrastructure.github_repos.lib.teams import _role_id_for
from aws_central_infrastructure.github_repos.lib.teams import ensure_full_repo_name
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


class TestEnsureFullRepoName:
    def test_Given_bare_repo_name__When_ensure_full_repo_name__Then_prefixes_passed_org(self):
        org_name = str(uuid4())
        repo_name = str(uuid4())

        result = ensure_full_repo_name(repo_name, org_name=org_name)

        assert result == f"{org_name}/{repo_name}"

    def test_Given_already_qualified_repo_name__When_ensure_full_repo_name__Then_unchanged(self):
        org_name = str(uuid4())
        already_qualified = f"{uuid4()}/{uuid4()}"

        result = ensure_full_repo_name(already_qualified, org_name=org_name)

        assert result == already_qualified


class TestRootTeamPushRepos:
    def test_Given_push_repos_provided__When_fully_configure_teams__Then_granted_push_on_root_team(self):
        root_team = GithubTeamConfig(name=str(uuid4()), description=str(uuid4()))
        push_repo = str(uuid4())
        org_members = GithubOrgMembers()

        fully_configure_teams(
            org_members=org_members, configs=[], root_team=root_team, root_team_push_repos=[push_repo]
        )

        assert root_team.repo_permissions == {push_repo: "push"}

    def test_Given_no_push_repos__When_fully_configure_teams__Then_root_team_has_no_grants(self):
        root_team = GithubTeamConfig(name=str(uuid4()), description=str(uuid4()))
        org_members = GithubOrgMembers()

        fully_configure_teams(org_members=org_members, configs=[], root_team=root_team, root_team_push_repos=None)

        assert root_team.repo_permissions == {}


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


class TestOrgRoleAssignmentValidation:
    @pytest.mark.parametrize("org_field", ["everyone", "org_admins"])
    def test_Given_assigned_user_in_org__When_fully_configure_teams__Then_no_error(self, org_field: str):
        root_team = GithubTeamConfig(name=str(uuid4()), description=str(uuid4()))
        username = str(uuid4())
        role_name = str(uuid4())
        org_members = GithubOrgMembers.model_validate(
            {org_field: [username], "org_role_assignments": {role_name: [username]}}
        )

        fully_configure_teams(org_members=org_members, configs=[], root_team=root_team)

    def test_Given_assigned_user_not_in_org__When_fully_configure_teams__Then_error(self):
        root_team = GithubTeamConfig(name=str(uuid4()), description=str(uuid4()))
        user_not_in_org = str(uuid4())
        role_name = str(uuid4())
        org_members = GithubOrgMembers(everyone=[str(uuid4())], org_role_assignments={role_name: [user_not_in_org]})

        with pytest.raises(GithubOrgRoleUserNotInOrgMembersError, match=rf"{user_not_in_org}.*{role_name}"):
            fully_configure_teams(org_members=org_members, configs=[], root_team=root_team)


class TestRoleIdLookup:
    def test_Given_role_present__When_role_id_for__Then_returns_its_id(self):
        role_name = str(uuid4())
        role_id = randint(1, 100000)
        role_ids = {str(uuid4()): randint(1, 100000), role_name: role_id}

        result = _role_id_for(role_name=role_name, role_ids=role_ids)

        assert result == role_id

    def test_Given_role_absent__When_role_id_for__Then_error_names_role_and_available(self):
        missing_role_name = str(uuid4())
        present_role_name = str(uuid4())
        role_ids = {present_role_name: randint(1, 100000)}

        with pytest.raises(GithubOrganizationRoleNotFoundError, match=rf"{missing_role_name}.*{present_role_name}"):
            _ = _role_id_for(role_name=missing_role_name, role_ids=role_ids)
