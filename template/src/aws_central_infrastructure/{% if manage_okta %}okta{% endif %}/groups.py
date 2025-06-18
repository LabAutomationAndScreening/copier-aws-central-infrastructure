from .lib import OktaGroupConfig


def define_group_configs(configs: list[OktaGroupConfig]) -> None:
    """Create the configurations for the Users.

    example: ```
        configs.append(
                OktaGroupConfig(
                    name="All Employees",
                    description="everybody",
                    assigned_users=[
                        "eli.fine@zombo.com",
                    ],
                )
            )
        )
    ```
    """
