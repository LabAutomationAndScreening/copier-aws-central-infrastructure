import json
import logging
from typing import Literal

import pulumi_aws
from ephemeral_pulumi_deploy import append_resource_suffix
from ephemeral_pulumi_deploy import common_tags_native
from ephemeral_pulumi_deploy import get_aws_account_id
from pulumi import ComponentResource
from pulumi import Output
from pulumi import ResourceOptions
from pulumi_aws.iam import GetPolicyDocumentResult
from pulumi_aws.iam import GetPolicyDocumentStatementArgs
from pulumi_aws.iam import GetPolicyDocumentStatementConditionArgs
from pulumi_aws.iam import GetPolicyDocumentStatementPrincipalArgs
from pulumi_aws.iam import get_open_id_connect_provider
from pulumi_aws.iam import get_policy_document
from pulumi_aws.organizations import get_organization
from pulumi_aws_native import codeartifact
from pulumi_aws_native import iam
from pydantic import BaseModel
from pydantic import Field

from aws_central_infrastructure.iac_management.lib import CENTRAL_INFRA_GITHUB_ORG_NAME
from aws_central_infrastructure.iac_management.lib import CODE_ARTIFACT_SERVICE_BEARER_STATEMENT
from aws_central_infrastructure.iac_management.lib import GITHUB_OIDC_URL
from aws_central_infrastructure.iac_management.lib import GithubOidcConfig
from aws_central_infrastructure.iac_management.lib import create_oidc_assume_role_policy

logger = logging.getLogger(__name__)

CODE_ARTIFACT_DOMAIN_NAME = CENTRAL_INFRA_GITHUB_ORG_NAME
PRIMARY_REPO_NAME = f"{CENTRAL_INFRA_GITHUB_ORG_NAME}-primary"
STAGING_REPO_NAME = f"{CENTRAL_INFRA_GITHUB_ORG_NAME}-staging"


class RepoPackageClaims(BaseModel):
    repo_name: str
    repo_org: str = CENTRAL_INFRA_GITHUB_ORG_NAME
    pypi_package_names: set[str] = Field(default_factory=set)
    npm_package_names: set[str] = Field(default_factory=set)
    nuget_package_names: set[str] = Field(default_factory=set)


class CentralCodeArtifact(ComponentResource):
    def __init__(
        self,
    ):
        super().__init__("labauto:CentralCodeArtifact", append_resource_suffix(), None)
        org_id = get_organization().id
        org_read_access_policy = json.loads(
            get_policy_document(
                statements=[
                    GetPolicyDocumentStatementArgs(
                        effect="Allow",
                        sid="OrgReadAccess",
                        actions=[
                            "codeartifact:DescribePackage",
                            "codeartifact:DescribePackageVersion",
                            "codeartifact:DescribeRepository",
                            "codeartifact:GetPackageVersionReadme",
                            "codeartifact:GetRepositoryEndpoint",
                            "codeartifact:GetRepositoryPermissionsPolicy",
                            "codeartifact:ListPackageVersionAssets",
                            "codeartifact:ListPackageVersionDependencies",
                            "codeartifact:ListPackageVersions",
                            "codeartifact:ListPackages",
                            "codeartifact:ListTagsForResource",
                            "codeartifact:ReadFromRepository",
                        ],
                        principals=[
                            GetPolicyDocumentStatementPrincipalArgs(
                                type="*",
                                identifiers=["*"],
                            )
                        ],
                        resources=["*"],
                        conditions=[
                            GetPolicyDocumentStatementConditionArgs(
                                values=[org_id],
                                variable="aws:PrincipalOrgID",
                                test="StringEquals",
                            ),
                        ],
                    ),
                ]
            ).json
        )
        domain = codeartifact.Domain(
            append_resource_suffix(),
            domain_name=CODE_ARTIFACT_DOMAIN_NAME,
            permissions_policy_document=json.loads(
                get_policy_document(
                    statements=[
                        GetPolicyDocumentStatementArgs(
                            effect="Allow",
                            sid="OrgReadAccess",
                            actions=[
                                "codeartifact:DescribeDomain",
                                "codeartifact:GetAuthorizationToken",
                                "codeartifact:GetDomainPermissionsPolicy",
                                "codeartifact:ListRepositoriesInDomain",
                                "sts:GetServiceBearerToken",
                            ],
                            principals=[
                                GetPolicyDocumentStatementPrincipalArgs(
                                    type="*",
                                    identifiers=["*"],
                                )
                            ],
                            resources=["*"],
                            conditions=[
                                GetPolicyDocumentStatementConditionArgs(
                                    test="StringEquals",
                                    values=[org_id],
                                    variable="aws:PrincipalOrgID",
                                ),
                            ],
                        ),
                    ]
                ).json
            ),
            opts=ResourceOptions(parent=self),
            tags=common_tags_native(),
        )
        self.domain = domain
        upstream_repos = [
            codeartifact.Repository(
                append_resource_suffix(f"{upstream_type}-store"),
                domain_name=domain.domain_name,
                repository_name=f"{upstream_type}-store",
                external_connections=[f"public:{connection_name}"],
                description=f"Provide artifacts from the public {upstream_type} registry",
                permissions_policy_document=org_read_access_policy,
                opts=ResourceOptions(parent=self),
                tags=common_tags_native(),
            )
            for upstream_type, connection_name in (("pypi", "pypi"), ("npm", "npmjs"), ("nuget", "nuget-org"))
        ]
        self.primary_repo = codeartifact.Repository(
            append_resource_suffix("primary"),
            domain_name=domain.domain_name,
            description="The normal place to install from. This is where production-ready packages are published to.",
            repository_name=PRIMARY_REPO_NAME,
            upstreams=[upstream_repo.repository_name for upstream_repo in upstream_repos],
            permissions_policy_document=org_read_access_policy,
            opts=ResourceOptions(parent=self),
            tags=common_tags_native(),
        )
        self.staging_repo = codeartifact.Repository(
            append_resource_suffix("staging"),
            domain_name=domain.domain_name,
            repository_name=STAGING_REPO_NAME,
            description="A staging repository for testing packages before promoting to production.",
            upstreams=[upstream_repo.repository_name for upstream_repo in upstream_repos],
            permissions_policy_document=org_read_access_policy,
            opts=ResourceOptions(parent=self),
            tags=common_tags_native(),
        )

    def register_package_claims(self, package_claims: list[RepoPackageClaims]) -> None:
        central_infra_oidc_provider_arn = get_open_id_connect_provider(url=GITHUB_OIDC_URL).arn

        for claims in package_claims:
            _ = RepoPublishingRoles(
                code_artifact=self,
                package_claims=claims,
                central_infra_oidc_provider_arn=central_infra_oidc_provider_arn,
            )


def create_code_artifact_package_arn(
    *,
    ca_repo_name: str,
    ca_domain_name: str,
    package_type: Literal["pypi", "npm", "nuget"],
    package_namespace: str = "",
    package_name: str,
) -> str:
    return f"arn:aws:codeartifact:{pulumi_aws.config.region}:{get_aws_account_id()}:package/{ca_domain_name}/{ca_repo_name}/{package_type}/{package_namespace}/{package_name}"


class RepoPublishingRoles(ComponentResource):
    def __init__(
        self,
        *,
        code_artifact: CentralCodeArtifact,
        package_claims: RepoPackageClaims,
        central_infra_oidc_provider_arn: str,
    ):
        super().__init__(
            "labauto:CentralCodeArtifactRepoPublishingRoles",
            append_resource_suffix(f"{package_claims.repo_org}--{package_claims.repo_name}", max_length=150),
            None,
            opts=ResourceOptions(parent=code_artifact),
        )
        self._central_infra_oidc_provider_arn = central_infra_oidc_provider_arn
        self._package_claims = package_claims
        self._code_artifact = code_artifact

        self._create_role(
            oidc_config=GithubOidcConfig(
                aws_account_id=get_aws_account_id(),
                repo_org=package_claims.repo_org,
                repo_name=package_claims.repo_name,
                role_name=f"GHA-CA-Staging-{package_claims.repo_name}",
                role_policy=iam.RolePolicyArgs(
                    policy_name="PublishPackagesToCodeArtifact",
                    policy_document=self._create_role_policy_document().json,
                ),
            )
        )

        self._create_role(
            oidc_config=GithubOidcConfig(
                aws_account_id=get_aws_account_id(),
                repo_org=package_claims.repo_org,
                repo_name=package_claims.repo_name,
                restrictions="refs/heads/main",  # TODO: consider creating a publishing environment within GitHub and using that
                role_name=f"GHA-CA-Primary-{package_claims.repo_name}",
                role_policy=iam.RolePolicyArgs(
                    policy_name="PublishPackagesToCodeArtifact",
                    policy_document=self._create_role_policy_document(for_primary=True).json,
                ),
            )
        )

    def _create_role(
        self,
        oidc_config: GithubOidcConfig,
    ):
        assert oidc_config.role_policy is not None
        _ = iam.Role(
            f"github-oidc--{oidc_config.role_name}",
            role_name=oidc_config.role_name,
            assume_role_policy_document=create_oidc_assume_role_policy(
                oidc_config=oidc_config, provider_arn=self._central_infra_oidc_provider_arn
            ).json,
            policies=[oidc_config.role_policy],
            tags=common_tags_native(),
            opts=ResourceOptions(parent=self),
        )

    def _create_role_policy_document(self, *, for_primary: bool = False) -> Output[GetPolicyDocumentResult]:
        ca_repo = self._code_artifact.primary_repo if for_primary else self._code_artifact.staging_repo
        return Output.all(self._code_artifact.domain.name, ca_repo.name).apply(
            lambda args: get_policy_document(
                statements=[
                    CODE_ARTIFACT_SERVICE_BEARER_STATEMENT,
                    GetPolicyDocumentStatementArgs(
                        sid="PublishToCodeArtifact",
                        effect="Allow",
                        actions=[
                            "codeartifact:PublishPackageVersion",
                            "codeartifact:PutPackageMetadata",
                        ],
                        resources=[
                            create_code_artifact_package_arn(
                                ca_repo_name=args[1],
                                ca_domain_name=args[0],
                                package_type="pypi",
                                # pypi does not use namespaces
                                package_name=package_name,
                            )
                            for package_name in self._package_claims.pypi_package_names
                        ]
                        + [
                            create_code_artifact_package_arn(
                                ca_repo_name=args[1],
                                ca_domain_name=args[0],
                                package_type="npm",
                                # npm does use namespaces...but ignoring for now
                                package_name=package_name,
                            )
                            for package_name in self._package_claims.npm_package_names
                        ]
                        + [
                            create_code_artifact_package_arn(
                                ca_repo_name=args[1],
                                ca_domain_name=args[0],
                                package_type="nuget",
                                # nuget does not use namespaces
                                package_name=package_name,
                            )
                            for package_name in self._package_claims.nuget_package_names
                        ],
                    ),
                ]
            )
        )
