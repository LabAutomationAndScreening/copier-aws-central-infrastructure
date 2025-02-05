from typing import TYPE_CHECKING

import boto3
from ephemeral_pulumi_deploy.utils import common_tags
from pulumi import ComponentResource
from pulumi import ResourceOptions
from pulumi_aws_native import Provider
from pulumi_aws_native import ssm

from .github_oidc_lib import WorkloadName
from .shared_lib import WORKLOAD_INFO_SSM_PARAM_PREFIX
from .shared_lib import AwsLogicalWorkload

if TYPE_CHECKING:
    from mypy_boto3_ssm.type_defs import ParameterMetadataTypeDef


class WorkloadParams(ComponentResource):
    def __init__(
        self,
        *,
        name: str,
        params_dict: dict[str, str],
        provider: Provider,
    ):
        super().__init__("labauto:AwsWorkloadParams", name, None)
        # replicate the workload information into the Identity Center account
        for param_name, param_value in params_dict.items():
            workload_name = param_name.split("/")[-1]
            _ = ssm.Parameter(
                f"{workload_name}-workload-info-for-{name}",
                type=ssm.ParameterType.STRING,
                name=param_name,
                description=f"Hold the logical workload information for {workload_name} so that {name} account can access it for easy reference.",
                tags=common_tags(),
                value=param_value,
                opts=ResourceOptions(provider=provider, parent=self, delete_before_replace=True),
            )


def load_workload_info(
    *, organization_home_region: str
) -> tuple[dict[WorkloadName, AwsLogicalWorkload], dict[str, str]]:
    ssm_client = boto3.client("ssm", region_name=organization_home_region)

    parameters: list[ParameterMetadataTypeDef] = []
    next_token = None

    while True:
        # API call with optional pagination
        response = ssm_client.describe_parameters(
            ParameterFilters=[{"Key": "Name", "Option": "BeginsWith", "Values": [WORKLOAD_INFO_SSM_PARAM_PREFIX]}],
            MaxResults=50,  # AWS allows up to 50 results per call
            NextToken=next_token if next_token else "",
        )

        # Add parameters from this page
        parameters.extend(response.get("Parameters", []))

        # Check if more pages exist
        next_token = response.get("NextToken")
        if not next_token:
            break

    def get_parameter_value(name: str) -> str:
        response = ssm_client.get_parameter(  # TODO: consider using get_parameters for just a single API call
            Name=name,
        )
        param_dict = response["Parameter"]
        assert "Value" in param_dict, f"Value not found in parameter {param_dict}"
        return param_dict["Value"]

    param_values: list[str] = []
    params_dict: dict[str, str] = {}
    for param in parameters:
        assert "Name" in param, f"Name not found in parameter {param}"
        param_name = param["Name"]
        param_value = get_parameter_value(param_name)
        param_values.append(param_value)
        params_dict[param_name] = param_value

    workloads_info = [AwsLogicalWorkload.model_validate_json(param) for param in param_values]
    workloads_dict: dict[WorkloadName, AwsLogicalWorkload] = {workload.name: workload for workload in workloads_info}
    return workloads_dict, params_dict
