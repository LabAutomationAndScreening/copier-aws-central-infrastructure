import random
import string
from unittest.mock import ANY

from pulumi_aws.iam import get_policy_document
from pytest_mock import MockerFixture

import aws_central_infrastructure.iac_management.lib.github_oidc_lib as github_oidc_lib_module
from aws_central_infrastructure.iac_management.lib.constants import CENTRAL_INFRA_GITHUB_ORG_NAME
from aws_central_infrastructure.iac_management.lib.constants import GITHUB_ORG_IDS
from aws_central_infrastructure.iac_management.lib.github_oidc_lib import GithubOidcConfig
from aws_central_infrastructure.iac_management.lib.github_oidc_lib import create_oidc_assume_role_policy


def _random_account_id() -> str:
    return "".join(random.choices(string.digits, k=12))


def _random_name() -> str:
    return "".join(random.choices(string.ascii_lowercase + "-", k=8))


class TestCreateOidcAssumeRolePolicy:
    def test_Given_no_restrictions__When_policy_created__Then_sub_matches_legacy_and_immutable_subjects(
        self, mocker: MockerFixture
    ) -> None:
        repo_name = _random_name()
        oidc_config = GithubOidcConfig(
            aws_account_id=_random_account_id(),
            role_name=_random_name(),
            repo_org=CENTRAL_INFRA_GITHUB_ORG_NAME,
            repo_name=repo_name,
        )
        mock_get_policy_document = mocker.patch.object(github_oidc_lib_module, get_policy_document.__name__)

        _ = create_oidc_assume_role_policy(oidc_config=oidc_config, provider_arn=_random_name())

        (statement,) = mock_get_policy_document.call_args.kwargs["statements"]
        sub_conditions = [
            condition
            for condition in statement.conditions
            if condition.variable == "token.actions.githubusercontent.com:sub"
        ]

        mock_get_policy_document.assert_called_once_with(statements=[ANY])
        assert len(sub_conditions) == 1
        assert sub_conditions[0].test == "StringLike"
        assert sub_conditions[0].values == [
            f"repo:{CENTRAL_INFRA_GITHUB_ORG_NAME}/{repo_name}:*",
            f"repo:{CENTRAL_INFRA_GITHUB_ORG_NAME}@{GITHUB_ORG_IDS[CENTRAL_INFRA_GITHUB_ORG_NAME]}/{repo_name}@*:*",
        ]
