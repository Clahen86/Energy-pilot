# Energipilot · Energy Pilot

**Your home battery, solar panels and electric car - planned hour by hour for the lowest price, in one beautiful app
for Home Assistant.** It always starts in *shadow*: it shows what it would do, but controls nothing until you say so.

![Energy Pilot](docs/screens_en.png)

## What it does

- **Live energy flow** – every real path (sun → battery, grid → battery, battery → car …), with light beams that follow
  the power. Colour shows the source, thickness the power.
- **A plan for today and tomorrow** – it charges the battery when power is cheap or the sun gives too much, and uses it
  when power is expensive. The car charges on sun first, then in the cheapest hours before it must be ready.
- **What the battery saved – measured** – today, this month, this year and in all, from what you really bought and sold
  against the same house and sun without the battery. It also knows what the power in the battery cost (a weighted
  average: grid power at the price paid, solar power free or at the sell price - your choice).
- **Gets better by itself** – a simple forecast works from day one, and an ML model trained every night on your own
  data takes over as it proves better: for house use, for the sun (sunlight, cloud, temperature, time of year) and for
  tomorrow's prices before they're out (wind, sun, weekday, recent prices). If the ML model starts to miss (a new heat
  pump, a new car), the simple one takes over again. The panel shows who decides and how well each one hits.
- **Learns your home** – every night it checks yesterday with the real numbers and adjusts the solar correction and the
  margins. It learns the battery's real efficiency and the car's habits (when it leaves, how much it takes) - what you
  set yourself always wins.
- **Your choice of style** – *Cheapest*, *Most sun*, *Safety* (keeps 30 % for power cuts), *Car first* or *Battery first*,
  plus fine-tuning: battery minimum, grid charging, selling, main fuse, quiet hours for battery and car.
- **Finds what you have** – from the Energy dashboard, known integrations and names. Shows only what you have.
- **Needs almost nothing** – weather (Open-Meteo), spot prices (Energi Data Service / energy-charts.info for 26 European
  countries), its own solar forecast and holidays are built in. Your own Strømligning, Nord Pool, Tibber, Energi Data
  Service or Solcast is used when you have it - today's and tomorrow's prices, whatever shape they come in. Hours
  your integration doesn't have yet are filled in, so the plan always reaches as far as anything is known. No spot
  price where you live (USA, UK…)? Enter your tariff plan or start from a template.
- **Controls many brands** – inverters: Growatt (SPH/SPA and MIN/MOD TL-XH, picked by model), Huawei, SolaX, Sungrow,
  SolarEdge, Fox ESS, GivEnergy, or any other by picking the controls yourself. Chargers: KEBA, Easee, Zaptec, go-e,
  Wallbox, OCPP and more.
- **Never half a command** – if a control the inverter profile needs is missing, it won't control at all and tells you
  what's missing. A test in *Shadow* shows every control it found before you let it take over.
- **Shadow first, always** – each part (battery, car) can be *Shadow*, *In control* or *Off*. One tap puts everything
  back in shadow. It never fights another system that controls the same battery.
- **Dashboard cards** – energy flow, plan, car, battery or everything, under *Add card → Energipilot*.
- **Buttons in Home Assistant** – *Charge now*, *Ready at*, *At most*, *Battery minimum*, *Style*, and sensors for the
  decision, price, battery target, *Saved today / this month / this year / in all* and *Battery power cost* - for your
  own automations.
- **Already have an energy system in AppDaemon?** Energy Pilot can run it unchanged, in shadow, and compare.

![Cards](docs/cards.png)

## Install

**Home Assistant OS / Supervised (recommended):**
1. *Settings → Apps → App store → ⋮ → Repositories* → add `https://github.com/Clahen86/Energy-pilot`
2. Install **Energipilot** and start it. It appears in the sidebar.
3. The guide shows what it found - fix what's wrong and press *Get started*.
4. Restart Home Assistant once: *Energipilot found* appears under *Devices & services* (buttons and sensors).

**Docker (Home Assistant Container/Core):** see [`docker/docker-compose.yml`](docker/docker-compose.yml) - give it your
Home Assistant address and a long-lived access token, open `http://<host>:8099`. Mount your Home Assistant config at
`/homeassistant` to get the cards and the companion integration installed automatically.

## Privacy

Everything runs in your home, the ML models too. It only fetches public data: weather (Open-Meteo), spot prices
(Energi Data Service, energy-charts.info) and exchange rates (ECB via frankfurter.dev).

## Good to know

- The inverter profiles for brands other than Growatt SPH are built from their known controls but not yet tried on real
  systems - run them in shadow first, check the control test, and report back.

---

## Dansk

**Husbatteri, solceller og elbil – planlagt time for time til den laveste pris, i én flot app til Home Assistant.**
Den starter altid i *skygge*: den viser, hvad den ville gøre, men styrer intet, før du siger til.

![Energipilot](docs/screens_da.png)

- **Levende energiflow** med de rigtige strømveje (sol → batteri, net → batteri, batteri → bil …) og **dagens og
  morgendagens plan**.
- **Batteriet har sparet – målt**: i dag, måned, år og i alt, ud fra det du faktisk har købt og solgt. Den kender også
  batteriets kostpris (solstrøm gratis eller til salgsprisen – du vælger).
- **Bliver selv bedre**: en simpel prognose virker fra dag ét, og en ML-model, der trænes hver nat på dine egne data,
  overtager efterhånden som den rammer bedre – for forbrug, sol og morgendagens priser før kl. 13. Rammer den ved
  siden af, tager den simple over igen. Panelet viser, hvem der bestemmer.
- **Lærer dit hjem**: gennemgår hver nat gårsdagen, lærer batteriets rigtige virkningsgrad og bilens vaner – det du
  selv indstiller, vinder altid.
- **Priser fra alle pris-integrationer** (Strømligning, Nord Pool, Tibber, Energi Data Service), i dag og i morgen.
- **Din stil**: Billigst muligt, Mest sol, Tryghed, Bilen først eller Batteriet først – plus finjustering.
- **Finder selv det du har** og viser kun det. Vejr, spotpriser, solprognose og helligdage er indbygget.
- **Aldrig en halv kommando**: mangler en kontrol, styrer den ikke, og en test i skygge viser, hvad den fandt.
- **Styrer mange mærker**: Growatt (SPH/SPA og MIN/MOD TL-XH, efter model), Huawei, SolaX, Sungrow, SolarEdge, Fox ESS, GivEnergy og alle andre via selvvalgte
  kontroller; ladere fra KEBA, Easee, Zaptec, go-e, Wallbox, OCPP m.fl.
- **Altid skygge først**, kort til dashboards og knapper i Home Assistant.

**Installation:** *Indstillinger → Apps → Butik → ⋮ → Repositories* → tilføj
`https://github.com/Clahen86/Energy-pilot`, installér **Energipilot**, start den, og følg guiden.

MIT-licens.
