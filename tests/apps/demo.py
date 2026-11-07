import appdaemon.plugins.hass.hassapi as hass
import json


class Demo(hass.Hass):
    def initialize(self):
        self.seen = []
        self.listen_state(self.on_soc, "sensor.soc")
        self.run_in(self.tick, 0)

    def tick(self, kwargs):
        soc = float(self.get_state("sensor.soc"))
        self.call_service("number/set_value", entity_id="number.battery_target", value=soc + 10)
        self.set_state("sensor.demo_plan", state="charge" if soc < 50 else "hold", attributes={"soc": soc})
        with open("/config/demo_state.json", "w") as f:
            json.dump({"soc": soc}, f)

    def on_soc(self, entity, attribute, old, new, kwargs):
        self.seen.append(new)
        self.tick({})
