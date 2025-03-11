import json
import logging

from ephemeral_pulumi_deploy import append_resource_suffix
from ephemeral_pulumi_deploy import common_tags_native
from pulumi import ComponentResource
from pulumi import ResourceOptions
from pulumi_aws.iam import GetPolicyDocumentStatementArgs
from pulumi_aws.iam import GetPolicyDocumentStatementConditionArgs
from pulumi_aws.iam import GetPolicyDocumentStatementPrincipalArgs
from pulumi_aws.iam import get_policy_document
from pulumi_aws.organizations import get_organization
from pulumi_aws_native import codeartifact

from aws_central_infrastructure.iac_management.lib.constants import CENTRAL_INFRA_GITHUB_ORG_NAME

logger = logging.getLogger(__name__)

CODE_ARTIFACT_DOMAIN_NAME = CENTRAL_INFRA_GITHUB_ORG_NAME
PRIMARY_REPO_NAME = f"{CENTRAL_INFRA_GITHUB_ORG_NAME}-primary"
STAGING_REPO_NAME = f"{CENTRAL_INFRA_GITHUB_ORG_NAME}-staging"


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
        _ = codeartifact.Repository(
            append_resource_suffix("primary"),
            domain_name=domain.domain_name,
            repository_name=PRIMARY_REPO_NAME,
            upstreams=[upstream_repo.repository_name for upstream_repo in upstream_repos],
            permissions_policy_document=org_read_access_policy,
            opts=ResourceOptions(parent=self),
            tags=common_tags_native(),
        )
        _ = codeartifact.Repository(
            append_resource_suffix("staging"),
            domain_name=domain.domain_name,
            repository_name=STAGING_REPO_NAME,
            upstreams=[upstream_repo.repository_name for upstream_repo in upstream_repos],
            permissions_policy_document=org_read_access_policy,
            opts=ResourceOptions(parent=self),
            tags=common_tags_native(),
        )
