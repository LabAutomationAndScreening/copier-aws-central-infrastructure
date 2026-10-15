from typing import Literal
from typing import Self

from ephemeral_pulumi_deploy import append_resource_suffix
from pulumi import ComponentResource
from pulumi import InvokeOptions
from pulumi import ResourceOptions
from pulumi_github import OrganizationRoleUser
from pulumi_github import Provider
from pulumi_github import Team
from pulumi_github import TeamMembers
from pulumi_github import TeamMembersMemberArgs
from pulumi_github import TeamRepository
from pulumi_github import get_organization_roles
from pydantic import BaseModel
from pydantic import Field

type RepositoryName = str
type GithubRepositoryPermission = Literal["pull", "triage", "push", "maintain", "admin"]
type OrganizationRoleName = str

# Predefined GitHub Enterprise Cloud role granting triage on every repo in the org, including future ones.
ALL_REPOSITORY_TRIAGE_ROLE = "all_repo_triage"


class GithubOrgMembers(BaseModel):
    org_admins: list[str] = Field(default_factory=list)
    everyone: list[str] = Field(default_factory=list)
    org_role_assignments: dict[OrganizationRoleName, list[str]] = Field(
        default_factory=dict[OrganizationRoleName, list[str]]
    )


def ensure_full_repo_name(repo_name: str, *, org_name: str) -> str:
    if "/" in repo_name:
        return repo_name

    return f"{org_name}/{repo_name}"


class GithubTeamConfig(BaseModel):
    name: str
    description: str
    privacy: Literal["secret", "closed"] = "closed"
    maintainers: list[str] = Field(default_factory=list)
    members: list[str] = Field(default_factory=list)
    repo_permissions: dict[RepositoryName, GithubRepositoryPermission] = Field(default_factory=dict)
    parent_team: Self | None = None
    auto_convert_org_admins_to_maintainers: bool = True  # github requires that org admins only be listed as maintainers, with this set to true, any members will automatically be converted to maintainers if they are org admins

    @property
    def slug(self) -> str:
        return self.name.replace(" ", "-").lower()

    @property
    def parent_team_slug(self) -> str | None:
        if self.parent_team is None:
            return None
        return self.parent_team.slug

    @property
    def member_args(self) -> list[TeamMembersMemberArgs]:
        # TODO: confirm that any members are not Org Admins, otherwise Pulumi says odd things can happen https://www.pulumi.com/registry/packages/github/api-docs/teammembership/
        all_members: list[TeamMembersMemberArgs] = []

        all_members.extend(
            TeamMembersMemberArgs(username=maintainer, role="maintainer")
            for maintainer in sorted(set(self.maintainers))
        )
        all_members.extend(
            TeamMembersMemberArgs(username=member, role="member") for member in sorted(set(self.members))
        )

        return all_members


class GithubTeam(ComponentResource):
    def __init__(
        self,
        *,
        config: GithubTeamConfig,
        org_name: str,
        provider: Provider | None = None,
    ):
        super().__init__("labauto:GithubTeam", append_resource_suffix(config.name), None)
        self._config = config
        team = Team(
            append_resource_suffix(config.slug),
            name=config.name,
            description=config.description,
            privacy=config.privacy,
            parent_team_id=config.parent_team_slug,
            opts=ResourceOptions(parent=self, provider=provider),
        )
        self.default_opts = ResourceOptions(parent=self, provider=provider, depends_on=[team])

        _ = TeamMembers(
            append_resource_suffix(config.slug),
            team_id=team.id,
            members=config.member_args,
            opts=self.default_opts,
        )
        for repo_name, permission in config.repo_permissions.items():
            full_repo_name = ensure_full_repo_name(repo_name, org_name=org_name)
            _ = TeamRepository(
                append_resource_suffix(
                    f"{config.slug}-{full_repo_name.replace('/', '-')}",
                    max_length=200,  # arbitrary, not sure if github actually enforces any limit...probably not
                ),
                team_id=team.id,
                repository=repo_name,
                permission=permission,
                opts=self.default_opts,
            )


class GithubOrgAdminAsTeamMemberError(Exception):
    def __init__(self, *, username: str, team_name: str):
        super().__init__(
            f"Org Admin {username} is listed as a member of team {team_name}. GitHub requires that Org Admins only be listed as Maintainers of teams."
        )


class GithubTeamMemberNotInOrgMembersError(Exception):
    def __init__(self, *, username: str, team_name: str):
        super().__init__(
            f"Team member '{username}' in team '{team_name}' is not listed in org_members.everyone or org_members.org_admins. Add them to org_members.everyone first."
        )


class GithubOrgRoleUserNotInOrgMembersError(Exception):
    def __init__(self, *, username: str, role_name: str):
        super().__init__(
            f"User '{username}' assigned the organization role '{role_name}' is not listed in org_members.everyone or org_members.org_admins. Organization roles can only be granted to members of the organization."
        )


class GithubOrganizationRoleNotFoundError(Exception):
    def __init__(self, *, role_name: str, available_role_names: list[str]):
        super().__init__(
            f"Organization role '{role_name}' was not found in this GitHub organization. Available roles: {available_role_names}"
        )


def _validate_team_members_in_org(configs: list[GithubTeamConfig], org_members: GithubOrgMembers) -> None:
    all_org_usernames = set(org_members.org_admins) | set(org_members.everyone)
    for config in configs:
        for member in config.members + config.maintainers:
            if member not in all_org_usernames:
                raise GithubTeamMemberNotInOrgMembersError(username=member, team_name=config.name)


def _role_id_for(*, role_name: str, role_ids: dict[OrganizationRoleName, int]) -> int:
    if role_name not in role_ids:
        raise GithubOrganizationRoleNotFoundError(role_name=role_name, available_role_names=sorted(role_ids.keys()))
    return role_ids[role_name]


def _validate_org_role_users_in_org(org_members: GithubOrgMembers) -> None:
    all_org_usernames = set(org_members.org_admins) | set(org_members.everyone)
    for role_name, usernames in org_members.org_role_assignments.items():
        for username in usernames:
            if username not in all_org_usernames:
                raise GithubOrgRoleUserNotInOrgMembersError(username=username, role_name=role_name)


def fully_configure_teams(
    *,
    configs: list[GithubTeamConfig],
    org_members: GithubOrgMembers,
    root_team: GithubTeamConfig,
    root_team_push_repos: list[str] | None = None,
) -> None:
    _validate_team_members_in_org(configs, org_members)
    _validate_org_role_users_in_org(org_members)

    for config in configs:
        admins_to_convert: list[str] = []
        for admin in org_members.org_admins:
            if admin in config.members:
                if not config.auto_convert_org_admins_to_maintainers:
                    raise GithubOrgAdminAsTeamMemberError(username=admin, team_name=config.name)
                admins_to_convert.append(admin)
        config.maintainers.extend(admins_to_convert)
        for admin in admins_to_convert:
            config.members.remove(admin)
    configs.insert(0, root_team)
    root_team.maintainers.extend(org_members.org_admins)
    root_team.members.extend(org_members.everyone)
    if root_team_push_repos is None:
        return
    for repo_name in root_team_push_repos:
        root_team.repo_permissions[repo_name] = "push"


def create_teams(  # noqa: PLR0913 # this is a lot of arguments, but they're all kwargs
    *,
    configs: list[GithubTeamConfig],
    provider: Provider,
    org_members: GithubOrgMembers,
    root_team: GithubTeamConfig,
    org_name: str,
    root_team_push_repos: list[str] | None = None,
) -> None:
    # Additional Token permissions needed beyond repo: Organization-Members Read/Write
    fully_configure_teams(
        configs=configs,
        org_members=org_members,
        root_team=root_team,
        root_team_push_repos=root_team_push_repos,
    )

    # TODO: confirm all team slugs are unique
    # TODO: confirm there's no duplicate repos listed in the GithubTeamConfig repo permissions (prefer over dict so that there's no silent overriding of permissions)
    for config in configs:
        if config.parent_team is None and config is not root_team:
            config.parent_team = root_team
        _ = GithubTeam(config=config, org_name=org_name, provider=provider)


def create_org_role_assignments(*, org_members: GithubOrgMembers, provider: Provider) -> None:
    """Grant organization-wide roles to individual members.

    The numeric role IDs differ between organizations, so they are looked up by name at deploy time rather
    than hardcoded. This requires the Custom organization roles permission: read on the preview token, and read &
    write on the deploy token in order to assign them. It is distinct from the Members permission.
    """
    if len(org_members.org_role_assignments) == 0:
        return
    available_roles = get_organization_roles(opts=InvokeOptions(provider=provider))
    role_ids = {role.name: role.role_id for role in available_roles.roles}
    for role_name, usernames in org_members.org_role_assignments.items():
        role_id = _role_id_for(role_name=role_name, role_ids=role_ids)
        for username in usernames:
            _ = OrganizationRoleUser(
                append_resource_suffix(f"{role_name.replace(' ', '-').lower()}-{username}", max_length=200),
                login=username,
                role_id=role_id,
                opts=ResourceOptions(provider=provider),
            )
