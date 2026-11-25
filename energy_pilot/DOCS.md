# Energy Pilot

Runs your energy system (battery, solar, EV charging) as an app. It always starts in **shadow**: it plans and shows
what it would do, but controls nothing. Each part can be set to *Shadow*, *Control* or *Off* in the panel, and
**Everything to shadow** stops all control with one tap.

Open **Energy Pilot** in the sidebar to set it up. The panel follows your Home Assistant language
(English, Danish, German, French, Dutch, Swedish, Norwegian).

More: https://github.com/Clahen86/Energy-pilot

## Your own inverter with scripts

No profile for your inverter? Energy Pilot can run your own Home Assistant scripts instead. Make one script for each
step, then pick them under **Settings → House battery → Inverter control → Chosen by you (any brand)** (**+ Add step** under each step).

| Step | What your script must make the inverter do |
|---|---|
| **Normal** | Run on its own again (self-use): the battery covers the house and takes the sun. |
| **Hold** | Keep the power in the battery: don't discharge (the sun may still charge it). |
| **Charge** | Charge from the grid up to `target` % at about `power_w` W. |
| **Sell** (optional) | Discharge to the grid down to `target` % at about `power_w` W. Only used if you allow selling. |

Each script gets these variables, used as `{{ target }}` and so on:

| Variable | Meaning |
|---|---|
| `target` | The level the battery should reach (%) |
| `soc` | The battery's level now (%) |
| `min_soc` | Your minimum (%) |
| `power_w` / `power_kw` | The power the plan wants to charge or sell with |
| `export_w` | How much may be sold |

Example (the entity names are made up - use your inverter's own):

```yaml
inverter_normal:
  alias: Inverter normal
  sequence:
    - action: select.select_option
      target: { entity_id: select.my_inverter_work_mode }
      data: { option: "Self Use" }
    - action: number.set_value
      target: { entity_id: number.my_inverter_discharge_power }
      data: { value: 5000 }

inverter_hold:
  alias: Inverter hold
  sequence:
    - action: select.select_option
      target: { entity_id: select.my_inverter_work_mode }
      data: { option: "Self Use" }
    - action: number.set_value
      target: { entity_id: number.my_inverter_discharge_power }
      data: { value: 0 }

inverter_charge:
  alias: Inverter charge
  sequence:
    - action: number.set_value
      target: { entity_id: number.my_inverter_charge_target_soc }
      data: { value: "{{ target }}" }
    - action: number.set_value
      target: { entity_id: number.my_inverter_charge_power }
      data: { value: "{{ power_w }}" }
    - action: select.select_option
      target: { entity_id: select.my_inverter_work_mode }
      data: { option: "Force Charge" }

inverter_sell:
  alias: Inverter sell
  sequence:
    - action: number.set_value
      target: { entity_id: number.my_inverter_discharge_target_soc }
      data: { value: "{{ target }}" }
    - action: number.set_value
      target: { entity_id: number.my_inverter_discharge_power }
      data: { value: "{{ power_w }}" }
    - action: select.select_option
      target: { entity_id: select.my_inverter_work_mode }
      data: { option: "Force Discharge" }
```

Then run the **self-test** (**Test your system**): it checks that the battery really holds, charges and goes back to
normal with your scripts.
