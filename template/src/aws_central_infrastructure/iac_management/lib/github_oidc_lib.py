from typing import Self
from typing import TypedDict
from typing import TypeGuard

from ephemeral_pulumi_deploy import get_config_str
from ephemeral_pulumi_deploy.utils import common_tags_native
from ephemeral_pulumi_deploy.utils import get_aws_account_id
from lab_auto_pulumi import AwsAccountId
from lab_auto_pulumi import AwsLogicalWorkload
from pulumi import ComponentResource
from pulumi import Output
from pulumi import Resource
from pulumi import ResourceOptions
from pulumi_aws.iam import AwaitableGetPolicyDocumentResult
from pulumi_aws.iam import GetPolicyDocumentStatementArgs
from pulumi_aws.iam import GetPolicyDocumentStatementConditionArgs
from pulumi_aws.iam import GetPolicyDocumentStatementPrincipalArgs
from pulumi_aws.iam import get_open_id_connect_provider
from pulumi_aws.iam import get_policy_document
from pulumi_aws_native import Provider
from pulumi_aws_native import iam
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import field_validator
from pydantic import model_validator

from .constants import GITHUB_ORG_IDS

GITHUB_OIDC_URL = "https://token.actions.githubusercontent.com"
IAM_STRING_LIKE_WILDCARD_CHARS = "*?"
ANY_SUBJECT_CONTEXT = "*"
CODE_ARTIFACT_SERVICE_BEARER_STATEMENT = GetPolicyDocumentStatementArgs(
    sid="GetCodeArtifactAuthToken",
    effect="Allow",
    resources=["*"],
    actions=["sts:GetServiceBearerToken"],
    conditions=[
        GetPolicyDocumentStatementConditionArgs(
            variable="sts:AWSServiceName",
            test="StringEquals",
            values=["codeartifact.amazonaws.com"],
        )
    ],
)
ECR_AUTH_STATEMENT = GetPolicyDocumentStatementArgs(
    effect="Allow",
    sid="EcrAuth",
    actions=[
        "ecr:GetAuthorizationToken",
    ],
    resources=["*"],
)
# pylint: disable=duplicate-code
# TODO: decide whether ECR policy statements belong in a shared library
ECR_PULL_STATEMENT = GetPolicyDocumentStatementArgs(
    sid="EcrPull",
    effect="Allow",
    actions=[
        "ecr:BatchGetImage",
        "ecr:GetDownloadUrlForLayer",
        "ecr:DescribeImages",
    ],
    resources=["*"],
)
# pylint: enable=duplicate-code
PULL_FROM_CENTRAL_ECRS_STATEMENTS = [ECR_AUTH_STATEMENT, ECR_PULL_STATEMENT]


def principal_in_org_condition(org_id: str) -> GetPolicyDocumentStatementConditionArgs:
    return GetPolicyDocumentStatementConditionArgs(
        values=[org_id],
        variable="aws:PrincipalOrgID",
        test="StringEquals",
    )


class CommonOidcConfigKwargs(TypedDict):
    role_name: str
    repo_org: str
    repo_name: str
    managed_policy_arns: list[str]
    role_policies: list[iam.RolePolicyArgs]


def _none_if_empty[T](items: list[T]) -> list[T] | None:
    if len(items) == 0:
        return None
    return items


def _is_specific_restriction(restriction: str | None) -> TypeGuard[str]:
    if restriction is None:
        return False
    if restriction == ANY_SUBJECT_CONTEXT:
        return False
    return True


class GithubOidcConfig(BaseModel):
    aws_account_id: str
    role_name: str
    repo_org: str
    repo_name: str
    managed_policy_arns: list[str] = Field(default_factory=list)
    restrictions: str | None = None
    role_policies: list[iam.RolePolicyArgs] = Field(default_factory=list)
    role_resource_name_prefix: str = "github-oidc--"

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @field_validator("repo_org")
    @classmethod
    def _require_known_org_id(cls, value: str) -> str:
        if value not in GITHUB_ORG_IDS:
            raise ValueError(  # noqa: TRY003 # pydantic validators must raise ValueError for it to be converted into a ValidationError
                f'GitHub org {value!r} has no entry in GITHUB_ORG_IDS; add it (find the ID in the "id" field at https://api.github.com/orgs/{value} or with `gh api orgs/{value} --jq .id`)'
            )
        return value

    @field_validator("restrictions")
    @classmethod
    def _allow_only_bare_wildcard(cls, value: str | None) -> str | None:
        if not _is_specific_restriction(value):
            return value
        for wildcard_char in IAM_STRING_LIKE_WILDCARD_CHARS:
            if wildcard_char in value:
                raise ValueError(f"OIDC restriction {value!r} must not contain wildcard characters")  # noqa: TRY003 # pydantic validators must raise ValueError for it to be converted into a ValidationError
        return value

    @model_validator(mode="after")
    def _reject_wildcard_repo_name_when_restricted(self) -> Self:
        if not _is_specific_restriction(self.restrictions):
            return self
        for wildcard_char in IAM_STRING_LIKE_WILDCARD_CHARS:
            if wildcard_char in self.repo_name:
                raise ValueError(  # noqa: TRY003 # pydantic validators must raise ValueError for it to be converted into a ValidationError
                    f"OIDC repo name {self.repo_name!r} must not contain wildcard characters when restricted to {self.restrictions!r}"
                )
        return self

    def create_role(self, *, provider_arn: str, parent: Resource | None = None) -> iam.Role:
        return iam.Role(
            f"{self.role_resource_name_prefix}{self.role_name}",
            role_name=self.role_name,
            assume_role_policy_document=create_oidc_assume_role_policy(
                oidc_config=self, provider_arn=provider_arn
            ).json,
            managed_policy_arns=_none_if_empty(self.managed_policy_arns),
            policies=_none_if_empty(self.role_policies),
            tags=common_tags_native(),
            opts=ResourceOptions(parent=parent),
        )


def create_oidc_assume_role_policy(
    *, oidc_config: GithubOidcConfig, provider_arn: str
) -> AwaitableGetPolicyDocumentResult:
    if oidc_config.restrictions is None:
        subject_context = ANY_SUBJECT_CONTEXT
    else:
        subject_context = oidc_config.restrictions
    # TODO: remove the legacy subject format once use_immutable_subject is enabled for every repo in every org in GITHUB_ORG_IDS. GitHub has announced no retirement date; existing repos keep the legacy format until opted in. Check that nothing else still trusts only the legacy format before opting in.
    legacy_subject = f"repo:{oidc_config.repo_org}/{oidc_config.repo_name}:{subject_context}"
    # Immutable subject format, the default for repos created after 2026-07-15: https://github.blog/changelog/2026-04-23-immutable-subject-claims-for-github-actions-oidc-tokens/
    # TODO: pin the exact repo ID instead of the `@*` wildcard, sourced from the github-repos stack outputs (requires iac-management to run after github-repos) or a GitHub API lookup.
    # The wildcard is acceptable for now: the org ID is pinned, so a renamed or squatted org cannot match; the literal `@` after the repo name stops similarly prefixed repo names from matching;
    # the remaining exposure is a repo in this org being deleted and recreated under the same name, which requires an org admin, who can already edit these roles; and the legacy format kept alongside is weaker anyway.
    immutable_subject = f"repo:{oidc_config.repo_org}@{GITHUB_ORG_IDS[oidc_config.repo_org]}/{oidc_config.repo_name}@*:{subject_context}"
    return get_policy_document(
        statements=[
            GetPolicyDocumentStatementArgs(
                effect="Allow",
                principals=[GetPolicyDocumentStatementPrincipalArgs(type="Federated", identifiers=[provider_arn])],
                actions=["sts:AssumeRoleWithWebIdentity"],
                conditions=[
                    GetPolicyDocumentStatementConditionArgs(
                        test="StringLike",
                        variable="token.actions.githubusercontent.com:sub",
                        values=[legacy_subject, immutable_subject],
                    ),
                    GetPolicyDocumentStatementConditionArgs(
                        test="StringEquals",
                        variable="token.actions.githubusercontent.com:aud",
                        values=["sts.amazonaws.com"],
                    ),
                ],
            )
        ]
    )


def create_kms_policy() -> iam.RolePolicyArgs:
    kms_key_arn = get_config_str("proj:kms_key_id")
    return iam.RolePolicyArgs(
        policy_name="InfraKmsDecryptAndStateBucketWrite",  # Even when running a Preview, for a stack that has never been instantiated, Pulumi needs to create some files in the S3 bucket
        policy_document=get_policy_document(
            statements=[
                GetPolicyDocumentStatementArgs(
                    sid="UseCentralKmsKeyForSecretsInStateFile",
                    effect="Allow",
                    actions=[
                        "kms:Decrypt",
                        "kms:Encrypt",  # unclear why Encrypt is required to run a Preview...but Pulumi gives an error if it's not included
                    ],
                    resources=[kms_key_arn],
                ),
                GetPolicyDocumentStatementArgs(  # TODO: add this to the aws-organizations repo roles
                    sid="CreateMetadataAndLocks",
                    effect="Allow",
                    actions=[
                        "s3:PutObject",
                    ],
                    resources=[
                        f"arn:aws:s3:::{get_config_str('proj:backend_bucket_name')}/${{aws:PrincipalAccount}}/*"
                    ],
                ),
                GetPolicyDocumentStatementArgs(  # TODO: add this to the aws-organizations repo roles
                    sid="RemoveLock",
                    effect="Allow",
                    actions=[
                        "s3:DeleteObject",
                        "s3:DeleteObjectVersion",
                    ],
                    resources=[
                        f"arn:aws:s3:::{get_config_str('proj:backend_bucket_name')}/${{aws:PrincipalAccount}}/*/.pulumi/locks/*.json"
                    ],
                ),
            ]
        ).json,
    )


def create_assume_dns_delegate_preview_policy(*, account_name: str) -> iam.RolePolicyArgs:
    from aws_central_infrastructure.central_networking.lib.role_names import (  # noqa: PLC0415 Imported lazily: central_networking.lib depends on iac_management.lib at module load, so a top-level import here would create a circular import between the two packages.
        dns_delegate_preview_role_name,
    )

    # The dns-delegate-preview-* roles (created per account in central_networking) are named after the
    # account they delegate to, so scope this to exactly the one account this preview role runs in.
    central_infra_account_id = get_aws_account_id()
    return iam.RolePolicyArgs(
        policy_name="AssumeCentralDnsDelegatePreviewRoles",
        policy_document=get_policy_document(
            statements=[
                GetPolicyDocumentStatementArgs(
                    sid="AssumeDnsDelegatePreviewRoles",
                    effect="Allow",
                    actions=["sts:AssumeRole"],
                    resources=[
                        f"arn:aws:iam::{central_infra_account_id}:role/{dns_delegate_preview_role_name(account_name)}"
                    ],
                )
            ]
        ).json,
    )


def infra_preview_role_name(repo_name: str, role_name_suffix: str | None = None) -> str:
    ending = repo_name if role_name_suffix is None else f"{repo_name}--{role_name_suffix}"
    return f"InfraPreview--{ending}"


def infra_deploy_role_name(repo_name: str, role_name_suffix: str | None = None) -> str:
    ending = repo_name if role_name_suffix is None else f"{repo_name}--{role_name_suffix}"
    return f"InfraDeploy--{ending}"


def create_oidc_for_standard_workload(
    *,
    workload_info: AwsLogicalWorkload,
    repo_org: str,
    repo_name: str,
    role_name_suffix: str | None = None,
) -> list[GithubOidcConfig]:
    """Permissions for the whole repo to deploy to any dev accounts and to run previews against staging.

    Permissions on main branch to deploy to staging and preview/deploy to prod.
    """
    kms_policy = create_kms_policy()
    configs: list[GithubOidcConfig] = []
    deploy_kwargs: CommonOidcConfigKwargs = {
        "role_name": infra_deploy_role_name(repo_name, role_name_suffix),
        "repo_org": repo_org,
        "repo_name": repo_name,
        "managed_policy_arns": ["arn:aws:iam::aws:policy/AdministratorAccess"],
        "role_policies": [kms_policy],
    }

    def preview_config(*, account_id: str, account_name: str) -> GithubOidcConfig:
        # role_policies are scoped per-account so each preview role can only assume its own account's dns-delegate-preview role
        return GithubOidcConfig(
            aws_account_id=account_id,
            role_name=infra_preview_role_name(repo_name, role_name_suffix),
            repo_org=repo_org,
            repo_name=repo_name,
            managed_policy_arns=["arn:aws:iam::aws:policy/ReadOnlyAccess"],
            role_policies=[
                kms_policy,
                create_assume_dns_delegate_preview_policy(account_name=account_name),
            ],
        )

    for dev_account in workload_info.dev_accounts:
        configs.append(
            GithubOidcConfig(
                aws_account_id=dev_account.id,
                **deploy_kwargs,
            )
        )
        configs.append(preview_config(account_id=dev_account.id, account_name=dev_account.name))
    for staging_account in workload_info.staging_accounts:
        configs.append(
            GithubOidcConfig(
                aws_account_id=staging_account.id,
                restrictions="ref:refs/heads/main",
                **deploy_kwargs,
            )
        )
        configs.append(preview_config(account_id=staging_account.id, account_name=staging_account.name))
    for prod_account in workload_info.prod_accounts:
        configs.append(
            GithubOidcConfig(
                aws_account_id=prod_account.id,
                restrictions="ref:refs/heads/main",
                **deploy_kwargs,
            )
        )
        configs.append(preview_config(account_id=prod_account.id, account_name=prod_account.name))
    return configs


def create_oidc_for_single_account_workload(
    *,
    aws_account_id: str,
    repo_org: str,
    repo_name: str,
    role_name_suffix: str
    | None = None,  # Used when there may be multiple separate stacks using different OIDC roles in the same repo.
) -> list[GithubOidcConfig]:
    kms_policy = create_kms_policy()
    return [
        GithubOidcConfig(
            aws_account_id=aws_account_id,
            role_name=infra_deploy_role_name(repo_name, role_name_suffix),
            repo_org=repo_org,
            repo_name=repo_name,
            restrictions="ref:refs/heads/main",
            managed_policy_arns=["arn:aws:iam::aws:policy/AdministratorAccess"],
            role_policies=[kms_policy],
        ),
        GithubOidcConfig(
            aws_account_id=aws_account_id,
            role_name=infra_preview_role_name(repo_name, role_name_suffix),
            repo_org=repo_org,
            repo_name=repo_name,
            managed_policy_arns=["arn:aws:iam::aws:policy/ReadOnlyAccess"],
            role_policies=[kms_policy],
        ),
    ]


def find_account_name_from_workload_info(*, workload_info: AwsLogicalWorkload, account_id: str) -> str:
    for account in workload_info.prod_accounts:
        if account.id == account_id:
            return account.name
    for account in workload_info.staging_accounts:
        if account.id == account_id:
            return account.name
    for account in workload_info.dev_accounts:
        if account.id == account_id:
            return account.name
    raise ValueError(f"Could not find account with id {account_id} in workload {workload_info.name}")  # noqa: TRY003 # not worth a custom exception for this


class WorkloadGithubOidc(ComponentResource):
    def __init__(
        self,
        workload_info: AwsLogicalWorkload,
        oidc_configs: list[GithubOidcConfig],
        providers: dict[AwsAccountId, Provider],
    ):
        super().__init__("labauto:AwsWorkloadGithubOidc", workload_info.name, None)
        central_infra_aws_account_id = get_aws_account_id()
        all_aws_accounts: list[
            str
        ] = []  # use a list instead of a set for deterministic ordering to avoid false positive pulumi diffs. # TODO: consider just creating a sorted list after using a set initially
        for oidc_config in oidc_configs:
            if oidc_config.aws_account_id not in all_aws_accounts:
                all_aws_accounts.append(oidc_config.aws_account_id)
        oidc_provider_arns: dict[AwsAccountId, Output[str]] = {}
        central_infra_oidc_provider_arn = Output.from_input(  # There can only be one GitHub OIDC provider per AWS account, and the aws-organization repo creates it in the central infra account. So need to dynamically get the ARN here.
            get_open_id_connect_provider(url=GITHUB_OIDC_URL).arn
        )
        oidc_provider_arns[central_infra_aws_account_id] = central_infra_oidc_provider_arn
        for aws_account_id in all_aws_accounts:
            account_name = find_account_name_from_workload_info(workload_info=workload_info, account_id=aws_account_id)
            pulumi_provider = None if aws_account_id == central_infra_aws_account_id else providers[aws_account_id]

            if aws_account_id != central_infra_aws_account_id:
                oidc_provider_arns[aws_account_id] = iam.OidcProvider(
                    f"github-oidc-provider-{account_name}",
                    url=GITHUB_OIDC_URL,
                    client_id_list=["sts.amazonaws.com"],
                    thumbprint_list=["6938fd4d98bab03faadb97b34396831e3780aea1"],  # GitHub's root CA thumbprint
                    tags=common_tags_native(),
                    opts=ResourceOptions(provider=pulumi_provider, parent=self),
                ).arn

        for oidc_config in oidc_configs:
            assume_role_policy_doc = Output.all(
                oidc_config=Output.from_input(oidc_config),
                oidc_provider_arn=oidc_provider_arns[oidc_config.aws_account_id],
            ).apply(
                lambda args: create_oidc_assume_role_policy(
                    oidc_config=args["oidc_config"],
                    provider_arn=args["oidc_provider_arn"],
                )
            )

            account_name = find_account_name_from_workload_info(
                workload_info=workload_info, account_id=oidc_config.aws_account_id
            )
            pulumi_provider = (
                None
                if oidc_config.aws_account_id == central_infra_aws_account_id
                else providers[oidc_config.aws_account_id]
            )
            _ = iam.Role(
                f"github-oidc--{account_name}--{oidc_config.role_name}",
                role_name=oidc_config.role_name,
                assume_role_policy_document=assume_role_policy_doc.json,
                managed_policy_arns=oidc_config.managed_policy_arns,
                policies=_none_if_empty(oidc_config.role_policies),
                tags=common_tags_native(),
                opts=ResourceOptions(provider=pulumi_provider, parent=self),
            )


def deploy_all_oidc(
    *,
    all_oidc: list[tuple[AwsLogicalWorkload, list[GithubOidcConfig]]],
    providers: dict[AwsAccountId, Provider],
) -> None:
    for workload_info, oidc_configs in all_oidc:
        _ = WorkloadGithubOidc(workload_info=workload_info, oidc_configs=oidc_configs, providers=providers)
