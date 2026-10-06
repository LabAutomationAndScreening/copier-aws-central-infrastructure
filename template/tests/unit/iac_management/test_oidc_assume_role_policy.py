import random
import re
import string
from unittest.mock import ANY
from unittest.mock import MagicMock

import pydantic
import pytest
from pulumi_aws.iam import GetPolicyDocumentStatementConditionArgs
from pulumi_aws.iam import get_policy_document
from pytest_mock import MockerFixture

import aws_central_infrastructure.iac_management.lib.github_oidc_lib as github_oidc_lib_module
from aws_central_infrastructure.iac_management.lib.constants import CENTRAL_INFRA_GITHUB_ORG_NAME
from aws_central_infrastructure.iac_management.lib.constants import GITHUB_ORG_IDS
from aws_central_infrastructure.iac_management.lib.github_oidc_lib import ANY_SUBJECT_CONTEXT
from aws_central_infrastructure.iac_management.lib.github_oidc_lib import GithubOidcConfig
from aws_central_infrastructure.iac_management.lib.github_oidc_lib import create_oidc_assume_role_policy

CENTRAL_ORG_IMMUTABLE_PREFIX = f"{CENTRAL_INFRA_GITHUB_ORG_NAME}@{GITHUB_ORG_IDS[CENTRAL_INFRA_GITHUB_ORG_NAME]}"


def _random_account_id() -> str:
    return "".join(random.choices(string.digits, k=12))


def _random_name() -> str:
    return "".join(random.choices(string.ascii_lowercase + "-", k=8))


def _sub_conditions_passed_to(mock_get_policy_document: MagicMock) -> list[GetPolicyDocumentStatementConditionArgs]:
    (statement,) = mock_get_policy_document.call_args.kwargs["statements"]
    return [
        condition
        for condition in statement.conditions
        if condition.variable == "token.actions.githubusercontent.com:sub"
    ]


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

        sub_conditions = _sub_conditions_passed_to(mock_get_policy_document)

        mock_get_policy_document.assert_called_once_with(statements=[ANY])
        assert len(sub_conditions) == 1
        assert sub_conditions[0].test == "StringLike"
        assert sub_conditions[0].values == [
            f"repo:{CENTRAL_INFRA_GITHUB_ORG_NAME}/{repo_name}:*",
            f"repo:{CENTRAL_ORG_IMMUTABLE_PREFIX}/{repo_name}@*:*",
        ]

    def test_Given_ref_restriction__When_policy_created__Then_sub_matches_both_subjects_scoped_to_that_ref(
        self, mocker: MockerFixture
    ) -> None:
        repo_name = _random_name()
        restriction = f"ref:refs/heads/{_random_name()}"
        oidc_config = GithubOidcConfig(
            aws_account_id=_random_account_id(),
            role_name=_random_name(),
            repo_org=CENTRAL_INFRA_GITHUB_ORG_NAME,
            repo_name=repo_name,
            restrictions=restriction,
        )
        mock_get_policy_document = mocker.patch.object(github_oidc_lib_module, get_policy_document.__name__)

        _ = create_oidc_assume_role_policy(oidc_config=oidc_config, provider_arn=_random_name())

        sub_conditions = _sub_conditions_passed_to(mock_get_policy_document)

        mock_get_policy_document.assert_called_once_with(statements=[ANY])
        assert len(sub_conditions) == 1
        assert sub_conditions[0].test == "StringLike"
        assert sub_conditions[0].values == [
            f"repo:{CENTRAL_INFRA_GITHUB_ORG_NAME}/{repo_name}:{restriction}",
            f"repo:{CENTRAL_ORG_IMMUTABLE_PREFIX}/{repo_name}@*:{restriction}",
        ]


class TestWhenGithubOidcConfigCreated:
    @pytest.mark.parametrize("wildcard_char", ["*", "?"])
    def test_Given_restriction_containing_wildcard__Then_validation_error_names_restriction(
        self, wildcard_char: str
    ) -> None:
        restriction = f"ref:refs/heads/{_random_name()}{wildcard_char}"

        with pytest.raises(pydantic.ValidationError, match=re.escape(restriction)):
            _ = GithubOidcConfig(
                aws_account_id=_random_account_id(),
                role_name=_random_name(),
                repo_org=CENTRAL_INFRA_GITHUB_ORG_NAME,
                repo_name=_random_name(),
                restrictions=restriction,
            )

    def test_Given_bare_wildcard_restriction__Then_config_keeps_it(self) -> None:
        oidc_config = GithubOidcConfig(
            aws_account_id=_random_account_id(),
            role_name=_random_name(),
            repo_org=CENTRAL_INFRA_GITHUB_ORG_NAME,
            repo_name=_random_name(),
            restrictions=ANY_SUBJECT_CONTEXT,
        )

        assert oidc_config.restrictions == ANY_SUBJECT_CONTEXT

    def test_Given_restrictions_explicitly_none__Then_config_has_no_restrictions(self) -> None:
        oidc_config = GithubOidcConfig(
            aws_account_id=_random_account_id(),
            role_name=_random_name(),
            repo_org=CENTRAL_INFRA_GITHUB_ORG_NAME,
            repo_name=_random_name(),
            restrictions=None,
        )

        assert oidc_config.restrictions is None

    @pytest.mark.parametrize("wildcard_char", ["*", "?"])
    def test_Given_wildcard_repo_name_with_ref_restriction__Then_validation_error_names_repo_and_restriction(
        self, wildcard_char: str
    ) -> None:
        repo_name = f"{_random_name()}{wildcard_char}"
        restriction = f"ref:refs/heads/{_random_name()}"

        with pytest.raises(pydantic.ValidationError, match=f"{re.escape(repo_name)}.*{re.escape(restriction)}"):
            _ = GithubOidcConfig(
                aws_account_id=_random_account_id(),
                role_name=_random_name(),
                repo_org=CENTRAL_INFRA_GITHUB_ORG_NAME,
                repo_name=repo_name,
                restrictions=restriction,
            )

    def test_Given_wildcard_repo_name_without_restriction__Then_config_keeps_it(self) -> None:
        oidc_config = GithubOidcConfig(
            aws_account_id=_random_account_id(),
            role_name=_random_name(),
            repo_org=CENTRAL_INFRA_GITHUB_ORG_NAME,
            repo_name="*",
        )

        assert oidc_config.repo_name == "*"

    def test_Given_wildcard_repo_name_with_bare_wildcard_restriction__Then_config_keeps_it(self) -> None:
        oidc_config = GithubOidcConfig(
            aws_account_id=_random_account_id(),
            role_name=_random_name(),
            repo_org=CENTRAL_INFRA_GITHUB_ORG_NAME,
            repo_name="*",
            restrictions=ANY_SUBJECT_CONTEXT,
        )

        assert oidc_config.repo_name == "*"

    def test_Given_repo_org_without_known_org_id__Then_validation_error_names_org(self) -> None:
        unknown_org_name = _random_name()

        with pytest.raises(pydantic.ValidationError, match=re.escape(unknown_org_name)):
            _ = GithubOidcConfig(
                aws_account_id=_random_account_id(),
                role_name=_random_name(),
                repo_org=unknown_org_name,
                repo_name=_random_name(),
            )
