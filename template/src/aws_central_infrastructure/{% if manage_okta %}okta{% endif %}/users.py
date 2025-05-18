from .lib import OktaUserConfig


def define_user_configs(configs: list[OktaUserConfig]) -> None:
    """Create the configurations for the Users.

    example: ```
        configs.append(
            OktaUserConfig(
                username="eli.fine@zombo.com", email="eli.fine@zombo.com", first_name="Eli", last_name="Fine"
            )
        )
    ```
    """
    _ = configs  # this line can be removed once the first team is appended on to configs, it just temporarily helps linting when the template is instantiated
