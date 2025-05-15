from typing import TYPE_CHECKING
from typing import Literal
from typing import Self

import boto3
from ephemeral_pulumi_deploy import append_resource_suffix
from ephemeral_pulumi_deploy import get_config_str
from ephemeral_pulumi_deploy.utils import common_tags_native
from lab_auto_pulumi import GITHUB_DEPLOY_TOKEN_SECRET_NAME
from lab_auto_pulumi import GITHUB_PREVIEW_TOKEN_SECRET_NAME
from pulumi import ComponentResource
from pulumi import ResourceOptions
from pulumi.runtime import is_dry_run
from pulumi_aws_native import secretsmanager
from pulumi_github import Provider
from pulumi_github import Repository
from pulumi_github import RepositoryEnvironment
from pulumi_github import RepositoryEnvironmentDeploymentBranchPolicyArgs
from pulumi_github import RepositoryEnvironmentDeploymentPolicy
from pulumi_github import RepositoryRuleset
from pulumi_github import RepositoryRulesetBypassActorArgs
from pulumi_github import RepositoryRulesetConditionsArgs
from pulumi_github import RepositoryRulesetConditionsRefNameArgs
from pulumi_github import RepositoryRulesetRulesArgs
from pulumi_github import RepositoryRulesetRulesPullRequestArgs
from pulumi_github import RepositoryRulesetRulesRequiredStatusChecksArgs
from pulumi_github import RepositoryRulesetRulesRequiredStatusChecksRequiredCheckArgs
from pydantic import BaseModel

from aws_central_infrastructure.artifact_stores.internal_packages import create_internal_packages_configs
from aws_central_infrastructure.iac_management.lib import CENTRAL_INFRA_REPO_NAME

from .constants import ACTIVELY_IMPORT_AWS_ORG_REPOS
from .constants import AWS_ORG_REPOS_SUCCESSFULLY_IMPORTED
from .constants import AWS_ORGANIZATION_REPO_NAME

if TYPE_CHECKING:
    from collections.abc import Sequence

    from aws_central_infrastructure.artifact_stores.lib import RepoPackageClaims

# preview token permissions: all repositories, Administration:Read, Contents: Read, Environments: Read, OrgMembers: Read
# not sure where the rest of the info went for the deploy token permissions, but also need: Actions: Read (needed for dealing with Environments)


def create_github_provider() -> Provider:
    # Trying to use pulumi_aws GetSecretVersionResult isn't working because it still returns an Output, and Provider requires a string. Even attempting to use apply
    secrets_client = boto3.client("secretsmanager")
    secrets_response = secrets_client.list_secrets(
        Filters=[
            {
                "Key": "name",
                "Values": [GITHUB_PREVIEW_TOKEN_SECRET_NAME if is_dry_run() else GITHUB_DEPLOY_TOKEN_SECRET_NAME],
            }
        ]
    )
    secrets = secrets_response["SecretList"]
    assert len(secrets) == 1, f"expected only 1 matching secret, but found {len(secrets)}"
    assert "ARN" in secrets[0], f"expected 'ARN' in secrets[0], but found {secrets[0].keys()}"
    secret_id = secrets[0]["ARN"]
    token = secrets_client.get_secret_value(SecretId=secret_id)["SecretString"]

    return Provider(  # TODO: figure out why this isn't getting automatically picked up from the config
        "default", token=token, owner=get_config_str("github:owner")
    )


class GithubRepoConfig(BaseModel):
    name: str
    visibility: Literal["private", "public"] = "private"
    description: str
    allow_merge_commit: bool = False
    allow_rebase_merge: bool = False
    delete_branch_on_merge: bool = True
    has_issues: bool = True
    has_projects: bool = False
    has_downloads: bool = False  # this should almost never be true (it's been deprecated), but it's here for help importing repos that somehow have it set to true
    allow_auto_merge: bool = True
    squash_merge_commit_title: str = "PR_TITLE"
    squash_merge_commit_message: str = "PR_BODY"
    require_branch_to_be_up_to_date_before_merge: bool = True
    org_admin_rule_bypass: bool = False
    repo_write_role_rule_bypass: bool = False
    require_code_owner_review: bool = True
    allow_update_branch: bool = False
    create_repo: bool = (
        True  # set to False if the repo already exists but you just want to apply some other Pulumi to it
    )
    import_existing_repo_using_config: Self | None = None
    create_pypi_publishing_environments: bool = (
        False  # this generally gets automatically updated based on the package claims in the Artifact Stores module
    )


class GithubRepo(ComponentResource):
    def __init__(self, *, config: GithubRepoConfig, provider: Provider | None = None):
        super().__init__("labauto:GithubRepo", append_resource_suffix(config.name, max_length=150), None)
        if config.create_repo:
            repo = Repository(
                append_resource_suffix(config.name, max_length=150),
                name=config.name,
                visibility=config.visibility
                if config.import_existing_repo_using_config is None
                else config.import_existing_repo_using_config.visibility,
                description=config.description if config.import_existing_repo_using_config is None else None,
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
                allow_update_branch=config.allow_update_branch
                if config.import_existing_repo_using_config is None
                else config.import_existing_repo_using_config.allow_update_branch,
                topics=["managed-by-aws-central-infrastructure-iac-repo"]
                if config.import_existing_repo_using_config is None
                else None,
                opts=ResourceOptions(
                    provider=provider,
                    parent=self,
                    import_=None if config.import_existing_repo_using_config is None else config.name,
                ),
            )
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

        bypass_actors: Sequence[RepositoryRulesetBypassActorArgs] = []
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
        ruleset_depends = [] if not config.create_repo else [repo]  # type: ignore[reportPossiblyUnboundVariable] # this is a false positive, due to the conditionals in this ternary and the logic above
        _ = RepositoryRuleset(
            append_resource_suffix(config.name, max_length=150),
            bypass_actors=bypass_actors
            if bypass_actors
            else None,  # supplying an empty list seems to cause problems, so explicitly pass None if no bypass
            name="Protect Default Branch",
            repository=config.name,
            target="branch",
            enforcement="active",
            conditions=RepositoryRulesetConditionsArgs(
                ref_name=RepositoryRulesetConditionsRefNameArgs(includes=["~DEFAULT_BRANCH"], excludes=[])
            ),
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
                    strict_required_status_checks_policy=config.require_branch_to_be_up_to_date_before_merge,
                ),
                pull_request=RepositoryRulesetRulesPullRequestArgs(
                    dismiss_stale_reviews_on_push=True,
                    require_last_push_approval=True,
                    required_approving_review_count=1,
                    require_code_owner_review=config.require_code_owner_review,
                    # TODO: set the Allowed Merge Methods once that becomes available through Pulumi
                ),
            ),
            opts=ResourceOptions(provider=provider, parent=self, depends_on=ruleset_depends),
        )


def create_repos(*, configs: list[GithubRepoConfig] | None = None, provider: Provider) -> None:
    # Token permissions needed: All repositories, Administration: Read & write, Environments: Read & write, Contents: read & write
    # After the initial deployment which creates the secret, go in and use the Manual Secrets permission set to update the secret with the real token, then you can create repos
    _ = secretsmanager.Secret(
        append_resource_suffix("github-deploy-access-token"),
        name=GITHUB_DEPLOY_TOKEN_SECRET_NAME,
        description="GitHub access token",
        secret_string="will-need-to-be-manually-entered",  # noqa: S106 # this is not a real secret
        tags=common_tags_native(),
        opts=ResourceOptions(ignore_changes=["secret_string"]),
    )
    _ = secretsmanager.Secret(
        append_resource_suffix("github-preview-access-token"),
        name=GITHUB_PREVIEW_TOKEN_SECRET_NAME,
        description="GitHub access token",
        secret_string="will-need-to-be-manually-entered",  # noqa: S106 # this is not a real secret
        tags=common_tags_native(),
        opts=ResourceOptions(ignore_changes=["secret_string"]),
    )

    if configs is None:
        configs = []
    if not configs:
        return
    if ACTIVELY_IMPORT_AWS_ORG_REPOS or AWS_ORG_REPOS_SUCCESSFULLY_IMPORTED:
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
                    org_admin_rule_bypass=True,
                    import_existing_repo_using_config=None
                    if AWS_ORG_REPOS_SUCCESSFULLY_IMPORTED
                    else default_imported_repo_config,
                ),
                GithubRepoConfig(
                    name=AWS_ORGANIZATION_REPO_NAME,
                    description="Managing the company's AWS Organization",
                    org_admin_rule_bypass=True,
                    import_existing_repo_using_config=None
                    if AWS_ORG_REPOS_SUCCESSFULLY_IMPORTED
                    else default_imported_repo_config,
                ),
            ]
        )
    package_claims_list: list[RepoPackageClaims] = []
    create_internal_packages_configs(package_claims_list)
    for package_claim in package_claims_list:
        for config in configs:
            if config.name == package_claim.repo_name:
                config.create_pypi_publishing_environments = True
                break
    for config in configs:
        _ = GithubRepo(config=config, provider=provider)
