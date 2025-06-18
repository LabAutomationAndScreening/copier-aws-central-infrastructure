import base64
import json
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


class SamlAppConfig(BaseModel):
    name: str
    label: str
    preconfigured_app: str | None
    assigned_groups: list[str] = []


class AwsIdentityCenterAppConfig(SamlAppConfig):
    acs_url: str
    issuer_url: str
    preconfigured_app: str | None = "amazon_aws_sso"


class FyleAppConfig(SamlAppConfig):
    preconfigured_app: str | None = None
    acs_url: str
    entity_url: str


def create_apps(*, app_configs: list[SamlAppConfig], group_objects: dict[str, Group], provider: Provider):
    for app_config in app_configs:
        resource_safe_name = app_config.name.lower().replace(" ", "-")
        if app_config.preconfigured_app is not None:
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
                opts=ResourceOptions(
                    provider=provider,
                ),
            )

        else:
            if not isinstance(app_config, FyleAppConfig):
                raise NotImplementedError(
                    f"How to handle {app_config.name} is not implemented. Please provide a preconfigured_app or implement it."
                )
            app = Saml(
                append_resource_suffix(resource_safe_name),
                label=app_config.label,
                sso_url=app_config.acs_url,
                recipient=app_config.acs_url,
                destination=app_config.acs_url,
                audience=app_config.entity_url,
                subject_name_id_format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
                subject_name_id_template="${user.email}",
                signature_algorithm="RSA_SHA256",
                digest_algorithm="SHA256",
                authn_context_class_ref=("urn:oasis:names:tc:SAML:2.0:ac:classes:PasswordProtectedTransport"),
                assertion_signed=True,
                response_signed=True,
                attribute_statements=[
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
                ],
                opts=ResourceOptions(provider=provider),
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
