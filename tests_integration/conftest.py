import custom_components.energy_pilot  # noqa: F401 - so the loader finds this custom_components
import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield
