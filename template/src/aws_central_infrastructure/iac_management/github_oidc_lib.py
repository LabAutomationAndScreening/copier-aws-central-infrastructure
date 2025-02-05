from ephemeral_pulumi_deploy.utils import common_tags_native
from pulumi import ComponentResource
from pulumi import Output
from pulumi import ResourceOptions
from pulumi_aws.iam import GetPolicyDocumentStatementArgs
from pulumi_aws.iam import GetPolicyDocumentStatementConditionArgs
from pulumi_aws.iam import GetPolicyDocumentStatementPrincipalArgs
from pulumi_aws.iam import get_policy_document
from pulumi_aws_native import Provider
from pulumi_aws_native import iam
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from .shared_lib import AwsLogicalWorkload

type WorkloadName = str
type AwsAccountId = str


class GithubOidcConfig(BaseModel):
    aws_account_id: str
    role_name: str
    repo_org: str
    repo_name: str
    managed_policy_arns: list[str] = Field(default_factory=list)
    restrictions: str | None = None
    role_policy: iam.RolePolicyArgs | None = None

    model_config = ConfigDict(arbitrary_types_allowed=True)


def create_oidc_for_single_account_workload(
    *,
    aws_account_id: str,
    repo_org: str,
    repo_name: str,
    kms_key_arn: str,
    role_name_suffix: str
    | None = None,  # Used when there may be multiple separate stacks using different OIDC roles in the same repo.
) -> list[GithubOidcConfig]:
    role_name_ending = repo_name
    if role_name_suffix is not None:
        role_name_ending += f"--{role_name_suffix}"
    kms_policy = iam.RolePolicyArgs(
        policy_name="InfraKmsDecrypt",
        policy_document=get_policy_document(
            statements=[
                GetPolicyDocumentStatementArgs(
                    effect="Allow",
                    actions=[
                        "kms:Decrypt",
                        "kms:Encrypt",  # unclear why Encrypt is required to run a Preview...but Pulumi gives an error if it's not included
                    ],
                    resources=[kms_key_arn],
                )
            ]
        ).json,
    )
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
        all_aws_accounts: list[
            str
        ] = []  # use a list instead of a set for deterministic ordering to avoid false positive pulumi diffs. # TODO: consider just creating a sorted list after using a set initially
        for oidc_config in oidc_configs:
            if oidc_config.aws_account_id not in all_aws_accounts:
                all_aws_accounts.append(oidc_config.aws_account_id)
        oidc_providers: dict[AwsAccountId, iam.OidcProvider] = {}
        for aws_account_id in all_aws_accounts:
            account_name = find_account_name_from_workload_info(workload_info=workload_info, account_id=aws_account_id)
            oidc_providers[aws_account_id] = iam.OidcProvider(
                f"github-oidc-provider-{account_name}",
                url="https://token.actions.githubusercontent.com",
                client_id_list=["sts.amazonaws.com"],
                thumbprint_list=["6938fd4d98bab03faadb97b34396831e3780aea1"],  # GitHub's root CA thumbprint
                tags=common_tags_native(),
                opts=ResourceOptions(provider=providers[aws_account_id], parent=self),
            )
        for oidc_config in oidc_configs:
            assume_role_policy_doc = Output.all(
                oidc_config=Output.from_input(oidc_config),
                oidc_provider_arn=oidc_providers[oidc_config.aws_account_id].arn,
            ).apply(
                lambda args: get_policy_document(
                    statements=[
                        GetPolicyDocumentStatementArgs(
                            effect="Allow",
                            principals=[
                                GetPolicyDocumentStatementPrincipalArgs(
                                    type="Federated", identifiers=[args["oidc_provider_arn"]]
                                )
                            ],
                            actions=["sts:AssumeRoleWithWebIdentity"],
                            conditions=[
                                GetPolicyDocumentStatementConditionArgs(
                                    test="StringLike" if args["oidc_config"].restrictions is None else "StringEquals",
                                    variable="token.actions.githubusercontent.com:sub",
                                    values=[
                                        f"repo:{args['oidc_config'].repo_org}/{args['oidc_config'].repo_name}:{'*' if args['oidc_config'].restrictions is None else args['oidc_config'].restrictions}"
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
            )
            account_name = find_account_name_from_workload_info(
                workload_info=workload_info, account_id=oidc_config.aws_account_id
            )
            _ = iam.Role(
                f"github-oidc--{account_name}--{oidc_config.role_name}",
                role_name=oidc_config.role_name,
                assume_role_policy_document=assume_role_policy_doc.json,
                managed_policy_arns=oidc_config.managed_policy_arns,
                policies=None if oidc_config.role_policy is None else [oidc_config.role_policy],
                tags=common_tags_native(),
                opts=ResourceOptions(provider=providers[oidc_config.aws_account_id], parent=self),
            )


def deploy_all_oidc(
    *,
    all_oidc: list[tuple[AwsLogicalWorkload, list[GithubOidcConfig]]],
    providers: dict[AwsAccountId, Provider],
) -> None:
    for workload_info, oidc_configs in all_oidc:
        _ = WorkloadGithubOidc(workload_info=workload_info, oidc_configs=oidc_configs, providers=providers)
