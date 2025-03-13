from collections.abc import Iterable
from collections.abc import Sequence
from typing import Literal

import boto3
from ephemeral_pulumi_deploy import append_resource_suffix
from ephemeral_pulumi_deploy import get_config_str
from ephemeral_pulumi_deploy.utils import common_tags_native
from pulumi import ComponentResource
from pulumi import ResourceOptions
from pulumi.runtime import is_dry_run
from pulumi_aws_native import secretsmanager
from pulumi_github import Provider
from pulumi_github import Repository
from pulumi_github import RepositoryRuleset
from pulumi_github import RepositoryRulesetBypassActorArgs
from pulumi_github import RepositoryRulesetConditionsArgs
from pulumi_github import RepositoryRulesetConditionsRefNameArgs
from pulumi_github import RepositoryRulesetRulesArgs
from pulumi_github import RepositoryRulesetRulesPullRequestArgs
from pulumi_github import RepositoryRulesetRulesRequiredStatusChecksArgs
from pulumi_github import RepositoryRulesetRulesRequiredStatusChecksRequiredCheckArgs
from pydantic import BaseModel


class GithubRepoConfig(BaseModel, frozen=True):
    name: str
    visibility: Literal["private", "public"] = "private"
    description: str
    allow_merge_commit: bool = False
    allow_rebase_merge: bool = False
    delete_branch_on_merge: bool = True
    has_issues: bool = True
    allow_auto_merge: bool = True
    squash_merge_commit_title: str = "PR_TITLE"
    squash_merge_commit_message: str = "PR_BODY"
    require_branch_to_be_up_to_date_before_merge: bool = True
    org_admin_rule_bypass: bool = False


class GithubRepo(ComponentResource):
    def __init__(self, *, config: GithubRepoConfig, provider: Provider | None = None):
        super().__init__("labauto:GithubRepo", append_resource_suffix(config.name), None)
        repo = Repository(
            append_resource_suffix(config.name),
            name=config.name,
            visibility=config.visibility,
            description=config.description,
            allow_merge_commit=config.allow_merge_commit,
            allow_rebase_merge=config.allow_rebase_merge,
            delete_branch_on_merge=config.delete_branch_on_merge,
            has_issues=config.has_issues,
            allow_auto_merge=config.allow_auto_merge,
            squash_merge_commit_title=config.squash_merge_commit_title,
            squash_merge_commit_message=config.squash_merge_commit_message,
            auto_init=True,
            topics=["managed-by-aws-central-infrastructure-iac-repo"],
            opts=ResourceOptions(provider=provider, parent=self),
        )
        bypass_actors: Sequence[RepositoryRulesetBypassActorArgs] | None = None
        if config.org_admin_rule_bypass:
            bypass_actors = [
                RepositoryRulesetBypassActorArgs(
                    actor_type="OrganizationAdmin",
                    bypass_mode="pull_request",
                    actor_id=1,  # Pulumi requires some value for actor_id, but it doesn't seem to be used when actor_type is set to Org Admin
                )
            ]
        _ = RepositoryRuleset(
            append_resource_suffix(config.name),
            bypass_actors=bypass_actors,
            name="Protect Default Branch",
            repository=repo.name,
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
                    # TODO: set the Allowed Merge Methods once that becomes available through Pulumi
                ),
            ),
            opts=ResourceOptions(provider=provider, parent=self, depends_on=[repo]),
        )


def create_repos(configs: Iterable[GithubRepoConfig] | None = None) -> None:
    # Token permissions needed: All repositories, Administration: Read & write, Environments: Read & write, Contents: read & write
    # After the initial deployment which creates the secret, go in and use the Manual Secrets permission set to update the secret with the real token, then you can create repos
    _ = secretsmanager.Secret(
        append_resource_suffix("github-access-token"),
        name="/manually-entered-secrets/iac/github-access-token",
        description="GitHub access token",
        secret_string="will-need-to-be-manually-entered",  # noqa: S106 # this is not a real secret
        tags=common_tags_native(),
        opts=ResourceOptions(ignore_changes=["secret_string"]),
    )

    if configs is None:
        configs = []
    if not configs:
        return
    token = "fake"  # noqa: S105 # this is not a real secret
    if not is_dry_run():  # the Pulumi Preview process doesn't seem to actually invoke the Github API, so only grant the Deploy role the ability to get this secret and ignore it during Preview
        # Trying to use pulumi_aws GetSecretVersionResult isn't working because it still returns an Output, and Provider requires a string. Even attempting to use apply
        secrets_client = boto3.client("secretsmanager")
        secrets_response = secrets_client.list_secrets(
            Filters=[{"Key": "name", "Values": ["/manually-entered-secrets/iac/github-access-token"]}]
        )
        secrets = secrets_response["SecretList"]
        assert len(secrets) == 1, f"expected only 1 matching secret, but found {len(secrets)}"
        assert "ARN" in secrets[0], f"expected 'ARN' in secrets[0], but found {secrets[0].keys()}"
        secret_id = secrets[0]["ARN"]
        token = secrets_client.get_secret_value(SecretId=secret_id)["SecretString"]

    provider = Provider(  # TODO: figure out why this isn't getting automatically picked up from the config
        "default", token=token, owner=get_config_str("github:owner")
    )

    for config in configs:
        _ = GithubRepo(config=config, provider=provider)
