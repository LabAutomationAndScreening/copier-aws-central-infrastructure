from ephemeral_pulumi_deploy import get_config_str
from pulumi_aws.iam import GetPolicyDocumentStatementArgs
from pulumi_aws.iam import GetPolicyDocumentStatementConditionArgs
from pulumi_aws.iam import get_policy_document


def create_inline_view_only_policy() -> str:
    state_bucket_name = get_config_str("proj:backend_bucket_name")
    return get_policy_document(
        statements=[
            GetPolicyDocumentStatementArgs(
                effect="Allow",
                actions=["eks:DescribeCluster", "eks:ListClusters"],
                resources=["*"],
            ),
            GetPolicyDocumentStatementArgs(
                effect="Allow",
                actions=["s3:GetObject", "s3:GetObjectVersion"],
                resources=[f"arn:aws:s3:::{state_bucket_name}/${{aws:PrincipalAccount}}/*"],
            ),
            GetPolicyDocumentStatementArgs(
                effect="Allow",
                actions=["s3:ListBucket"],
                resources=[f"arn:aws:s3:::{state_bucket_name}"],
                conditions=[
                    GetPolicyDocumentStatementConditionArgs(
                        test="StringLike", variable="s3:prefix", values=["${aws:PrincipalAccount}/*"]
                    ),
                ],
            ),
        ]
    ).json
