import re
from collections.abc import Collection
from collections.abc import Mapping
from collections.abc import MutableSequence
from collections.abc import Sequence
from typing import TYPE_CHECKING
from typing import Literal
from typing import Self
from typing import override

from ephemeral_pulumi_deploy import append_resource_suffix
from pulumi import ComponentResource
from pulumi import Output
from pulumi import Resource
from pulumi import ResourceOptions
from pulumi_github import Provider
from pulumi_github import Repository
from pulumi_github import RepositoryAutolinkReference
from pulumi_github import RepositoryEnvironment
from pulumi_github import RepositoryEnvironmentDeploymentBranchPolicyArgs
from pulumi_github import RepositoryEnvironmentDeploymentPolicy
from pulumi_github import RepositoryRuleset
from pulumi_github import RepositoryRulesetBypassActorArgs
from pulumi_github import RepositoryRulesetConditionsArgs
from pulumi_github import RepositoryRulesetConditionsRefNameArgs
from pulumi_github import RepositoryRulesetRulesArgs
from pulumi_github import RepositoryRulesetRulesMergeQueueArgs
from pulumi_github import RepositoryRulesetRulesPullRequestArgs
from pulumi_github import RepositoryRulesetRulesRequiredStatusChecksArgs
from pulumi_github import RepositoryRulesetRulesRequiredStatusChecksRequiredCheckArgs
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from aws_central_infrastructure.artifact_stores.internal_packages import create_internal_packages_configs
from aws_central_infrastructure.iac_management.lib import CENTRAL_INFRA_REPO_NAME

from .constants import ALLOW_ADMIN_BYPASS_FOR_AWS_ORG_REPOS
from .constants import AWS_ORG_REPOS_SUCCESSFULLY_IMPORTED
from .constants import AWS_ORGANIZATION_REPO_NAME

if TYPE_CHECKING:
    from aws_central_infrastructure.artifact_stores.lib import RepoPackageClaims


class AutoLinkConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    ticket_prefix: str
    url: str

    @override
    def __hash__(self) -> int:
        return hash((self.ticket_prefix, self.url))


GLOBAL_AUTOLINKS: set[AutoLinkConfig] = set()

type MergeMethod = Literal["merge", "squash", "rebase"]
type MergeQueueMergeMethod = Literal["MERGE", "SQUASH", "REBASE"]
_MERGE_QUEUE_MERGE_METHODS: dict[MergeMethod, MergeQueueMergeMethod] = {
    "merge": "MERGE",
    "squash": "SQUASH",
    "rebase": "REBASE",
}


class MergeQueueConfig(BaseModel):
    grouping_strategy: Literal["ALLGREEN", "HEADGREEN"] = "ALLGREEN"
    check_response_timeout_minutes: int = 60
    max_entries_to_build: int = 5
    max_entries_to_merge: int = 5
    min_entries_to_merge: int = 1
    min_entries_to_merge_wait_minutes: int = 5


class GithubRepoConfig(BaseModel):
    name: str
    visibility: Literal["private", "public"] = "private"
    description: str
    allow_merge_commit: bool = False
    allow_rebase_merge: bool = False
    delete_branch_on_merge: bool = True
    has_issues: bool = True
    has_projects: bool = False
    has_wiki: bool = False
    has_downloads: bool = False  # this should almost never be true (it's been deprecated), but it's here for help importing repos that somehow have it set to true
    allow_auto_merge: bool = True
    squash_merge_commit_title: str = "PR_TITLE"
    squash_merge_commit_message: str = "PR_BODY"
    require_branch_to_be_up_to_date_before_merge: bool = True
    vulnerability_alerts: bool = True
    org_admin_rule_bypass: bool = False
    repo_write_role_rule_bypass: bool = False
    require_code_owner_review: bool = True
    required_approving_review_count: int = 1  # note: if `require_last_push_approval` or `require_code_owner_review` are set to True, then setting this value to 0 will not completely remove the requirement for approval---those two other options can still enforce a requirement of at least 1 approval
    require_last_push_approval: bool = True
    dismiss_stale_reviews_on_push: bool = True
    allow_update_branch: bool = False
    create_repo: bool = (
        True  # set to False if the repo already exists but you just want to apply some other Pulumi to it
    )
    import_existing_repo_using_config: Self | None = None
    create_pypi_publishing_environments: bool = (
        False  # this generally gets automatically updated based on the package claims in the Artifact Stores module
    )
    autolink_references: list[AutoLinkConfig] = Field(default_factory=list[AutoLinkConfig])
    topics: list[str] = Field(default_factory=list)
    allowed_merge_methods: Sequence[MergeMethod] | None = Field(
        default=None,
        description="When left as None, this just uses the boolean flags for allow_merge_commit etc. But it can be set to an explicit list, usually in an attempt to prevent all types of merge commits and only allow fast-forward merges ('merge' cannot be allowed as a value here in that case, typically 'rebase' is used for this field)",
    )
    additional_protected_branches: list[str] = Field(
        default_factory=list,
        description="Branch names or fnmatch globs (e.g. 'development', 'release/*') that should receive the SAME protection ruleset as the default branch. Used by repos following a gitflow SDLC. Each entry is matched as refs/heads/<entry>.",
    )
    review_exempt_teams: list[str] = Field(
        default_factory=list,
        description="Slugs of teams (as produced by GithubTeamConfig.slug) whose members may merge pull requests into the protected branches without any approving review. The other branch rules, including required status checks, still apply. The exemption is keyed on the user performing the merge, not on the pull request author.",
    )
    merge_queue: MergeQueueConfig | None = Field(
        default=None,
        description="When set, merges into the protected branches go through GitHub's merge queue with these settings (the defaults are GitHub's). The queue tests each pull request merged onto the branch tip itself, so require_branch_to_be_up_to_date_before_merge is ignored (it would only block entry into the queue). The queue's merge method is derived from the repository's allowed merge methods, which must resolve to exactly one.",
    )


class ReviewExemptTeamNotFoundError(Exception):
    def __init__(self, *, repo_name: str, team_slug: str, available_team_slugs: list[str]):
        super().__init__(
            f"Repository '{repo_name}' lists review exempt team '{team_slug}', but no team config produces that slug. Available team slugs: {available_team_slugs}"
        )


def _validate_review_exempt_teams(*, configs: Sequence[GithubRepoConfig], team_slugs: Collection[str]) -> None:
    for config in configs:
        for team_slug in config.review_exempt_teams:
            if team_slug not in team_slugs:
                raise ReviewExemptTeamNotFoundError(
                    repo_name=config.name, team_slug=team_slug, available_team_slugs=sorted(team_slugs)
                )


class MergeQueueMergeMethodAmbiguousError(Exception):
    def __init__(self, *, repo_name: str, candidates: Sequence[MergeMethod]):
        super().__init__(
            f"Repository '{repo_name}' enables a merge queue, which needs exactly one merge method, but the repository config allows {list(candidates)}. Narrow allowed_merge_methods or the allow_*_merge flags down to one."
        )


def _merge_queue_merge_method(config: GithubRepoConfig) -> MergeQueueMergeMethod:
    candidates: list[MergeMethod] = []
    if config.allowed_merge_methods is not None:
        candidates.extend(config.allowed_merge_methods)
    else:
        candidates.append("squash")  # always enabled on the repository, there is no config knob for it
        if config.allow_merge_commit:
            candidates.append("merge")
        if config.allow_rebase_merge:
            candidates.append("rebase")
    if len(candidates) != 1:
        raise MergeQueueMergeMethodAmbiguousError(repo_name=config.name, candidates=candidates)
    return _MERGE_QUEUE_MERGE_METHODS[candidates[0]]


def _bypass_actors_or_none(
    actors: MutableSequence[RepositoryRulesetBypassActorArgs],
) -> MutableSequence[RepositoryRulesetBypassActorArgs] | None:
    # supplying an empty list seems to cause problems, so explicitly pass None if no bypass
    if len(actors) == 0:
        return None
    return actors


def _branch_ruleset_targets(
    config: GithubRepoConfig,
) -> list[tuple[str, str, list[str]]]:
    targets: list[tuple[str, str, list[str]]] = [
        (config.name, "Protect Default Branch", ["~DEFAULT_BRANCH"]),
    ]
    seen_suffixes = {config.name}
    for index, branch in enumerate(config.additional_protected_branches):
        sanitized = re.sub(r"[^A-Za-z0-9_.-]+", "-", branch).strip("-")
        suffix = f"{config.name}-{sanitized}"
        if suffix in seen_suffixes:
            suffix = f"{config.name}-{index}-{sanitized}"
        seen_suffixes.add(suffix)
        targets.append((suffix, f"Protect {branch} Branch", [f"refs/heads/{branch}"]))
    return targets


class GithubRepo(ComponentResource):
    def __init__(
        self,
        *,
        config: GithubRepoConfig,
        global_autolinks: set[AutoLinkConfig],
        team_ids: Mapping[str, Output[int]],
        provider: Provider | None = None,
    ):
        super().__init__(
            "labauto:GithubRepo",
            append_resource_suffix(config.name, max_length=150),
            None,
        )
        conditional_repo_depends: list[Resource] = []
        if config.create_repo:
            repo_topics = ["managed-by-aws-central-infrastructure-iac-repo"]
            repo_topics += config.topics

            # TODO: enable GitHub's immutable OIDC subject claims for every repo (ActionsRepositoryOidcSubjectClaimCustomizationTemplate with use_immutable_subject) once the provider supports it: https://github.com/integrations/terraform-provider-github/pull/3582 . That unblocks removing the legacy subject format from the trust policy in create_oidc_assume_role_policy.
            repo = Repository(
                append_resource_suffix(config.name, max_length=150),
                name=config.name,
                visibility=config.visibility
                if config.import_existing_repo_using_config is None
                else config.import_existing_repo_using_config.visibility,
                description=config.description
                if config.import_existing_repo_using_config is None
                else config.import_existing_repo_using_config.description,
                allow_merge_commit=config.allow_merge_commit
                if config.import_existing_repo_using_config is None
                else config.import_existing_repo_using_config.allow_merge_commit,
                allow_rebase_merge=config.allow_rebase_merge
                if config.import_existing_repo_using_config is None
                else config.import_existing_repo_using_config.allow_rebase_merge,
                delete_branch_on_merge=config.delete_branch_on_merge
                if config.import_existing_repo_using_config is None
                else config.import_existing_repo_using_config.delete_branch_on_merge,
                has_issues=config.has_issues
                if config.import_existing_repo_using_config is None
                else config.import_existing_repo_using_config.has_issues,
                has_projects=config.has_projects
                if config.import_existing_repo_using_config is None
                else config.import_existing_repo_using_config.has_projects,
                has_wiki=config.has_wiki
                if config.import_existing_repo_using_config is None
                else config.import_existing_repo_using_config.has_wiki,
                has_downloads=config.has_downloads
                if config.import_existing_repo_using_config is None
                else config.import_existing_repo_using_config.has_downloads,
                allow_auto_merge=config.allow_auto_merge
                if config.import_existing_repo_using_config is None
                else config.import_existing_repo_using_config.allow_auto_merge,
                squash_merge_commit_title=config.squash_merge_commit_title
                if config.import_existing_repo_using_config is None
                else config.import_existing_repo_using_config.squash_merge_commit_title,
                squash_merge_commit_message=config.squash_merge_commit_message
                if config.import_existing_repo_using_config is None
                else config.import_existing_repo_using_config.squash_merge_commit_message,
                auto_init=True if config.import_existing_repo_using_config is None else None,
                vulnerability_alerts=config.vulnerability_alerts
                if config.import_existing_repo_using_config is None
                else config.import_existing_repo_using_config.vulnerability_alerts,
                allow_update_branch=config.allow_update_branch
                if config.import_existing_repo_using_config is None
                else config.import_existing_repo_using_config.allow_update_branch,
                topics=repo_topics if config.import_existing_repo_using_config is None else None,
                opts=ResourceOptions(
                    provider=provider,
                    parent=self,
                    import_=None if config.import_existing_repo_using_config is None else config.name,
                ),
            )
            conditional_repo_depends.append(repo)
        if config.create_pypi_publishing_environments:
            pypi_env = RepositoryEnvironment(
                append_resource_suffix(f"{config.name}-pypi", max_length=150),
                repository=config.name,
                environment="pypi",
                deployment_branch_policy=RepositoryEnvironmentDeploymentBranchPolicyArgs(
                    custom_branch_policies=True,
                    protected_branches=False,  # github does not allow setting protected branches to True when custom_branch_policies is True...not sure why
                ),
                opts=ResourceOptions(parent=self, provider=provider),
            )
            _ = RepositoryEnvironmentDeploymentPolicy(
                append_resource_suffix(f"{config.name}-pypi", max_length=150),
                repository=config.name,
                environment=pypi_env.environment,
                branch_pattern="main",
                opts=ResourceOptions(parent=pypi_env, provider=provider),
            )
            _ = RepositoryEnvironment(
                append_resource_suffix(f"{config.name}-test-pypi", max_length=150),
                repository=config.name,
                environment="testpypi",
                opts=ResourceOptions(parent=self, provider=provider),
            )

        bypass_actors: MutableSequence[RepositoryRulesetBypassActorArgs] = []
        if config.org_admin_rule_bypass:
            bypass_actors.append(
                RepositoryRulesetBypassActorArgs(
                    actor_type="OrganizationAdmin",
                    bypass_mode="pull_request",
                    actor_id=0,  # Pulumi requires some value for actor_id, but it doesn't seem to be used when actor_type is set to Org Admin
                )
            )
        if config.repo_write_role_rule_bypass:
            bypass_actors.append(
                RepositoryRulesetBypassActorArgs(
                    actor_type="RepositoryRole",
                    bypass_mode="pull_request",
                    actor_id=4,  # the ID for the Write Repository Role
                )
            )
        review_bypass_actors: MutableSequence[RepositoryRulesetBypassActorArgs] = [*bypass_actors]
        for team_slug in config.review_exempt_teams:
            review_bypass_actors.append(
                RepositoryRulesetBypassActorArgs(
                    actor_type="Team",
                    bypass_mode="exempt",  # the rule never runs for members of the team. GitHub's auto-merge completion ignores the pull_request bypass mode, so that mode cannot be used for this
                    actor_id=team_ids[team_slug],
                )
            )
        merge_queue: RepositoryRulesetRulesMergeQueueArgs | None = None
        strict_required_status_checks = config.require_branch_to_be_up_to_date_before_merge
        if config.merge_queue is not None:
            merge_queue = RepositoryRulesetRulesMergeQueueArgs(
                merge_method=_merge_queue_merge_method(config),
                grouping_strategy=config.merge_queue.grouping_strategy,
                check_response_timeout_minutes=config.merge_queue.check_response_timeout_minutes,
                max_entries_to_build=config.merge_queue.max_entries_to_build,
                max_entries_to_merge=config.merge_queue.max_entries_to_merge,
                min_entries_to_merge=config.merge_queue.min_entries_to_merge,
                min_entries_to_merge_wait_minutes=config.merge_queue.min_entries_to_merge_wait_minutes,
            )
            strict_required_status_checks = False
        for resource_suffix, ruleset_name, includes in _branch_ruleset_targets(config):
            conditions = RepositoryRulesetConditionsArgs(
                ref_name=RepositoryRulesetConditionsRefNameArgs(includes=includes, excludes=[])
            )
            ruleset_opts = ResourceOptions(provider=provider, parent=self, depends_on=conditional_repo_depends)
            # The review requirements live in their own ruleset so that review-exempt teams can be exempted from them alone. Rulesets on the same branch aggregate, with the most restrictive version of a rule winning
            _ = RepositoryRuleset(
                append_resource_suffix(resource_suffix, max_length=150),
                bypass_actors=_bypass_actors_or_none(bypass_actors),
                name=ruleset_name,
                repository=config.name,
                target="branch",
                enforcement="active",
                conditions=conditions,
                rules=RepositoryRulesetRulesArgs(
                    deletion=True,
                    non_fast_forward=True,
                    required_status_checks=RepositoryRulesetRulesRequiredStatusChecksArgs(
                        required_checks=[
                            RepositoryRulesetRulesRequiredStatusChecksRequiredCheckArgs(
                                context="required-check",
                                integration_id=15368,  # the ID for Github Actions
                            )
                        ],
                        strict_required_status_checks_policy=strict_required_status_checks,
                    ),
                    merge_queue=merge_queue,
                    # a pull request is still required here, but with no review requirements: exemption is per ruleset, so the config's review knobs live only in the "(Review)" ruleset below
                    pull_request=RepositoryRulesetRulesPullRequestArgs(
                        allowed_merge_methods=config.allowed_merge_methods,
                        dismiss_stale_reviews_on_push=False,
                        require_last_push_approval=False,
                        required_approving_review_count=0,
                        require_code_owner_review=False,
                    ),
                ),
                opts=ruleset_opts,
            )
            _ = RepositoryRuleset(
                append_resource_suffix(f"{resource_suffix}-review", max_length=150),
                bypass_actors=_bypass_actors_or_none(review_bypass_actors),
                name=f"{ruleset_name} (Review)",
                repository=config.name,
                target="branch",
                enforcement="active",
                conditions=conditions,
                rules=RepositoryRulesetRulesArgs(
                    pull_request=RepositoryRulesetRulesPullRequestArgs(
                        allowed_merge_methods=config.allowed_merge_methods,
                        dismiss_stale_reviews_on_push=config.dismiss_stale_reviews_on_push,
                        require_last_push_approval=config.require_last_push_approval,
                        required_approving_review_count=config.required_approving_review_count,
                        require_code_owner_review=config.require_code_owner_review,
                    ),
                ),
                opts=ruleset_opts,
            )

        autolinks = global_autolinks | set(config.autolink_references)

        for autolink in autolinks:
            _ = RepositoryAutolinkReference(
                append_resource_suffix(f"{config.name}-{autolink.ticket_prefix}-autolink", max_length=150),
                repository=config.name,
                key_prefix=autolink.ticket_prefix,
                target_url_template=autolink.url,
                opts=ResourceOptions(parent=self, provider=provider, depends_on=conditional_repo_depends),
            )


def create_repos(  # noqa: PLR0913 # this is a lot of arguments, but they're all kwargs
    *,
    configs: list[GithubRepoConfig] | None = None,
    provider: Provider,
    team_ids: Mapping[str, Output[int]],
    include_aws_org_repos: bool = False,
    include_internal_packages: bool = True,
    global_autolinks: set[AutoLinkConfig] | None = None,
) -> None:
    if configs is None:
        configs = []
    if len(configs) == 0:
        return
    resolved_autolinks = GLOBAL_AUTOLINKS if global_autolinks is None else global_autolinks
    if include_aws_org_repos:
        default_imported_repo_config = (  # these are the typical default github settings, so use these when importing a repo
            GithubRepoConfig(
                name="na",
                description="na",
                has_downloads=True,
                has_projects=True,
                allow_auto_merge=False,
                allow_update_branch=False,
                delete_branch_on_merge=False,
                allow_merge_commit=True,
                allow_rebase_merge=True,
            )
        )
        configs.extend(
            [
                GithubRepoConfig(
                    name=CENTRAL_INFRA_REPO_NAME,
                    description="Manage Central/Core Infrastructure for the AWS Organization",
                    org_admin_rule_bypass=ALLOW_ADMIN_BYPASS_FOR_AWS_ORG_REPOS,
                    import_existing_repo_using_config=None
                    if AWS_ORG_REPOS_SUCCESSFULLY_IMPORTED
                    else default_imported_repo_config,
                ),
                GithubRepoConfig(
                    name=AWS_ORGANIZATION_REPO_NAME,
                    description="Managing the company's AWS Organization",
                    org_admin_rule_bypass=ALLOW_ADMIN_BYPASS_FOR_AWS_ORG_REPOS,
                    import_existing_repo_using_config=None
                    if AWS_ORG_REPOS_SUCCESSFULLY_IMPORTED
                    else default_imported_repo_config,
                ),
            ]
        )
    if include_internal_packages:
        package_claims_list: list[RepoPackageClaims] = []
        create_internal_packages_configs(package_claims_list)
        for package_claim in package_claims_list:
            for config in configs:
                if config.name == package_claim.repo_name:
                    config.create_pypi_publishing_environments = True
                    break
    _validate_review_exempt_teams(configs=configs, team_slugs=team_ids.keys())
    for config in configs:
        _ = GithubRepo(config=config, global_autolinks=resolved_autolinks, team_ids=team_ids, provider=provider)
