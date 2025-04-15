from typing import TypedDict

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

GITHUB_OIDC_URL = "https://token.actions.githubusercontent.com"
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
    role_policy: iam.RolePolicyArgs


class GithubOidcConfig(BaseModel):
    aws_account_id: str
    role_name: str
    repo_org: str
    repo_name: str
    managed_policy_arns: list[str] = Field(default_factory=list)
    restrictions: str | None = None
    role_policy: iam.RolePolicyArgs | None = None
    role_resource_name_prefix: str = "github-oidc--"

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def create_role(self, *, provider_arn: str, parent: Resource | None = None) -> iam.Role:
        role_policies: list[iam.RolePolicyArgs] = []
        if self.role_policy is not None:
            role_policies.append(self.role_policy)
        return iam.Role(
            f"{self.role_resource_name_prefix}{self.role_name}",
            role_name=self.role_name,
            assume_role_policy_document=create_oidc_assume_role_policy(
                oidc_config=self, provider_arn=provider_arn
            ).json,
            policies=role_policies,
            tags=common_tags_native(),
            opts=ResourceOptions(parent=parent),
        )


def create_oidc_assume_role_policy(
    *, oidc_config: GithubOidcConfig, provider_arn: str
) -> AwaitableGetPolicyDocumentResult:
    return get_policy_document(
        statements=[
            GetPolicyDocumentStatementArgs(
                effect="Allow",
                principals=[GetPolicyDocumentStatementPrincipalArgs(type="Federated", identifiers=[provider_arn])],
                actions=["sts:AssumeRoleWithWebIdentity"],
                conditions=[
                    GetPolicyDocumentStatementConditionArgs(
                        test="StringLike"
                        if oidc_config.restrictions is None or oidc_config.restrictions == "*"
                        else "StringEquals",
                        variable="token.actions.githubusercontent.com:sub",
                        values=[
                            f"repo:{oidc_config.repo_org}/{oidc_config.repo_name}:{'*' if oidc_config.restrictions is None else oidc_config.restrictions}"
                        ],
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


def create_oidc_for_standard_workload(
    *, workload_info: AwsLogicalWorkload, repo_org: str, repo_name: str, role_name_suffix: str | None = None
) -> list[GithubOidcConfig]:
    """Permissions for the whole repo to deploy to any dev accounts and to run previews against staging.

    Permissions on main branch to deploy to staging and preview/deploy to prod.
    """
    role_name_ending = repo_name
    if role_name_suffix is not None:
        role_name_ending += f"--{role_name_suffix}"
    kms_policy = create_kms_policy()
    configs: list[GithubOidcConfig] = []
    preview_kwargs: CommonOidcConfigKwargs = {
        "role_name": f"InfraPreview--{role_name_ending}",
        "repo_org": repo_org,
        "repo_name": repo_name,
        "managed_policy_arns": ["arn:aws:iam::aws:policy/ReadOnlyAccess"],
        "role_policy": kms_policy,
    }
    deploy_kwargs: CommonOidcConfigKwargs = {
        "role_name": f"InfraDeploy--{role_name_ending}",
        "repo_org": repo_org,
        "repo_name": repo_name,
        "managed_policy_arns": ["arn:aws:iam::aws:policy/AdministratorAccess"],
        "role_policy": kms_policy,
    }
    for dev_account in workload_info.dev_accounts:
        configs.append(
            GithubOidcConfig(
                aws_account_id=dev_account.id,
                **deploy_kwargs,
            )
        )
        configs.append(
            GithubOidcConfig(
                aws_account_id=dev_account.id,
                **preview_kwargs,
            )
        )
    for staging_account in workload_info.staging_accounts:
        configs.append(
            GithubOidcConfig(
                aws_account_id=staging_account.id,
                restrictions="ref:refs/heads/main",
                **deploy_kwargs,
            )
        )
        configs.append(
            GithubOidcConfig(
                aws_account_id=staging_account.id,
                **preview_kwargs,
            )
        )
    for prod_account in workload_info.prod_accounts:
        configs.append(
            GithubOidcConfig(
                aws_account_id=prod_account.id,
                restrictions="ref:refs/heads/main",
                **deploy_kwargs,
            )
        )
        configs.append(
            GithubOidcConfig(
                aws_account_id=prod_account.id,
                **preview_kwargs,
            )
        )
    return configs


def create_oidc_for_single_account_workload(
    *,
    aws_account_id: str,
    repo_org: str,
    repo_name: str,
    role_name_suffix: str
    | None = None,  # Used when there may be multiple separate stacks using different OIDC roles in the same repo.
) -> list[GithubOidcConfig]:
    role_name_ending = repo_name
    if role_name_suffix is not None:
        role_name_ending += f"--{role_name_suffix}"
    kms_policy = create_kms_policy()
    return [
        GithubOidcConfig(
            aws_account_id=aws_account_id,
            role_name=f"InfraDeploy--{role_name_ending}",
            repo_org=repo_org,
            repo_name=repo_name,
            restrictions="ref:refs/heads/main",
            managed_policy_arns=["arn:aws:iam::aws:policy/AdministratorAccess"],
            role_policy=kms_policy,
        ),
        GithubOidcConfig(
            aws_account_id=aws_account_id,
            role_name=f"InfraPreview--{role_name_ending}",
            repo_org=repo_org,
            repo_name=repo_name,
            managed_policy_arns=["arn:aws:iam::aws:policy/ReadOnlyAccess"],
            role_policy=kms_policy,
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
                    oidc_config=args["oidc_config"], provider_arn=args["oidc_provider_arn"]
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
                policies=None if oidc_config.role_policy is None else [oidc_config.role_policy],
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
