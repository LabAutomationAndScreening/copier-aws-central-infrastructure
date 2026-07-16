import base64
import json
from pathlib import Path
from typing import Any

import pulumi
from ephemeral_pulumi_deploy import append_resource_suffix
from pulumi import ResourceOptions
from pulumi_okta import AppGroupAssignments
from pulumi_okta import AppGroupAssignmentsGroupArgs
from pulumi_okta import Provider
from pulumi_okta.app import Saml
from pulumi_okta.app import SamlAttributeStatementArgs
from pulumi_okta.group import Group
from pydantic import BaseModel
from pydantic import ConfigDict


class SamlAppConfig(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    label: str
    assigned_groups: list[str] = []
    custom_saml_attributes: list[SamlAttributeStatementArgs] = []

    @property
    def saml_attribute_statements(self) -> list[SamlAttributeStatementArgs]:
        for attribute in self.custom_saml_attributes:
            if attribute.filter_type or attribute.filter_value:
                assert attribute.type == "GROUP", (
                    f"Only attributes of type 'GROUP' can have filter_type or filter_value. Error in attribute {attribute.name}"
                )
        return list(self.custom_saml_attributes)


class PreConfiguredSamlAppConfig(SamlAppConfig):
    preconfigured_app: str
    acs_url: str
    issuer_url: str


class AwsIdentityCenterAppConfig(PreConfiguredSamlAppConfig):
    preconfigured_app: str = "amazon_aws_sso"


class ManualSamlAppConfig(SamlAppConfig):
    logo: Path | None = None
    acs_url: str
    entity_id: str
    subject_name_id_template: str = "${user.email}"


class FyleAppConfig(ManualSamlAppConfig):
    custom_saml_attributes: list[SamlAttributeStatementArgs] = [
        SamlAttributeStatementArgs(
            name="firstName",
            type="EXPRESSION",
            namespace="urn:oasis:names:tc:SAML:2.0:attrname-format:basic",
            values=["${user.firstName}"],
        ),
        SamlAttributeStatementArgs(
            name="lastName",
            type="EXPRESSION",
            namespace="urn:oasis:names:tc:SAML:2.0:attrname-format:basic",
            values=["${user.lastName}"],
        ),
    ]


class ClaudeCodeAppConfig(ManualSamlAppConfig):
    subject_name_id_template: str = "${user.getInternalProperty('id')}"
    custom_saml_attributes: list[SamlAttributeStatementArgs] = [
        SamlAttributeStatementArgs(
            name="email",
            type="EXPRESSION",
            namespace="urn:oasis:names:tc:SAML:2.0:attrname-format:basic",
            values=["${user.email}"],
        ),
        SamlAttributeStatementArgs(
            name="firstName",
            type="EXPRESSION",
            namespace="urn:oasis:names:tc:SAML:2.0:attrname-format:basic",
            values=["${user.firstName}"],
        ),
        SamlAttributeStatementArgs(
            name="lastName",
            type="EXPRESSION",
            namespace="urn:oasis:names:tc:SAML:2.0:attrname-format:basic",
            values=["${user.lastName}"],
        ),
        SamlAttributeStatementArgs(
            name="groups",
            type="GROUP",
            namespace="urn:oasis:names:tc:SAML:2.0:attrname-format:unspecified",
            filter_type="REGEX",
            filter_value=".*",
        ),
    ]


def create_apps(
    *,
    app_configs: list[SamlAppConfig],
    group_objects: dict[str, Group],
    provider: Provider,
):
    for app_config in app_configs:
        resource_safe_name = app_config.name.lower().replace(" ", "-")
        if isinstance(app_config, PreConfiguredSamlAppConfig):
            app_settings_dict: dict[str, Any] = {}
            if isinstance(app_config, AwsIdentityCenterAppConfig):
                app_settings_dict = {
                    "acsURL": app_config.acs_url,
                    "entityID": app_config.issuer_url,
                }
            app = Saml(
                append_resource_suffix(resource_safe_name),
                label=app_config.label,
                preconfigured_app=app_config.preconfigured_app,
                app_settings_json=json.dumps(app_settings_dict) if app_settings_dict else None,
                attribute_statements=app_config.saml_attribute_statements,
                opts=ResourceOptions(
                    provider=provider,
                ),
            )
        elif isinstance(app_config, (ClaudeCodeAppConfig, FyleAppConfig)):
            app = Saml(
                append_resource_suffix(resource_safe_name),
                label=app_config.label,
                logo=str(app_config.logo) if app_config.logo else None,
                sso_url=app_config.acs_url,
                recipient=app_config.acs_url,
                destination=app_config.acs_url,
                audience=app_config.entity_id,
                subject_name_id_format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
                subject_name_id_template=app_config.subject_name_id_template,
                signature_algorithm="RSA_SHA256",
                digest_algorithm="SHA256",
                authn_context_class_ref=("urn:oasis:names:tc:SAML:2.0:ac:classes:PasswordProtectedTransport"),
                assertion_signed=True,
                response_signed=True,
                attribute_statements=[
                    *app_config.saml_attribute_statements,
                ],
                opts=ResourceOptions(provider=provider),
            )
        else:
            # TODO: with the addition of ManualSamlAppConfig, this code path with a few more examples or config changes can probably go away and we can simply
            # have manual and preconfigued apps with enough configurability that we can cover all cases
            raise NotImplementedError(
                f"How to handle {app_config.name} is not implemented. Please provide a preconfigured_app or implement it."
            )
        _ = AppGroupAssignments(
            append_resource_suffix(resource_safe_name),
            app_id=app.id,
            groups=[
                AppGroupAssignmentsGroupArgs(id=group_objects[group_name].id, profile=json.dumps({}))
                for group_name in app_config.assigned_groups
            ],
            opts=ResourceOptions(provider=provider),
        )
        pulumi.export(f"{resource_safe_name.upper()}-METADATA", app.metadata)
        pulumi.export(
            f"-{resource_safe_name}-metadata-b64-encoded",
            app.metadata.apply(lambda metadata: base64.b64encode(metadata.encode("utf-8")).decode("utf-8")),
        )
