# Changelog – Energy Pilot

Newest first. Each version lists what changed since the one before.

## 0.115.0 – 2026-11-27
- Battery efficiency measured on the grid: each time the battery starts or stops, the jump on the grid meter shows what it really takes and gives, the inverter's own loss included. Shown under "What it has learned" - the plan doesn't use it yet
## 0.114.3 – 2026-11-27
- Car: "Ready at" is back for a car picked from the list that has no ready time yet - the field was hidden, so there was no way to set one
## 0.114.2 – 2026-11-26
- Import limit: the battery's grid charge gives way within a minute when the house suddenly uses more than expected (the oven, the kettle), so the house stays under the limit - the car already did this
## 0.114.1 – 2026-11-26
- Big batteries (over 25 kWh) plan in 1 % steps - a 2 % step was more than the house used in an hour, so the plan charged too little at night. Thanks to @mbuhansen
- The value of what the battery holds at the day's end is learned right: an empty battery no longer looks free (the learned value starts again from neutral, once). Thanks to @mbuhansen
- The sun is sold only when selling beats storing it; Kostal holds the battery with Block Charge while the sun is sold. Thanks to @mbuhansen
- Kostal hybrids: the sun and the battery share the inverter's AC power. Thanks to @mbuhansen
## 0.114.0 – 2026-11-26
- New install: "Would have saved a month" in the savings card the first two weeks - worked out on the home's own last 30 days, the battery on the inverter's own control against Energy Pilot's plan (taken down a little, as the plan knew each day in advance)
- "Ready to take over?" after three days in shadow with the self-test passed: "Try control for 24 hours" - it goes back to shadow by itself afterwards (also after a restart) and says what the day saved, with "Keep controlling"
- Share: a small icon on the savings makes a picture of the month's amount and its days, for Facebook and the like - no names, no address
## 0.113.2 – 2026-11-26
- Two or more batteries: with no spare sun, none of them may charge on "normal" - one can no longer fill itself from the other (each kept the grid at zero on its own, and power went round in a circle)
- The house meter is never swapped while a battery's power isn't read - with one battery missing the meters can't add up, and a right house meter was swapped for one that reads 0 W at night
## 0.113.1 – 2026-11-26
- Sell fee (Settings → Grid, when selling is on): what selling one kWh costs, such as your supplier's fee - taken off every sell price, so the plan only sells when it still pays. Thanks to @mbuhansen
- Kostal PLENTICORE L G3: "G3" is the generation, not 3 kW - the plan no longer holds grid charging to 3 kW. Thanks to @mbuhansen
## 0.113.0 – 2026-11-26
- Things that run cheaply: pool pump. Set its hours a day - it runs them every day, on the sun first and the rest in the cheapest hours before midnight. Turned on by hand it stays on and the time counts. A pool pump on a smart plug is found by itself
## 0.112.0 – 2026-11-26
- Power tariff: "Counts only in" - weekdays, from-to and months. Many grid companies count only daytime hours on weekdays in winter: the month's peak is then measured only in those hours, and the plan charges freely at night and on weekends (up to your import limit)
- Outside Denmark: one field for taxes and surcharge per kWh (energy tax plus your supplier's surcharge, excl. VAT) instead of the three grid tariff fields - VAT is added by itself. It also shows with Home Assistant's own Nord Pool, whose price is the bare spot price, and is added to it
- An "Own tariff" chosen but never filled in no longer hides your own price sensor (there were no prices, no plan, and the shadow days never started counting)
- A change to taxes, tariff or price area is used at once
## 0.111.3 – 2026-11-26
- Savings: today shows what you really paid - power bought for the battery counts when it's bought, and the saving comes when it's used
## 0.111.2 – 2026-11-26
- Cars: the "plugged in" sensor can be picked from the integration your car's battery level comes from, whatever the brand (Lynk & Co's charger connection status couldn't be picked). "Not plugged in" counts as not plugged in
- The inverter's own grid limit (peak shaving) set lower than your limit here is found in the settings check - the inverter turned the battery down by itself at that number. "Fix it" sets it to your limit
## 0.111.1 – 2026-11-25
- Setup: what was found is shown with its numbers live and in words ("discharging 3.0 kW", "buying 515 W"), with a green "The numbers add up" or a red line when a sensor looks wrong. "Fix" opens just that one choice; all sensors are behind "Show all sensors"
- No internet: after 15 minutes the app says so (and the Problem sensor turns on) - the plan runs on the last known prices and its own guesses, and everything at home is still controlled. With an inverter controlled through its maker's cloud it says the battery can't be steered until the internet is back
- Your own setup with scripts: a short example in the app, and a full guide with all four scripts in the Documentation tab
## 0.111.0 – 2026-11-25
- Sigenergy: hold no longer charges from the grid ("Command Charging (PV First)" is a grid charge) - it is self-consumption with discharging at 0
- Tesla Powerwall and Enphase: hold sets the reserve to the level rounded down and turns grid charging off - a reserve above the level made them charge from the grid
- Huawei: a forced charge is always ended with the integration's stop service - without the "Stop forcible charge" button it ran on into the dear hours
- SolarEdge: "Advanced Power Control" is turned on when there. GivTCP: "Enable charge target" is turned on to charge. Sunsynk add-on: the other entity names (Prog1 charge option, Set SoC timezone1) are found too
- Luxpower: the settings check no longer offers the level Energy Pilot holds at as your minimum (it could ratchet it up)
- Ohme and myenergi zappi are handed back to their own mode (smart charge / Eco+) when Energy Pilot lets go
- New profiles: Victron through Home Assistant's own Victron GX integration, Luxpower (LuxPython), Solis FB00+ (SolaX Modbus), SolaX Gen4+ by remote control (picked by hand) and Canadian Solar EP Cube
- Your own setup can run your own scripts for each step (normal, hold, charge, and an optional sell), with the plan's target, level and power as variables - for any inverter without a profile
- Self-test: cloud inverters (Fox cloud, Growatt cloud, Anker, EP Cube) get 10 minutes to react, and a nearly full or cold battery is judged more gently
- The plan knows the inverter's AC power (from its rated-power sensor or its model's name): it doesn't plan to charge from the grid or discharge faster than the inverter can
- Without Solcast, the plan learns the forecast's own poor days and counts on a little less sun when the forecast is unsure
- Water heaters with a temperature of their own heat 10 °C extra on sun that would otherwise be sold cheaply, and go back when it's gone
## 0.110.3 – 2026-11-25
- Savings: "Sun and battery" today now counts the power still in the battery at what it cost, like "Battery" does - it could show less saved today than the battery alone
## 0.110.2 – 2026-11-25
- Easee (and other known chargers) with your own start/stop switch chosen: the charger keeps its own control of the current, pause and resume, and your switch starts and stops it as well. Before, only the switch was used and the current was lost
- Sofar (ZCS Azzurro) on the new Solarman integration is no longer called the old, read-only one, and the hint says "Deye / Sofar" instead of "Deye"
- Self-test: a failed step says why without names (the kind of refusal, or where the controls came from) - so faults can be mended from the data
## 0.110.1 – 2026-11-25
- Cars: the "plugged in" sensor list shows only sensors from the car's own integration (Tesla, VW, Kia …), never the charger's - the charger already tells that a car is in it. A line under the field says to pick None when the car isn't in Home Assistant
## 0.110.0 – 2026-11-25
- More cars than chargers: a list of cars under Settings → Car, each with its own name, battery level and "plugged in" sensor (when the car is in Home Assistant) and battery size. A car without Home Assistant needs only a name and a size
- Each charger finds the car in it by itself: the car whose own sensor says it is plugged in; else, once each car has 3 charges behind it, by the power it takes (only when the cars charge clearly differently); else the same car as last time
- "Car in the charger" on the car card, the dashboard card and in the companion: pick it with one tap - it stays until the car is unplugged
- The charger uses the level, size, target, ready time, at most and 100 % for the trip of the car in it
- Under Settings each car shows what it takes ("Takes about 3.7 kW, 5 charges")
- Without a list of cars nothing changes
## 0.109.0 – 2026-11-25
- Extra cars like the first one: pick the car's battery level (and its size) under Settings → Car, and it charges to a target in % instead of a set number of kWh. Its card has the level, the target (60–100 %), 100 % for the next trip (off by itself when the car leaves full), Charge now and Ready at
- "Charge now" on an extra car acts at once, not at the next round
- The dashboard card shows every extra car under the first: level, planned hours and buttons
- Companion 1.2.0: each extra car gets its own entities - Charge now, Ready at, Charge to (or At most), 100 % for next trip and Next charge - named after the car
## 0.108.1 – 2026-11-25
- New profile "Deye / Sunsynk (Sunsynk add-on)": the kellerza Sunsynk add-on's six programmes (Prog1 capacity, Prog1 charge, Use timer). Found by itself - a Deye on the add-on no longer gets the Solarman profile, which has none of its controls
- Controls with Home Assistant's "_2" at the end (a re-added integration, e.g. select.rc_force_charge_discharge_2 on Solis) are now found by every profile
- Savings: a battery reading that can't be real (above 50 kW - a wrong unit, W taken as kW) is no longer counted. A day that was counted that way (thousands saved in one day) is set to nothing, once
- "Move the integration to the Marketplace": the address is on its own line again, not one letter per line
- The charging curve has names on its axes (battery level, charging speed), and the card is in French, Swedish and Norwegian too
- House model: learning with exactly one week of data no longer crashes (#59)
## 0.108.0 – 2026-11-25

- New optional role "Other generation (wind, hydro …)" under Sun: power made on the spot that can't be switched, such as a small wind turbine. It counts in the energy balance (house, surplus for the car, savings) and shows in the flow as "SUN · OTHER", but stays out of the solar forecast, solar learning and the shared hours. No forecast for it yet: the plan uses it as it comes
- English outside the app: the add-on's name, description, sidebar title and docs tab are now in English (Energy Pilot), and the texts on sensor.energipilot follow Home Assistant's language instead of falling back to Danish. The companion device is called Energy Pilot (existing entity ids stay)

## 0.107.8 – 2026-11-24

- Savings, "Energy Pilot's own part": power bought cheaply and still in the battery at the end of the day no longer counts as a loss. The comparison with the inverter's own control now counts what each battery holds more than the other at what that power cost. Earlier days keep their old figure

## 0.107.7 – 2026-11-24

- Home Assistant's Mac app: tapping a time field (battery targets, your own tariff, "ready by") no longer crashes the whole app. In the Mac app only, time fields are plain text (07:30); "730" or "7.30" is understood. Browsers and the phone apps keep the normal time picker

## 0.107.6 – 2026-11-24

- Wallbox: "Ready" means no car is plugged in (and "Locked" that it can't charge) - the self-test no longer runs without a car and calls the charger broken. The same for Peblar's "no EV connected"
- Self-test "normal": a battery resting at your own minimum is no longer a fault (it used a fixed 20 %, so a Sungrow at 30 % failed)

## 0.107.5 – 2026-11-24

- Battery tile on the front page and in the card: kWh in the battery is the big number, with the % and what can still be used down to your minimum below it. The whole tile now updates live, not just the % (#47)

## 0.107.4 – 2026-11-24

- A Deye whose model fits but that has none of Solarman's controls (through deye_modbus or Solar Assistant/MQTT) no longer gets the Solarman profile - the self-test found no controls there (#62, #63, #64)
- Self-test, selling from the battery: when the battery discharges but nothing is sold, it says "export limit, or the house used it" instead of a fault (#61)
- The shared house model can be fetched again (the report service answered every GET before reaching it)

## 0.107.3 – 2026-11-24

Thanks to mbuhansen for all four:

- After a start, the controls are looked up before the first plan - selling is no longer shown as blocked until the next round (#56)
- Fixed by itself: an OK button next to Undo hides the line and keeps the fix (#54)
- Detailed plan: a running total hour by hour, starting from what today really cost so far, and a sum for each day (#55)
- Detailed plan: an hour at the battery's floor says "Holding", not "Covers the house" (#57)

## 0.107.2 – 2026-11-24

- A profile chosen by hand that finds none of its controls, while another profile fits, is replaced by the one that fits (Fox ESS through Modbus with "Fox ESS (cloud)" chosen found no controls). The choice in Settings shows it, and the change log says Energy Pilot changed it

## 0.107.1 – 2026-11-24

- SolaX read through its own integration and controlled through SolaX Modbus (two devices): the SolaX Modbus controls are now found, instead of "7 controls missing" and a self-test that found no controls

## 0.107.0 – 2026-11-23

New brands:
- SolaX Gen2/Gen3 and Growatt through SolaX Modbus - picked by their own controls, Gen4 and later keep their profile
- Off-grid inverters through ESPHome (Growatt SPF, SRNE, Voltronic/MPP): grid or battery first, and charging from the grid
- Luxpower / EG4 through MonitorMySolar, Zendure SolarFlow/Hyper (Zendure-HA), EcoFlow PowerOcean (local Modbus), Marstek Venus (local API), and Voltronic/Axpert over MQTT (chosen by hand)
- Kostal (its own integration) and the old Solarman integration only read: a button now opens the integration that can control them

Fixes:
- Homes with Powerwall, Solis, GoodWe (SEMS) and a few others lost all their checks and warnings - two lists had the same name in the code
- Huawei: charging from the grid turns on "Charge from grid" (and its limits) while it charges, and puts your own values back after
- SolaX through Home Assistant's own integration (read only): says to install SolaX Modbus instead of failing
- Wallbox: starting a charge no longer pauses the charger ("pause/resume" is on while charging)
- A known charger (Wallbox, Zaptec, Peblar, Hypervolt …) keeps its own way to start and stop, also with its switch chosen by hand
- The car's self-test is skipped when the car isn't plugged in, instead of counting as a fault

Learning together:
- The shared house model trained every night on the homes that share their hours can now be used as a third forecast. It is sent out only when it clearly beats the homes' own forecasts on days it hasn't seen, is checked before use, gets no say in a home for three weeks, and loses it again by itself if it misses. Until there's enough data, nothing changes
- The shared start values for the nightly tuning now reach Energy Pilot (they were left out)

## 0.106.1 – 2026-11-23

From the nightly self-test reports:
- Anker SOLIX through Anker's own integration (Solarbank 4 E5000 Pro and others, local Modbus): its own profile - found and controlled by itself (#51)
- Deye single-phase (SG0*LP1) through Solarman: holding the battery sets the limit 1 % above the level now - it kept discharging at the level itself (#53)
- SolarEdge (Modbus Multi): holding stops discharging and lets the sun cover the house first; only the timer and the command are written again every 30 minutes, so the inverter's flash isn't worn; homes without battery control get a hint where to turn on Storage Control (#50)
- FoxESS H3 Pro / H3 Smart: the self-test says when charging fails because of a known bug in the FoxESS integration (#1244, fixed there but not released), and a sale the sun covered is tried again another time instead of failing (#52)

## 0.106.0 – 2026-11-23

- The companion integration can now come from the Marketplace (HACS): repository Clahen86/energy-pilot-companion. Then it serves the dashboard card itself and the app never touches it - the first step to the app needing no access to Home Assistant's folder. Have it from the app? The front page shows how to move it, in three steps
- The add-on only answers Home Assistant itself and its login (ingress): other containers on Home Assistant's network can't reach the panel
- Dashboard card: a new **Status** view (what it does now and why, what comes next, battery, house and price - small, for a phone), the battery's level the next 24 hours in the Battery view, and the car folded to one line when it isn't plugged in
- New entities: **Problem** (on when something needs a look), **Price level** (cheap / normal / dear) and **Battery health** (what it holds against its label)

## 0.105.0 – 2026-11-23

Safety and honesty - after a careful review of the code by a user:
- Yesterday's use hour by hour and your area (about 10 km) are sent only when you say yes. The front page asks once and tells you what you get for it (the sun forecast corrected by your neighbours' sun, a warning when the power is out nearby, better forecasts for everyone). It's under Settings too
- Shared fixes go out only once the developer has approved them, and a shared fix can never turn charging into selling or the other way round, or pick a mode that could take the house off the grid
- Changes are only taken as JSON from the panel itself, so another web page can't turn control on or change the settings
- Docker: the panel asks for a password (EP_PASSWORD, or one written to the log at the first start)
- The add-on no longer reads other add-ons' configuration
- The README says exactly what is sent, and what the add-on may reach

Plan:
- A big battery covers the whole house in the plan, not one 2 % step of it with the rest bought (#45, thanks @mbuhansen)
- No "tomorrow's prices are estimated" when all of tomorrow is known (#46, thanks @mbuhansen)
- Charging hours on the chart can be tapped again (#47, thanks @mbuhansen)
- Plan → "Detailed plan": hour by hour what the battery does, bought and sold, and the cost (#48, thanks @mbuhansen)

## 0.104.2 – 2026-11-23

- Sungrow (mkaiser Modbus): back to self-consumption, the forced charge/discharge command is set to "Stop (default)" too, as mkaiser's own scene does. Left on "Forced charge", the battery kept charging from the grid after a charge (#42)
- Car: a "ready at" from a timestamp sensor (evcc's departure time) shows as local time - it said "2026-" (#43, thanks @mbuhansen)
- Settings > Car: pick the charger once, and its power, plug, charged energy, car level and departure time are filled in from it. evcc's loadpoints are listed too (#44, thanks @mbuhansen)

## 0.104.1 – 2026-11-23

- Fox ESS through its cloud (the foxess integration) has its own profile: it was taken for Fox ESS Modbus by its names, so "Force Charge" was refused and charging and selling never worked. Charging and selling now go through Fox ESS's Mode Scheduler, and the scheduler is turned off before the work mode is changed
- The self-test says "found no controls" when a step had nothing to send, instead of "no reaction" from the inverter

## 0.104.0 – 2026-11-23

Finding your setup - learned from a Fox ESS house in the UK ("Export not shown") and the shared setups:
- The meters must add up: sun + grid = house + battery. When they don't for two hours, Energy Pilot finds the one sensor that makes them add up (or a battery or grid read the wrong way round) and uses it - shown with an undo. If nothing fits, it says so
- Grid power as two one-way sensors (Fox ESS "Grid Consumption" + "Feed-in", "import" + "export" power): buying less selling, so selling shows. Before, only buying was seen
- The grid's buying sensor was taken for the house's use (Fox ESS), so the house forecast learned the night charging as the house. Never again - and the inverter's plainest-named sensor wins, not the first one in the list
- Another sensor chosen: the house forecast learns from it within minutes, not after a day
- Never taken for the house battery: Hive, a car through EUDA or any sensor with a car's VIN, an energy meter's own battery, garden, leak, humidity or window sensors - and "battery level" alone only with a home battery's power found
- Never taken for the car charger: an e-bike, a scooter, a mower or a robot
- Never taken for another part: a generator or a solar string for the battery, "energy flow" or the grid for the sun, a "load" for the grid, "solar to house" or the battery's output for the house
- New profiles (being tested): GivEnergy through GivTCP, Anker SOLIX (Solarbank 2/3/4, Max AC)
- GoodWe through SEMS and Solis through its cloud: a button that opens the integration that can control them
- Undo now works for "a sensor stopped answering"
- Shared setups send up to 60 controls per device (the ones in use first) - a Fox ESS's switches were cut off

From @mbuhansen - thank you:
- New profile (being tested): Kostal Plenticore through Kostal Plenticore Battery Control (Modbus). The plan stays inside the inverter's own minimum and maximum SoC, its top battery power is used, the main fuse is read from the integration, and the self-test waits while the inverter wakes up at night
- Car: a field for the battery's size; a plug-in hybrid's small battery is learned; evcc's size is used until then; the plan counts on the power the car really takes (a car on one phase behind an 11 kW charger takes 3.7 kW)
- evcc gets its own planning ("smart") back when Energy Pilot lets go of the car - it stayed at "off" or "now"; and a hint when no charger controls are found

## 0.103.0 – 2026-11-22

Learned from what users' setups look like:
- Controls are also found by the integration's own key, so entity names in Swedish, Italian or any language work (a Swedish Wallbox wouldn't start)
- Sungrow with mkaiser's Modbus package: its battery controls have no device and were never found - now they are
- New profiles (being tested): Sungrow (sungrow-hass), myenergi libbi, Marstek Venus, Luxpower (lxp_modbus), E3DC
- Finding your setup: a door lock's or a tablet's battery is never taken for the house battery, a solar sensor (Kostal) or an energy sensor (kWh) never for the car charger's power, and a power sensor never for the feed-in price
- A battery integration that can only read says so - with the one that can control it (Powerwall → Teslemetry, Solis cloud → Solis Modbus, GoodWe SEMS → GoodWe local) - and a battery another system already runs (Zendure with omnibattery) is left to it

## 0.102.3 – 2026-11-22

- What if and Electricity deals: amounts in whole money ("61 kr" instead of "61,00 kr"), the cheapest deal stands out, and the deal links are easier to see
- The charging curve's "100 %" is no longer cut off
- README: the new features, with new pictures

## 0.102.2 – 2026-11-22

- Pick your own electricity deal right away: under Settings → Electricity price ("Your deal"), and on the deals card, which now shows from the start ("collecting data – the comparison comes in X days") instead of only after 7 days

## 0.102.1 – 2026-11-22

- "Plan vs. real" could stay empty: one broken line in the plan log (left by a power cut) stopped the reading, so every plan after it was missing - and the log was never trimmed. Broken lines are now skipped and the log cleans itself up. The chart is back the morning after updating

## 0.102.0 – 2026-11-22

Ideas many people know from other battery planners, made to work by themselves - no new settings to learn.

- The car and the house battery: the car's charging is now part of the battery plan. The battery only helps the car with what the house won't need before the sun or cheap power fills it again - never on a dear evening, and the morning is always kept for the house. "Right now" says which it does. Without grid charging, a charger that can be turned down (Keba, Easee …) gives the battery the sun first
- An unsure sun forecast (Solcast's poor day far below the expected) makes the plan count on a little less sun
- Gentle charging: when hours cost about the same, the battery charges calmly over them instead of at full power in one
- Nobody home for a day: the plan counts on the house's standby use until someone is back
- A cold battery charges slower - learned from its own temperature, and shown as a curve with the slowdown near full
- A limit on selling is found by itself, and the plan keeps room in the battery for sun that would otherwise be lost
- Your own hours: tap an hour in the plan and choose Charge here, Sell here or Keep the power
- A water heater on a switch is found by itself and rests in up to 4 dear hours a day - the water stays hot
- What if: a new card shows what a bigger battery, more panels or no battery would have meant on your last 30 days
- Electricity deals: which deal would have been cheapest for your use, each worked out with its own battery plan - all deals in Denmark (elpris.dk), Octopus in the UK, every retailer in Australia, Italy's open offers, US utility tariffs; elsewhere hourly against fixed. Pick your own deal to see what you'd save. Hide it with ✕
- Octopus Power Down (Saving) Sessions are joined by themselves and planned for
- Hypervolt chargers can be controlled
- A report now carries the last 48 hours, so a problem can be replayed

## 0.101.1 – 2026-11-22

- Fox ESS (Modbus): selling from the battery could do nothing - the hold step had set the on-grid minimum to the battery's level, and selling didn't put it back. Selling now sets your own minimum first
- A car's battery is no longer taken for the house battery when the car comes in through MQTT (TeslaMate) or a data service - any device a car maker made. Tesla Powerwall and BYD Battery-Box still count
- Another appliance's power (an aircon, a heat pump, a dryer …) is no longer taken for the car charger's
- Settings tell you when the car charger's power looks like another appliance, or when the house battery's level comes from a car or a phone - picked earlier, now pointed out (never changed by itself)

## 0.101.0 – 2026-11-22

- A better start for new homes: until its own nightly test has run on 5 of its own days, a new home starts from the settings that similar homes found for themselves - only homes with the same inverter brand, country, battery size and car or not, and only when at least three of them agree. Brands are never mixed. From then on the home's own test takes over as before, and homes that already found their own settings are left alone. The panel shows "starting from X similar homes" while it's in use

## 0.100.0 – 2026-11-22

- Update automatically: a card on the front page offers to turn on Home Assistant's own "Auto update" for Energy Pilot, so fixes come by themselves. Only when you press "Turn on" - "No thanks" keeps it away, and it can be turned off again under Settings → Add-ons

## 0.99.6 – 2026-11-21

- A phone's battery is never taken for the house battery, not even when it was picked by hand: Energy Pilot then finds the real battery by itself, and phones are no longer in the list. A picked phone had left the battery without a profile, so nothing was controlled (found in a tester's report)
- The test no longer fails "Charge from the grid" on a battery that can't charge from the grid (EcoFlow PowerStream, Megarevo): the step is skipped and says why - the station charges through its own AC charging, for example a smart plug under Things

## 0.99.5 – 2026-11-21

- The inverter's own time slot (Growatt, GivEnergy) now also starts 2 hours back, so a clock that runs slow - not only fast - can't keep the charging from starting. With a right clock nothing changes: the slot is only turned on when the plan's block begins and off again when it ends

## 0.99.4 – 2026-11-21

- An inverter clock that runs wrong no longer stops the charging early: the inverter's time slot now ends 2 hours after the plan's block (Energy Pilot still ends the block itself on time). A Growatt whose clock was 70 minutes ahead - never moved to winter time - left its slot early and covered the house from the battery instead
- Growatt: the work mode is written first and the time slot last, so SolarAssistant's all-day "Battery first" slot can't put itself over Energy Pilot's
- When the inverter leaves what it was told by itself, Energy Pilot notices within a minute instead of up to five
- In countries with summer time: for a week after the clocks change, a note asks you to check the inverter's own clock (only for inverters steered by time slots - Growatt, GivEnergy, Alpha ESS)

## 0.99.3 – 2026-11-21

- Charge windows follow the plan's whole block: the inverter's time slot runs from a little before the block began to where it ends, and is written once instead of being moved every quarter. A Growatt went back to Load first for minutes each time its slot was moved to start at the current quarter, so the battery stopped charging and covered the house instead. Also for GivEnergy and Alpha ESS. A window still never runs more than 3-4 hours ahead, so an order can't be left standing if Energy Pilot stops

## 0.99.2 – 2026-11-21

- Fewer writes to the inverter while the battery charges from the grid: small changes in the charge power (under 5 %) and the stop level (up to 3 %) are no longer sent, and the same values aren't written again just because the battery's level rises. Changes between charge, hold and normal still go at once, and inverters that forget their settings (Victron, Solis) still get everything written as before

## 0.99.1 – 2026-11-21

- Learns your panels: on clear days Energy Pilot sees how your production spreads over the day and bends the solar forecast hour by hour to match - which way the panels face, the tilt, and shade at certain hours are all included. Settings now show what it found (for example "facing south-west, shade 15–16"), and point it out if the solar forecast seems set up for another direction. Nothing is changed in your setup
- Tests its own settings every night: the last 14 days are replayed with slightly changed settings, and it moves one small step only when that would clearly have cost less - within fixed limits, and back to standard if that turns out best. Shown in the learning card; can be switched off under Battery → Advanced

## 0.99.0 – 2026-11-21

- Today's savings count the power in the battery at what it cost: charging overnight for the evening no longer looks like a loss in the morning (asked for by a tester)
- A car's battery level through Tibber, GWM Ora, MG (SAIC) or VW Connect is no longer taken for the house battery (found by the shared setups)
- Sensor finder: when Energy Pilot can't find a sensor by itself, it uses what other installations with the same integration use - learned every night from the shared setups, sent out without an app update. A home that works today isn't changed
- Daily control counts as a test: when the battery has done what it was told for a few minutes, that order counts as working for its profile - so profiles get confirmed without anyone pressing a button
- Test by itself at night (in the test card, off unless you turn it on): a new or mended profile is tested between 2 and 5 am while Energy Pilot isn't controlling the battery - the same test as the button, at most 1 kW
- When a test step fails because a control went offline, the report says which kind of control it was

## 0.98.0 – 2026-11-21

- Honest savings: the savings card now also shows Energy Pilot's own part - measured against the same battery left to the inverter's own control (the house first, charged by the sun only), with the same house and sun. Any battery saves something on its own; this is what the planning adds on top

## 0.97.0 – 2026-11-21

- Safer: an order to the inverter (charge from the grid, sell) now runs out by itself after about an hour and is moved on every quarter. Should Energy Pilot, Home Assistant or the network stop, the inverter goes back to normal on its own instead of charging or selling all day (Growatt, GivEnergy)
- Safer: when Energy Pilot is stopped or updated, it puts the battery back to normal first
- The sky network only counts installations that have shared for at least a week, and a power cut nearby must be seen twice in a row before the battery is kept full
- Sharing now also sends yesterday's use, sun, battery and price hour by hour (when sharing is on), so the models can be trained on all houses. The share text says so
- No AppDaemon folders as default options any more

## 0.96.0 – 2026-11-21

- Shared knowledge: a new Energy Pilot starts from what others have learned - the sun forecast's correction, the battery's real efficiency and how it slows down near full - and moves to its own numbers over two weeks
- Sky network: every quarter hour the sun against the forecast is shared for an area of about 10 km. Clouds seen by houses upwind adjust your sun for the next three hours
- Power cuts nearby: when several houses within 30 km lose the grid, the storm watch (if on) keeps the battery full for three hours
- Houses like yours: under the share switch you see what similar houses saved this month, and whether a feature like selling from the battery pays more
- The battery's health: its usable capacity compared with others of the same model
- Fixes found for a charger are shared like the inverters' (confirmed by three installations), and a fix your own test found is now used in daily control
- Grid tariff: when three neighbours with the same grid company typed in the same tariff, a new user gets it by itself
- All of it under the one share switch, with a short text saying what is shared

## 0.95.4 – 2026-11-20

- No prices at all (the market's data is late, as in NL on 20 November): the battery now runs as normal - the house first - instead of staying in its last order, and the home page says so. When the prices are back the plan takes over by itself

## 0.95.3 – 2026-11-20

- Fixed: a battery power sensor in watts could be taken for kW while the battery sat idle (a few watts). The house then looked like hundreds of kW and nothing was sold from the battery. Sensors that say W are now taken at their word, and a wrong guess is put back by itself as soon as the sensor reads hundreds

## 0.95.2 – 2026-11-20

- Home Assistant now downloads the ready-made app instead of building it on your machine: faster updates and no build leftovers on the disk

## 0.95.1 – 2026-11-20

- Ready-made app images are now built on GitHub for amd64 and aarch64 (no change to the app itself)

## 0.95.0 – 2026-11-20

- Charging power can now be a kWh counter (e.g. Monta's "Charged total") for chargers without a live power sensor - the power is worked out from how fast the counter rises
- The counter's history is used too, so the car is taken out of the house's use when learning

## 0.94.3 – 2026-11-19

- Fox ESS: the work mode is found as "Self Use" or "Self-Use", so other Fox integrations than foxess_modbus can hold and go back to normal too

## 0.94.2 – 2026-11-19

- Fox ESS Modbus: force charge and force discharge power are sent in kW, as the inverter wants - selling from the battery was refused before

## 0.94.1 – 2026-11-19

- The headline says "Planned" when the battery should cover the house but has stood still for 5 minutes while the house buys from the grid
- Victron: a persistent ESS limit "Max inverter power" at 0 is pointed out - the battery can't discharge then; Energy Pilot never changes it
- Self-test: "Back to normal" only passes when the battery really covers the house

## 0.94.0 – 2026-11-19

- "Use of the battery" in the battery settings: spare the battery (as before), in between, or most saved - how much of the battery's wear a move must pay for. An own wear number still wins
- The graphs show quarter and half-hour prices as they come - the plan, the car and the dashboard card - not just the hour's average

## 0.93.0 – 2026-11-19

- Own profile for an inverter Energy Pilot doesn't know: search its controls (likely ones first) and pick a select's option or a value with one tap - off-grid, factory reset and firmware are never offered
- A price from a select (Peak / Off Peak) is flagged: it's a name, not a price - use your own tariff plan
- evcc charging points are started and stopped by their mode (now / off)
- A battery level, battery power or solar sensor that has been unavailable for half an hour is swapped for one that works, with undo
- A skipped self-test is offered again after two weeks

## 0.92.3 – 2026-11-19

- Front page says why the sun goes into the battery instead of being sold: what it is worth later (used or sold) against the feed-in price now

## 0.92.2 – 2026-11-19

- Fox ESS Modbus: battery power from the two sensors "Battery Charge" and "Battery Discharge" - charging no longer reads as 0, so the self-test sees it
- "Why it holds" also shows the battery efficiency the plan counts with
- "What's new" after an update, and the update card lists the changes of every version it brings

## 0.92.1 – 2026-11-19

- Self-test text says it won't sell when selling is turned off

## 0.92.0 – 2026-11-18

- Says why the battery is kept for later
- Never sells from the battery below what buying it back costs
- Learned efficiency at most 95 %

## 0.91.0 – 2026-11-18

- Pause and resume for machines that carry on after a power cut
- A fuller car card (sources, planned hours, this charge)

## 0.90.3 – 2026-11-17

- Auto-fix: a stuck house or grid meter is never swapped for a one-phase meter

## 0.90.2 – 2026-11-17

- A hold only because the sun covers the house runs the battery as normal

## 0.90.1 – 2026-11-17

- Easee: also set the circuit's dynamic limit, so the charging current follows the plan

## 0.90.0 – 2026-11-17

- Help answers: your own question on top, pictures in replies

## 0.89.2 – 2026-11-17

- Ledger: the day 0.89.0 started also gets the battery's saving from before

## 0.89.1 – 2026-11-17

- Sun and battery savings: earlier days start with the battery's saving

## 0.89.0 – 2026-11-17

- Savings card: switch between battery and sun + battery, remembered

## 0.88.0 – 2026-11-16

- Sell the sun instead of storing it when that pays more

## 0.87.2 – 2026-11-16

- Charged this session from the plug-in really works (missing import)

## 0.87.1 – 2026-11-16

- Replan: first price change wakes the round at once
- Price entity must be a price (not an update entity), Octopus car level is no house battery
- README: Help tab, plan vs. actual
- Charged this session counts from the plug-in, also after a restart

## 0.87.0 – 2026-11-16

- Plan vs. actual chart, Help tab

## 0.86.8 – 2026-11-16

- New plan as soon as prices change

## 0.86.7 – 2026-11-16

- Get help: a message you send shows at once, until GitHub lists it
- Messages you send show at once

## 0.86.6 – 2026-11-16

- Plan tap: values rounded again (a local num shadowed the formatter)
- Battery tile shows kWh now and of the capacity
- Battery kWh on the front page, plan values rounded

## 0.86.5 – 2026-11-16

- Statistics: a battery without a profile sends its integration's name (e.g. sunsynk)
- Worker shows unknown battery integrations
- Statistics name the integration of unrecognised batteries

## 0.86.4 – 2026-11-16

- Easee/Huawei/GivEnergy: device_id stays in the action's data (text, not a list)
- Sell stop steps aside while the battery sells or is tested
- Easee device_id fix, sell stop pauses while the battery sells

## 0.86.3 – 2026-11-16

- Victron/Solis/SolarEdge: every value written each round, so an unchanged one (max charge power) never goes stale
- Victron ESS values never go stale while charging

## 0.86.2 – 2026-11-16

- Car: a charger switch without a plug sensor (smart plug) counts as plugged in
- Smart plug chargers work without a plug sensor

## 0.86.1 – 2026-11-16

- Plan: battery also in kWh when tapping an hour
- Battery in kWh in the plan

## 0.86.0 – 2026-11-16

- Colour themes - Standard, Neon, Nordic, Forest and High contrast, each in dark and light (Settings, kept on the device)

## 0.85.3 – 2026-11-15

- Car card shows the plan's real times (quarters), a real car icon, the ring fills like water to the car's level or this charge, a clean ready marker instead of the flag

## 0.85.2 – 2026-11-15

- Charge now tells the charger at once instead of at the next round

## 0.85.1 – 2026-11-15

- A new look for the car card (ring, ready time, the night's charging hours, sun or grid flow, Charge now button), the car above the battery card

## 0.85.0 – 2026-11-15

- A new look for the battery card - ring with the level and the minimum, a clean timeline with the dear hours and sunrise/sunset, one gauge for the dear hours, a calmer week

## 0.84.1 – 2026-11-15

- Phase switching also by a 'force 1 phase' switch (Peblar) and local names, Growatt cloud profile, FoxESS holds in Self Use, zone names no longer hide integration words in setup info

## 0.84.0 – 2026-11-15

- Switch between 1 and 3 phases on the sun's surplus (chargers with their own phase choice), Sun only never buys from the grid

## 0.83.2 – 2026-11-15

- Car ready time read in any format (no more plan stop), self-test says when a device went offline and puts its settings back once it returns, inverter battery limits in diagnostics

## 0.83.1 – 2026-11-15

- The inverter's own lowest battery level: named when the battery won't follow, and a settings check that offers to use it
- Spots when the inverter's own lowest battery level stops the plan, and offers to use it

## 0.83.0 – 2026-11-15

- Choose how small grid flows to hide (30-200 W) and short sync draws no longer show as buying
- Store and update links open right inside Home Assistant

## 0.81.0 – 2026-11-15

- Revert "0.82.0: natural energy scenes and animated flow in app and dashboard cards"

## 0.82.0 – 2026-11-15

- Battery card: next step follows quarter slots
- Sun share shown once measured
- Natural energy scenes and animated flow in app and dashboard cards

## 0.81.0 – 2026-11-15

- New battery card - next step, ready for the dear hours, sky graph with sun forecast and events, tap for details, sun share, essentials-only runtime, records and the week
- Savings above it, settings check only in settings

## 0.80.2 – 2026-11-15

- AlphaESS guide when a period is missing in its app (test and settings check), Alpha ESS tested
- A solar forecast alone no longer counts as a battery in setup info

## 0.80.1 – 2026-11-15

- A battery that can only be read (Powerwall local, SolarEdge cloud, FusionSolar) - one quiet line with the integration that can control it

## 0.80.0 – 2026-11-15

- GoodWe: the grid's sign known (plus when selling) when it can't be found from the house's balance
- GoodWe EMS profile (EMS mode with a power limit, the experimental GoodWe integration)

## 0.79.0 – 2026-11-15

- GoodWe as a built-in profile (operation mode with eco power and level)

## 0.78.2 – 2026-11-15

- Setup names - people found also with æ/ø/å (like Home Assistant's own ids), rooms stay
- Worker: installs and devices counted apart

## 0.78.1 – 2026-11-15

- Storm watch: official warnings from Meteoalarm, DWD, Météo-France, Environment Canada, GDACS, NWS, BOM, MetService, MET, Met Office and NHC
- AlphaESS - a charge period never runs over midnight (split before and after it)

## 0.78.0 – 2026-11-15

- How long the battery lasts (home, dashboard card, sensor) and storm watch (off by default)

## 0.77.2 – 2026-11-14

- Setup - the maker and model also from the other entities, the charger's device or the integration

## 0.77.1 – 2026-11-14

- Report worker: choices shown as choices (not turned on), versions separated
- Setup names nearly whole (only people, rooms, zones, home and device names swapped)
- Charger profile, price integration, no empty test

## 0.77.0 – 2026-11-14

- Report worker: newest version from the tags too (not only Releases), asked again every hour
- How it is set up for the developer (names cleaned, or full with Share my setup)
- Worker: setups section, newest version on the page

## 0.76.1 – 2026-11-14

- Stop selling: chosen from the brand when turned on, a test with the guide, diagnostics when it fails
- AlphaESS - longer test for the cloud, the integration's error shown with what to do, an error from a service no longer counts as done

## 0.76.0 – 2026-11-14

- Stop selling solar at negative prices

## 0.75.0 – 2026-11-14

- Worker: count installations per app and country (from the connection), and a private /stats page
- Worker /stats: everything on one page - Energy Pilot inverters and self-tests, Madplan, app errors, help messages
- Update card (new version, your error fixed) and the version in the daily question

## 0.74.0 – 2026-11-14

- Receiver: Appliance Watch
- Suggestions of the other apps (fits your home, from the same developer)

## 0.73.3 – 2026-11-14

- A machine Appliance Watch knows - Runs cheaply uses its real programme (minutes and kWh)

## 0.73.2 – 2026-11-14

- Receiver: House Chat
- Alpha ESS for the newer integration - hold is a discharge window away from now, charge carries its power, normal never deletes a period, windows never overlap

## 0.73.1 – 2026-11-14

- Receiver: Replace Device, Update Guard, Database Doctor and Heat Pilot
- Errors from Home Assistant restarting or the network (502, timeout, no connection) are not reported

## 0.73.0 – 2026-11-14

- Close on answers, answers go away by themselves, asked every 10 minutes the first week

## 0.72.1 – 2026-11-14

- Tests: skip the sklearn check where it isn't installed (CI)
- A new answer always gives a notification, also when the page is open
- README

## 0.72.0 – 2026-11-14

- A comment on an app-error issue reaches the installations that had the error

## 0.71.1 – 2026-11-14

- Learning models off quietly on a CPU that can't run them, with a note

## 0.71.0 – 2026-11-14

- Receiver: several apps (Energy Pilot ⚡ and Madplan 🍽️) each with its own badge
- Madplan: offers per chain (alarm at 0 from several homes), items the search did not find, errors, weekly overview
- Answers to Get help in the app, Alpha ESS times in whole quarters

## 0.70.0 – 2026-11-14

- Learn together: anonymous daily line, test results, fixes and app errors to the recipient (D1)
- Confirmed fixes (3 homes) are used by everyone with the same profile, with Undo
- 'testet af N'
- Ugentlig oversigt (cron)
- Kontakt under Indstillinger
- README
- Learn together + the card finds the savings figure right after a restart too

## 0.69.0 – 2026-11-14

- Dashboard card shows what the battery has saved - new Saved view (today large, yesterday/month/year/total) and a line on All
- The amount counts up smoothly

## 0.68.2 – 2026-11-13

- Runs cheaply follows shadow (turns nothing on/off, starts no machine - notification only) until Energy Pilot controls something
- A charger switched on by hand is not turned off until the battery is full

## 0.68.1 – 2026-11-13

- Get help: the button is called Get help in 7 languages, explanation under the button, up to 3 images (made smaller in the browser) shown in the issue
- Worker gemmer billederne i det private repo
- Get help with message and images

## 0.68.0 – 2026-11-13

- Send to the developer: Cloudflare Worker (report-worker/) that stores reports in a private repo
- /api/report sender test + diagnose (uden all_controls)
- Button explaining what is sent, optional note and number
- Falls back to GitHub link + download until the URL is set
- Send to the developer - one button sends test and diagnostics to ep-reports (private repo), shows what is sent, optional note and a number

## 0.67.1 – 2026-11-13

- The test's result, saved values and fixes were not saved (the settings file did not know the keys) - now saved
- The test does not start without saved values and remembers them in memory too

## 0.67.0 – 2026-11-13

- Guide with the test (explanation, Start/Skip), status light, test card on the front page, automatic fixes with Undo (fuse in amps, 0-1 battery percent, kW without unit, price in øre, renamed and frozen sensors), a battery doing the opposite goes to normal for an hour, a charger that does not start is restarted once

## 0.66.0 – 2026-11-13

- Test your system - tries hold/charge/sell/normal and charger at at most 1 kW, measures whether it happens (30 s in a row, min. 1 min), tries other safe options itself and remembers what works (can be undone), puts everything back (also after a restart), GitHub button with filled-in result
- Button at the top under Control and under Settings

## 0.65.13 – 2026-11-13

- Solis (every 10 min) and SolarEdge (every 30 min) rewrite the remote control even if HA shows the value - their timers only restart on a write

## 0.65.12 – 2026-11-13

- Ids (device_id, serial, *_id) are always sent as text - Easee rejected device_id "45" as a number

## 0.65.11 – 2026-11-13

- Huawei working mode picks the integration's own option (maximise_self_consumption)
- All select values are matched to the control's own options regardless of case/spaces/underscores

## 0.65.10 – 2026-11-13

- A Victron control showing Unknown is written immediately (the integration shows Unknown 5 min after the last write) - only unavailable is waited on

## 0.65.9 – 2026-11-13

- Victron keep-alive every minute check - resent on time (4 min) and immediately when the controls are back after unavailable
- Resends are counted in the log

## 0.65.8 – 2026-11-13

- Flow: no line to the car for a charger's standby power (below 100 W)

## 0.65.7 – 2026-11-13

- Plan: equal prices charge in the first slots, not the last

## 0.65.6 – 2026-11-13

- Flow: grid shows selling/buying from 30 W (was 100 W)

## 0.65.5 – 2026-11-13

- Deye: limit the grid charge current to the planned power, put the owner's back after

## 0.65.4 – 2026-11-13

- Small fixes

## 0.65.3 – 2026-11-13

- Settings page: put back the charger switch list removed by mistake in 0.65.2

## 0.65.2 – 2026-11-13

- Runs cheaply: pick lists show only plugs, start buttons and the plug's own power sensor - 'Show all' for the rest

## 0.65.1 – 2026-11-13

- Runs cheaply: only real machines and plugs are offered (no room sensors, no robot mowers' settings), looked up at start

## 0.65.0 – 2026-11-13

- Runs cheaply: small batteries and machines on the sun or in cheap hours, after the house battery and the car

## 0.64.0 – 2026-11-13

- House sensor without statistics: say so, and offer to keep the house's history in Energy Pilot itself

## 0.63.5 – 2026-11-13

- Remove the house heat model (husmodel) from Energy Pilot - it is about heating, not power

## 0.63.4 – 2026-11-12

- The dashboard card takes the height it needs on a sections dashboard - the overview no longer runs into the card below

## 0.63.3 – 2026-11-12

- The plan in the card and the app opens at the time now - it waits until the card has a width

## 0.63.2 – 2026-11-12

- Fix the front page (a wrong name for the language stopped it)

## 0.63.1 – 2026-11-12

- The Shadow tab is called Control
- The front page shows the cheapest hours with a link to the plan instead of the plan graph a second time

## 0.63.0 – 2026-11-12

- A charger in shadow shows the charge Energy Pilot would make (dashed in the plan) beside what really happened, with the average price of each
- How much a car takes is learned per charger

## 0.62.2 – 2026-11-12

- The plan graph shows car charging only for chargers Energy Pilot runs - a charger in shadow is charged by something else

## 0.62.1 – 2026-11-12

- The sell switch is 'Use the export price' - it tells the plan, it doesn't steer the inverter

## 0.62.0 – 2026-11-12

- Header counts Energy Pilot's own control
- Selling and charging switches grouped
- Clearer switches
- 'Sell from solar'
- Minimum slider ignores scrolling
- Settings change log

## 0.61.3 – 2026-11-12

- Grid and battery under 100 W shown as idle (inverter trimming is not selling)

## 0.61.2 – 2026-11-12

- Easter computed in-house (no dateutil)
- CI installs holidays

## 0.61.1 – 2026-11-12

- The dashboard card's energy picture shows the weather, the season and the holiday like the app

## 0.61.0 – 2026-11-12

- The flow card shows the real weather, the time of day, the season and the day's holiday - by country

## 0.60.3 – 2026-11-12

- Growatt lets go of the all-day grid-first slot after selling
- Charge taper never lower than a level above

## 0.60.2 – 2026-11-12

- A selling grid setpoint (Victron) is never kept as the owner's - back to 0 when selling stops and when leaving control

## 0.60.1 – 2026-11-12

- Hours without battery history are left out of the house use

## 0.60.0 – 2026-11-12

- Option to not sell from the battery in the cheap hours
- Clearer no-gain message

## 0.59.4 – 2026-11-12

- Never suggest a phone's battery as a home battery

## 0.59.3 – 2026-11-12

- The plan shows the car's charging like the sun - kWh per hour as a pink area

## 0.59.2 – 2026-11-12

- Chargers with fixed steps (8/10/13 A) stop when even the lowest step would go over the import limit

## 0.59.1 – 2026-11-11

- 'Max from the grid' at 0 or at/below the minimum is ignored - it would stop all grid charging (red Tempo days too)

## 0.59.0 – 2026-11-11

- Battery targets: at least X % at a set time every day, even when it doesn't pay

## 0.58.3 – 2026-11-11

- The decision sensor knows 'selling from the battery' - before, it stayed on the previous state

## 0.58.2 – 2026-11-11

- Quiet hours for the battery only stop charging from the grid - solar surplus still charges (issue #13)

## 0.58.1 – 2026-11-10

- Hold never asks for less than the battery minimum (at 9 % Growatt keeps 10 % - it was shown as not confirmed)

## 0.58.0 – 2026-11-10

- Own tariff plan: feed-in price by time (e.g. 15c from 6-9pm) and a daily cap on paid feed-in - folded away under the tariff plan, only for those who need it

## 0.57.1 – 2026-11-10

- House history: every charger is taken out, not only charger 1

## 0.57.0 – 2026-11-10

- No home power sensor: the house's use is worked out from the history of grid, sun, battery and car - it learns the daily shape straight away, and 'house today' and the nightly review work too

## 0.56.1 – 2026-11-10

- Plan chart: hours a forecast leaves out (the night with Forecast.Solar) count as no sun - the line no longer runs straight through the night

## 0.56.0 – 2026-11-10

- Sun forecast from more sources: Solcast, Open-Meteo Solar Forecast (wh_period), Home Assistant's Energy dashboard forecast (Forecast.Solar and the rest) - and its own learned forecast when none gives the hours
- The plan no longer goes without sun

## 0.55.0 – 2026-11-10

- Control: a setting that changes back by itself is set again at once
- Told when something else (Predbat, an automation) steers the battery too
- The battery's power follows the time left of the slot and the house's real use, so it ends where the plan says

## 0.54.0 – 2026-11-10

- Battery control and Car control as selects in Home Assistant (Shadow / Control / Off) - an automation can switch Energy Pilot on and off

## 0.53.2 – 2026-11-10

- Victron: the ESS settings are sent again every 4 minutes - Victron puts them back to its defaults after about 10 minutes

## 0.53.1 – 2026-11-10

- Megarevo through SolarAssistant: Work mode for normal (Self consume) and hold (Battery priority), matched loosely by name
- No grid charging, so the plan never buys for the battery

## 0.53.0 – 2026-11-10

- Car: two limits - from the grid up to (e.g. 80 %) and with the sun up to (e.g. 100 %)
- The sun's surplus fills the rest for free

## 0.52.7 – 2026-11-10

- Car: a session number older than the plug-in belongs to the last visit (KEBA keeps it until charging starts) - counted as 0, so the car gets its full charge

## 0.52.6 – 2026-11-10

- Car battery: every percentage sensor of a car is offered to choose (two cars, names it doesn't know) - only ones named like a battery level are ever picked by themselves

## 0.52.5 – 2026-11-10

- Deye: the global grid-charge switch follows 'may charge from the grid' (set, not toggled) - the programmes decide
- Switches already in the wanted state aren't written again

## 0.52.4 – 2026-11-10

- Charger behind a sum sensor (Zappi + 'All EV power' group): found from the plug's device, never group switches
- A minimum-SoC setting is not an extra battery

## 0.52.3 – 2026-11-10

- Battery cost: Energy Pilot's own number when it runs the battery (the paused system's stands still)

## 0.52.2 – 2026-11-10

- Battery cost: Energy Pilot's own number when it runs the battery (the paused system's stands still)

## 0.52.1 – 2026-11-10

- Charger control: never offer child locks (Danish 'børne' looked like French 'borne')

## 0.52.0 – 2026-11-10

- Charger control: pick the switch that starts a charger (Shelly, Tuya Local, smart plug)
- On/off-only chargers run at full power

## 0.51.0 – 2026-11-10

- The car's battery level: charge to a target, 100 % for the next trip, car battery size learned

## 0.50.2 – 2026-11-10

- Fix: a second _clamp broke control in 0.50.1

## 0.50.1 – 2026-11-10

- Huawei, GivEnergy, Sungrow, Victron: give full charge/discharge power back
- Numbers kept inside the entity's range
- The follow check also names limits at their minimum and blocking modes

## 0.50.0 – 2026-11-10

- Limits a charge or sale set are given back (Sigenergy, Victron, EcoFlow, GivEnergy, Growatt TL-XH, Deye solar sell)
- Warn when the battery doesn't follow the plan

## 0.49.3 – 2026-11-10

- Plan the quarter now whole (the battery held late in every quarter) and run at each quarter's start

## 0.49.2 – 2026-11-10

- Growatt: set the free-mode discharge/charge rates and let slot 1 go, so the battery always covers the house

## 0.49.1 – 2026-11-10

- Dashboard card: show the battery plan like the app (battery level, selling, car, legend)

## 0.49.0 – 2026-11-09

- Grid charging stops at 95 % (NMC 90 %) - the sun may fill it, and every 14 days without a full battery it charges to 100 % once to balance

## 0.48.0 – 2026-11-09

- Learns how the battery really charges near full
- The house battery doesn't empty itself into the car

## 0.47.0 – 2026-11-09

- Power tariffs - month's peak kept, battery shaves peaks, car charges beside them

## 0.46.0 – 2026-11-09

- Calmer design - found sensors folded to one line, ready-to-control checklist, compact extra car cards, bigger plan chart, AppDaemon block only when there is one

## 0.45.0 – 2026-11-09

- New sensors - next battery charge, next car charge, next sale, cheapest hour, house use today, solar forecast

## 0.44.0 – 2026-11-09

- Clear engine text, newer texts in German/French/Dutch/Swedish/Norwegian, usual main fuse suggested

## 0.43.1 – 2026-11-09

- Victron ESS controls found on another device than the battery level (Victron MQTT + GX)

## 0.43.0 – 2026-11-09

- Wear counted on all battery use
- Battery type found by itself (LFP/NMC/sodium/lead) and sets wear, minimum and efficiency

## 0.42.0 – 2026-11-09

- Grid power direction - found from the house's balance, or set by hand (Grid → Advanced)

## 0.41.1 – 2026-11-09

- Plug status lists (VEVOR plugged_in, OCPP …), charging current as a select, charger controls only from its own device

## 0.41.0 – 2026-11-09

- More batteries can be controlled - each through its own inverter, starts in shadow, power shared by what each can take

## 0.40.0 – 2026-11-09

- Extra chargers can be controlled - each starts in shadow
- Charger 1 first, the others turned down first

## 0.39.3 – 2026-11-09

- Selling from the battery reached the plan again
- Extra sensors aligned under the first
- 12 V car batteries not suggested

## 0.39.2 – 2026-11-09

- Any kWh sensor can be picked as a solar forecast

## 0.39.1 – 2026-11-09

- Spot prices outside Denmark include tomorrow

## 0.39.0 – 2026-11-08

- Flere ladebokse (hver bil for sig, under hovedsikringen, kun skygge)

## 0.38.0 – 2026-11-08

- More home batteries (planned as one, found automatically, shadow only)

## 0.37.0 – 2026-11-08

- New images: front page with own decision, settings with selling from the battery
- Settings check with fix button, Advanced, diagnostics file

## 0.36.11 – 2026-11-08

- Selling from the battery also for Deye via ESPHome (Selling first) and EcoFlow PowerStream (custom load above house consumption)

## 0.36.10 – 2026-11-08

- Selling from the battery for Victron (grid setpoint), Growatt (Grid first) and Deye/Solarman (Export First)
- The owner's own settings are remembered before selling and restored afterwards

## 0.36.9 – 2026-11-08

- The battery cost price tolerates a wrong battery percentage for a moment (resets/trims only after 5 min)

## 0.36.8 – 2026-11-08

- Octopus Agile uses Agile Predict as price forecast (region from the tariff), own forecast as fallback

## 0.36.7 – 2026-11-08

- Selling from the battery also for Huawei, Solis, Sigenergy, SolarEdge and GivEnergy (looked up in the integrations' source code)
- Missing sell controls do not block control

## 0.36.6 – 2026-11-08

- Selling hours are shown in the plan graph (own color, legend and in the hour's details)

## 0.36.0 – 2026-11-08

- Sell from the battery (optional) - the plan sells when the sell price gives a profit after losses and wear (wear calculated per currency), export limit
- Selling in the Sofar (Solarman/SolaX), SolaX, Fox ESS and Sungrow profiles

## 0.35.2 – 2026-11-08

- Only writes values that are not already set, and resends a value once if it was not accepted (Solarman drops writes)

## 0.35.1 – 2026-11-08

- The quarter-hour plan can use the battery, even when the house uses less than one step per quarter-hour (fine step 1%, smallest step covers the house)

## 0.35.0 – 2026-11-08

- Power back into the battery is worth the refill price (not the average) - uses the battery in the morning and does not buy late
- The front page shows its own decision with AppDaemon's next to it

## 0.34.1 – 2026-11-08

- Writes energy_pilot_uses.json with the sensors it uses, so database tools do not stop their history

## 0.34.0 – 2026-11-08

- Off-grid mode - the generator is controlled from the battery, solar and consumption forecast: starts before the reserve is reached, minimum run time, fills to a target, quiet hours, emergency limit always
- Card on the front page, part of Shadow

## 0.33.0 – 2026-11-08

- Prices and chargers checked against the integrations' source code - Nord Pool/Tibber (HA's own), EnergyZero and easyEnergy fetched via their action
- ENTSO-E, Frank Energie and Zonneplan are read
- Charging profiles for Easee, Zaptec, go-e, Wallbox, Peblar, OCPP, Alfen, Ohme and zappi

## 0.32.0 – 2026-11-08

- More profiles checked against the source code - GivEnergy fixed (timed charge service, pause mode), new Solis (RC force charge, resent every 10 min) and Alpha ESS (cloud services)
- Tesla and Enphase confirmed against HA's own code

## 0.31.0 – 2026-11-08

- Profiler tjekket mod integrationernes kildekode - Huawei rettet (navne, 'Maximise self consumption', device_id, stop forcible charge), SolarEdge (AC charge policy, timeout, hold tager sol), Fox ESS (force charge power/max SoC)
- Nye: Sigenergy, Sofar via SolaX Modbus, Tesla Powerwall, Enphase IQ Battery
- Test with real entity names

## 0.30.0 – 2026-11-08

- German, French, Dutch, Swedish and Norwegian in panel, card, the engine's decisions and the companion integration (English underneath so nothing is missing)
- Language follows Home Assistant

## 0.29.0 – 2026-11-08

- EDF Tempo - prices from today's/tomorrow's color and the six Tempo prices (Tempo day 06-06, night 22-06)
- Unknown color is not guessed

## 0.28.2 – 2026-11-08

- 'Found' line on one line, model name without repetition

## 0.28.1 – 2026-11-08

- Inverter list sorted by brand with ✅/🧪, and 'Found: ... - all controls found' above it

## 0.28.0 – 2026-11-08

- Sofar profile (Solarman, Self Use / Passive with min/max battery power)
- The integration's name only counts when its controls exist (Solarman is used by both Deye and Sofar)

## 0.27.0 – 2026-11-08

- Deye via ESPHome/lokal Modbus (klatremis, seks Time point-programmer)
- Cars' batteries are not mistaken for the home battery
- 'Self-chosen' can pick any control in HA

## 0.26.0 – 2026-11-08

- EcoFlow PowerStream profile (custom load following house consumption, hold = 0 W, no grid charging - the plan does not buy for the battery)
- Tal holdes inden for kontrollens min/max

## 0.25.0 – 2026-11-08

- New images: Shadow (Now it would, Copy/Your system), Settings (follow the sun, main fuse, discharge power and more), self-check with first report
- Learns the battery's usable capacity (and efficiency) from charges and discharges - kWh per percentage point both ways, independently of each other
- Used when the field is empty, suggestion when the set number differs

## 0.24.4 – 2026-11-08

- Another system's battery cost price is only used when it is credible (at most 3 x the highest price) - otherwise Energy Pilot's own

## 0.24.3 – 2026-11-08

- 'House today' counted yesterday's consumption just after midnight

## 0.24.2 – 2026-11-07

- Tomorrow's price mixed in Strømligning's spot price (without tariff) - now only the 'tomorrow' entity that matches today's (same type: VAT, spot, export)
- Amber-forecast-sensoren findes

## 0.24.1 – 2026-11-07

- Shadow shows what the engine would do, even when another system is in control
- The columns are called Copy and Your system

## 0.24.0 – 2026-11-07

- The car follows the sun live (current follows surplus, also charges outside the plan on clear surplus, margin against on/off) and protects the main fuse
- Both can be turned off
- Bilen tjekkes hvert minut

## 0.23.0 – 2026-11-07

- Octopus Energy - rates/next_day_rates and event entities are read for buying and selling (import and export kept separate), price now from the rates

## 0.22.0 – 2026-11-07

- Victron ESS profile (force charge + max charge/discharge power, grid setpoint is not touched)
- Egen afladeeffekt i indstillingerne

## 0.21.3 – 2026-11-07

- Settings failed (KeyError 'guess') when a found sensor did not match the list's filter

## 0.21.2 – 2026-11-07

- The search field is a small link 'Find another sensor' so the settings do not get cluttered

## 0.21.1 – 2026-11-07

- Settings no longer stick out beyond the cards on phones (rows wrap, search field and add on their own line)

## 0.21.0 – 2026-11-07

- The battery's sign is detected automatically (Fox ESS and others count discharge as positive) + option
- Varying sell price from a sensor (e.g. Amber) with forecast, used hour by hour/quarter-hour by quarter-hour

## 0.20.0 – 2026-11-07

- The lists show all sensors with the right unit (also Victron and templates without device_class), best guess at the top, search field
- Multiple solar systems and solar forecasts are added together

## 0.19.1 – 2026-11-07

- Deye profile (Solarman integration) - all six Time of Use programs are set the same, no times are touched

## 0.19.0 – 2026-11-07

- New images: panel 0.18.4 (House today, car in house consumption) and the cards in a new design
- Image for Facebook in the facebook folder
- Plans in the market's price periods - quarter-hour in Europe (since Oct 2025), half hour in the UK, hour otherwise
- Battery and car use the cheapest quarter-hours

## 0.18.4 – 2026-11-07

- The self-check also subtracts the car from house consumption when it is included

## 0.18.3 – 2026-11-07

- Detects whether the car is included in house consumption and subtracts it (live, today and in the history the forecast learns from)
- Choices under Car and charger

## 0.18.2 – 2026-11-07

- Image for the beta tester post
- Opslagsbillede: viser ML
- 'House today' is the engine's own (used so far + forecast for the rest of the day), another forecast is shown next to it

## 0.18.1 – 2026-11-07

- The Shadow tab does not flicker - the page is only redrawn when something has changed, and without fade-in

## 0.18.0 – 2026-11-07

- Blend - simple forecast from day one, ML takes over gradually as it hits better (consumption, sun, tomorrow's prices before 13:00)
- The car's habits and the battery's efficiency are learned
- Vind i vejret, 60 dages historik
- The panel shows who decides

## 0.17.0 – 2026-11-07

- Battery cost price (weighted average like AppDaemon, solar power free or at sell price, uses your AppDaemon's numbers when it exists) and measured savings today/month/year/total - card in the panel and sensors in the companion

## 0.16.0 – 2026-11-07

- Inverter models (Growatt SPH/SPA and MIN/MOD TL-XH chosen by model), requirement check: if a control is missing the engine does not control (never half a command), test view of found/missing controls

## 0.15.2 – 2026-11-07

- House consumption in tomorrow's plan: the engine's forecast fills the hours another forecast does not cover

## 0.15.1 – 2026-11-07

- Tomorrow's prices from all price integrations (also 'tomorrow' entities, Nord Pool, Tibber, EDS formats), missing hours are filled from own spot prices at the user's price level, notification when they are missing

## 0.15.0 – 2026-11-07

- Energy flow shows the real power paths (solar→battery, grid→battery, battery→car ...) in panel and card, thickness by power, color by source
- Glow around active nodes, the sun rotates, dot grid

## 0.14.0 – 2026-11-07

- Docker (compose + image via GitHub Actions), README in Danish/English with images, apps only if they exist

## 0.13.0 – 2026-11-07

- Companion integration (Charge now, Ready at, Max, Battery minimum, Style, All in shadow, decision, price, savings) - the app installs it and announces itself via Supervisor discovery

## 0.12.0 – 2026-11-07

- Adapters - the engine can control inverters (Growatt, Huawei, SolaX, Sungrow, SolarEdge, Fox ESS, GivEnergy + custom profile for all brands) and chargers (KEBA, Easee, Zaptec, go-e, Wallbox, OCPP and more via switch + current)
- Shadow/control per part, read-back, stays out when another system controls the battery

## 0.11.2 – 2026-11-07

- Quiet hours separately: the home battery and the car each have their own time range

## 0.11.1 – 2026-11-07

- Settings split into cards with icons: Home battery, Car and charger, Electricity price, Grid, Quiet hours

## 0.11.0 – 2026-11-07

- Self-learning - notes what it expected each hour, reviews yesterday each night: solar correction (cloudy/clear), consumption margin in expensive hours, end value found by re-planning yesterday with real numbers
- Self-check card with report

## 0.10.0 – 2026-11-07

- Own tariff plan (periods with price, weekday/weekend, months) with templates (day/night, peak, PG&E, SCE, Economy 7) - works in countries without spot prices like the USA

## 0.9.0 – 2026-11-07

- Virker i hele Europa - priszoner pr. land (energy-charts.info udenfor DK), valuta efter ECB-kurs, moms pr. land, helligdage pr. land (holidays), valuta i panelet

## 0.8.0 – 2026-11-07

- The engine manages by itself - Danish holidays, weather and solar radiation (Open-Meteo), own electricity prices (Energi Data Service + tariff, tax, VAT
- Price area and grid tariff can be corrected), own solar forecast learned from the system's production, ML house consumption with temperature and days off

## 0.7.0 – 2026-11-07

- Choices - style (cheapest, most sun, peace of mind, car/battery first) and fine tuning (minimum, charge from grid, sell, size/power, import cap, car cheapest/solar only, charger power, quiet hours)

## 0.6.0 – 2026-11-07

- Own engine - house consumption forecast (learned from 28 days of statistics), battery plan (DP over the price hours, sun, losses, no selling from battery), car plan (sun first, then cheapest before ready time)
- Shown in the plan graph and compared with AppDaemon

## 0.5.0 – 2026-11-07

- Finds what you have by itself (Energy dashboard, known integrations, names), shows where it was found, house consumption is calculated if missing, guide at first start

## 0.4.0 – 2026-11-07

- Cards for the dashboard (energy flow, battery, car, plan or everything) - the card file goes in /local and is added as a resource, data from sensor.energipilot

## 0.3.0 – 2026-11-07

- Professional design - line icons, light rays in the energy flow, key figures, sleek car, sharp plan graph, tab bar with icons, dark/light theme

## 0.2.0 – 2026-11-07

- New panel - live energy flow, decision in plain language, price/sun/battery/house, car buttons, today's plan, shadow tab with agreement, settings for what you have

## 0.1.1 – 2026-11-07

- Repo-adresse: Clahen86/Energy-pilot
- App: Python image directly in Dockerfile (build.yaml is deprecated)

## 0.1.0 – 2026-11-07

- Energy Pilot: runs AppDaemon apps unchanged in shadow (does nothing, shows what it would do, compares with your system) or takes control
- First panel
- App-pakning
- Read calls (get_*) also run in shadow
- Replies are packed as in AppDaemon
- Repo as app repository (repository.yaml, energy_pilot/ with config, Dockerfile, DOCS)
