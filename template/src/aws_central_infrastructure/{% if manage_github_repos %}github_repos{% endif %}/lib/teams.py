from typing import Literal

from ephemeral_pulumi_deploy import append_resource_suffix
from pulumi import ComponentResource
from pulumi import ResourceOptions
from pulumi_github import Provider
from pulumi_github import Team
from pulumi_github import TeamMembers
from pulumi_github import TeamMembersMemberArgs
from pulumi_github import TeamRepository
from pydantic import BaseModel
from pydantic import Field

from aws_central_infrastructure.iac_management.lib import CENTRAL_INFRA_GITHUB_ORG_NAME
from aws_central_infrastructure.iac_management.lib import CENTRAL_INFRA_REPO_NAME

type RepositoryName = str
type GithubRepositoryPermission = Literal["pull", "triage", "push", "maintain", "admin"]


class GithubOrgMembers(BaseModel):
    org_admins: list[str] = Field(default_factory=list)
    everyone: list[str] = Field(default_factory=list)


def ensure_full_repo_name(repo_name: str) -> str:
    if "/" in repo_name:
        return repo_name

    return f"{CENTRAL_INFRA_GITHUB_ORG_NAME}/{repo_name}"


class GithubTeamConfig(BaseModel):
    name: str
    description: str
    privacy: Literal["secret", "closed"] = "closed"
    maintainers: list[str] = Field(default_factory=list)
    members: list[str] = Field(default_factory=list)
    repo_permissions: dict[RepositoryName, GithubRepositoryPermission] = Field(default_factory=dict)

    @property
    def slug(self) -> str:
        return self.name.replace(" ", "-").lower()

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
    def __init__(self, *, config: GithubTeamConfig, provider: Provider | None = None):
        super().__init__("labauto:GithubTeam", append_resource_suffix(config.name), None)
        self._config = config
        team = Team(
            append_resource_suffix(config.slug),
            name=config.name,
            description=config.description,
            privacy=config.privacy,
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
            full_repo_name = ensure_full_repo_name(repo_name)
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


def create_teams(
    *,
    configs: list[GithubTeamConfig],
    provider: Provider,
    org_members: GithubOrgMembers,
    root_team: GithubTeamConfig,
) -> None:
    # Additional Token permissions needed beyond repo: Organization-Members Read/Write
    configs.insert(0, root_team)
    root_team.maintainers.extend(org_members.org_admins)
    root_team.members.extend(org_members.everyone)
    for repo_name in (
        CENTRAL_INFRA_REPO_NAME,
        "aws-organization",  # TODO: parametrize this, don't hardcode the repo name
    ):
        root_team.repo_permissions[repo_name] = "push"

    # TODO: confirm all team slugs are unique
    # TODO: confirm there's no duplicate repos listed in the GithubTeamConfig repo permissions (prefer over dict so that there's no silent overriding of permissions)
    for config in configs:
        _ = GithubTeam(config=config, provider=provider)
