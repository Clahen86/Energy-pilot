from energy_pilot.telemetry import Telemetry


class C:
    def __init__(self, key):
        self.key, self.platforms = key, {}
        self.registry = [{"entity_id": "sensor.inv_soc", "platform": "sunsynk"}]

    def profile_key(self, part="battery"):
        return self.key

    def parts(self):
        return ["battery"]

    def mode(self, p):
        return "shadow"


class O:
    def __init__(self, key):
        self.settings, self.controller, self.engine = {"first_seen": "2026-11-01"}, C(key), None
        self.ha = type("H", (), {"config": {}})()

    def role(self, name):
        return "sensor.inv_soc" if name == "battery_soc" else None

    def save(self, d):
        pass


def make(key):
    t = Telemetry.__new__(Telemetry)
    t.ov = O(key)
    return t.daily()


def test_unknown_profile_sends_the_integration_name_only():
    assert make(None)["battery_integration"] == "sunsynk"
    assert "battery_integration" not in make("growatt")
