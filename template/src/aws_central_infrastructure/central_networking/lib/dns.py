import json
import re

import pulumi_aws
from ephemeral_pulumi_deploy import append_resource_suffix
from ephemeral_pulumi_deploy import common_tags
from lab_auto_pulumi import CENTRAL_NETWORKING_SSM_PREFIX
from lab_auto_pulumi import AwsAccountInfo
from lab_auto_pulumi import AwsLogicalWorkload
from lab_auto_pulumi import WorkloadName
from pulumi import ComponentResource
from pulumi import Output
from pulumi import ResourceOptions
from pydantic import BaseModel

from aws_central_infrastructure.iac_management.lib import infra_deploy_role_name
from aws_central_infrastructure.iac_management.lib import infra_preview_role_name
from aws_central_infrastructure.identity_center.lib.constants import LOW_RISK_ACCOUNT_ADMIN_ACCESS_PERMISSION_SET_NAME

from .network import AllAccountProviders
from .network import CentralNetworkingHostedZone
from .network import create_ssm_param_in_all_accounts
from .role_names import dns_delegate_preview_role_name


def normalize_record_name_pattern(pattern: str) -> str:
    return pattern.lower().rstrip(".")


class CentralNetworkingDnsDelegate(ComponentResource):
    def __init__(
        self,
        *,
        account: AwsAccountInfo,
        zone: CentralNetworkingHostedZone,
        all_providers: AllAccountProviders,
        record_name_patterns: list[str],
        github_repo_name: str,
    ):
        super().__init__(
            "labauto:CentralNetworkingDnsDelegate",
            append_resource_suffix(f"dns-delegate-{account.name}", max_length=150),
            None,
        )
        preview_principal_arns = [
            f"arn:aws:iam::{account.id}:role/{infra_preview_role_name(github_repo_name)}",
            f"arn:aws:iam::{account.id}:role/aws-reserved/sso.amazonaws.com/AWSReservedSSO_{LOW_RISK_ACCOUNT_ADMIN_ACCESS_PERMISSION_SET_NAME}_*",
        ]
        deploy_principal_arns = [
            f"arn:aws:iam::{account.id}:role/{infra_deploy_role_name(github_repo_name)}",
            f"arn:aws:iam::{account.id}:role/aws-reserved/sso.amazonaws.com/AWSReservedSSO_{LOW_RISK_ACCOUNT_ADMIN_ACCESS_PERMISSION_SET_NAME}_*",
        ]

        preview_assume_role_policy = json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"AWS": f"arn:aws:iam::{account.id}:root"},
                        "Action": "sts:AssumeRole",
                        "Condition": {
                            "StringLike": {
                                "aws:PrincipalArn": preview_principal_arns,
                            }
                        },
                    }
                ],
            }
        )

        deploy_assume_role_policy = json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"AWS": f"arn:aws:iam::{account.id}:root"},
                        "Action": "sts:AssumeRole",
                        "Condition": {
                            "StringLike": {
                                "aws:PrincipalArn": deploy_principal_arns,
                            }
                        },
                    }
                ],
            }
        )

        preview_role = pulumi_aws.iam.Role(
            append_resource_suffix(dns_delegate_preview_role_name(account.name), max_length=150),
            name=dns_delegate_preview_role_name(account.name),
            assume_role_policy=preview_assume_role_policy,
            tags=common_tags(),
            opts=ResourceOptions(parent=self),
        )

        deploy_role = pulumi_aws.iam.Role(
            append_resource_suffix(f"dns-delegate-deploy-{account.name}", max_length=150),
            name=f"dns-delegate-deploy-{account.name}",
            assume_role_policy=deploy_assume_role_policy,
            tags=common_tags(),
            opts=ResourceOptions(parent=self),
        )

        list_records_policy: Output[str] = zone.zone.id.apply(
            lambda zone_id: json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Action": ["route53:ListResourceRecordSets"],
                            "Resource": f"arn:aws:route53:::hostedzone/{zone_id}",
                        }
                    ],
                }
            )
        )

        normalized_patterns = list(dict.fromkeys(normalize_record_name_pattern(p) for p in record_name_patterns))
        change_records_policy: Output[str] = zone.zone.id.apply(
            lambda zone_id: json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Action": [
                                "route53:GetHostedZone",
                                "route53:ListResourceRecordSets",
                            ],
                            "Resource": f"arn:aws:route53:::hostedzone/{zone_id}",
                        },
                        {
                            "Effect": "Allow",
                            "Action": ["route53:ChangeResourceRecordSets"],
                            "Resource": f"arn:aws:route53:::hostedzone/{zone_id}",
                            "Condition": {
                                "ForAllValues:StringLike": {
                                    "route53:ChangeResourceRecordSetsNormalizedRecordNames": normalized_patterns,
                                }
                            },
                        },
                        {
                            "Effect": "Allow",
                            "Action": ["route53:GetChange"],
                            "Resource": "*",
                        },
                    ],
                }
            )
        )

        _ = pulumi_aws.iam.RolePolicy(
            append_resource_suffix(f"dns-delegate-preview-policy-{account.name}", max_length=150),
            role=preview_role.name,
            policy=list_records_policy,
            opts=ResourceOptions(parent=preview_role),
        )

        _ = pulumi_aws.iam.RolePolicy(
            append_resource_suffix(f"dns-delegate-deploy-policy-{account.name}", max_length=150),
            role=deploy_role.name,
            policy=change_records_policy,
            opts=ResourceOptions(parent=deploy_role),
        )

        account_native_provider = all_providers.all_native_providers[account.id]
        create_ssm_param_in_all_accounts(
            providers={account.id: account_native_provider},
            parent=self,
            resource_name_prefix=f"dns-delegate-preview-role-arn-{account.name}",
            param_name=f"{CENTRAL_NETWORKING_SSM_PREFIX}/dns-delegate-preview-role-arn",
            param_value=preview_role.arn,
        )
        create_ssm_param_in_all_accounts(
            providers={account.id: account_native_provider},
            parent=self,
            resource_name_prefix=f"dns-delegate-deploy-role-arn-{account.name}",
            param_name=f"{CENTRAL_NETWORKING_SSM_PREFIX}/dns-delegate-deploy-role-arn",
            param_value=deploy_role.arn,
        )


class WorkloadDnsDelegateConfig(BaseModel):
    workload_name: WorkloadName
    github_repo_name: str
    prod_record_patterns: list[str]
    staging_record_patterns: list[str]
    dev_record_patterns: list[str]


def _patterns_overlap(a: str, b: str) -> bool:
    def to_regex(p: str) -> re.Pattern[str]:
        return re.compile(re.escape(p).replace(r"\*", ".*"), re.IGNORECASE)

    return bool(to_regex(a).fullmatch(b) or to_regex(b).fullmatch(a))


def validate_no_cross_workload_pattern_overlap(
    configs: list[WorkloadDnsDelegateConfig],
) -> None:
    seen: dict[str, WorkloadName] = {}
    for cfg in configs:
        all_patterns = [
            *cfg.prod_record_patterns,
            *cfg.staging_record_patterns,
            *cfg.dev_record_patterns,
        ]
        for pattern in all_patterns:
            for seen_pattern, seen_workload in seen.items():
                if _patterns_overlap(pattern, seen_pattern):
                    raise ValueError(  # noqa: TRY003 # simple validation, no custom exception needed
                        f"Record pattern '{pattern}' claimed by both '{seen_workload}' and '{cfg.workload_name}'"
                    )
            seen[pattern] = cfg.workload_name


def create_dns_delegates(
    *,
    delegate_configs: list[WorkloadDnsDelegateConfig],
    workloads_info: dict[WorkloadName, AwsLogicalWorkload],
    zone: CentralNetworkingHostedZone,
    all_providers: AllAccountProviders,
) -> None:
    validate_no_cross_workload_pattern_overlap(delegate_configs)
    for cfg in delegate_configs:
        if cfg.workload_name not in workloads_info:
            raise ValueError(  # noqa: TRY003 # simple validation, no custom exception needed
                f"Workload '{cfg.workload_name}' not found in workloads_info. Available: {list(workloads_info.keys())}"
            )
        workload = workloads_info[cfg.workload_name]
        for account in workload.prod_accounts:
            _ = CentralNetworkingDnsDelegate(
                account=account,
                zone=zone,
                all_providers=all_providers,
                record_name_patterns=cfg.prod_record_patterns,
                github_repo_name=cfg.github_repo_name,
            )
        for account in workload.staging_accounts:
            _ = CentralNetworkingDnsDelegate(
                account=account,
                zone=zone,
                all_providers=all_providers,
                record_name_patterns=cfg.staging_record_patterns,
                github_repo_name=cfg.github_repo_name,
            )
        for account in workload.dev_accounts:
            _ = CentralNetworkingDnsDelegate(
                account=account,
                zone=zone,
                all_providers=all_providers,
                record_name_patterns=cfg.dev_record_patterns,
                github_repo_name=cfg.github_repo_name,
            )
