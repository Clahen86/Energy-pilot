# Energipilot · Energy Pilot

**Your home battery, solar panels and electric car - planned hour by hour for the lowest price, in one beautiful app
for Home Assistant.** It always starts in *shadow*: it shows what it would do, but controls nothing until you say so.

![Energy Pilot](docs/screens_en.png)

## What it does

- **Live energy flow** – sun, house, battery, grid and car, with light beams that follow the power.
- **A plan for today and tomorrow** – it charges the battery when power is cheap or the sun gives too much, and uses it
  when power is expensive. The car charges on sun first, then in the cheapest hours before it must be ready.
- **Learns by itself** – your house's use (temperature, weekdays, holidays), what your solar panels make of the
  sunshine, and every night it checks yesterday with the real numbers and adjusts. A self-check shows what it saved.
- **Your choice of style** – *Cheapest*, *Most sun*, *Safety* (keeps 30 % for power cuts), *Car first* or *Battery first*,
  plus fine-tuning: battery minimum, grid charging, selling, main fuse, quiet hours for battery and car.
- **Finds what you have** – from the Energy dashboard, known integrations and names. Shows only what you have.
- **Needs almost nothing** – weather (Open-Meteo), spot prices (Energi Data Service / energy-charts.info for 26 European
  countries), its own solar forecast and holidays are built in. Your own Strømligning, Nord Pool, Tibber or Solcast is
  used when you have it. No spot price where you live (USA, UK…)? Enter your tariff plan or start from a template.
- **Controls many brands** – inverters: Growatt, Huawei, SolaX, Sungrow, SolarEdge, Fox ESS, GivEnergy, or any other by
  picking the controls yourself. Chargers: KEBA, Easee, Zaptec, go-e, Wallbox, OCPP and more.
- **Shadow first, always** – each part (battery, car) can be *Shadow*, *In control* or *Off*. One tap puts everything
  back in shadow. It never fights another system that controls the same battery.
- **Dashboard cards** – energy flow, plan, car, battery or everything, under *Add card → Energipilot*.
- **Buttons in Home Assistant** – *Charge now*, *Ready at*, *At most*, *Battery minimum*, *Style*, and sensors for the
  decision, price, battery target and savings - for your own automations.
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

Everything runs in your home. It only fetches public data: weather (Open-Meteo), spot prices (Energi Data Service,
energy-charts.info) and exchange rates (ECB via frankfurter.dev).

---

## Dansk

**Husbatteri, solceller og elbil – planlagt time for time til den laveste pris, i én flot app til Home Assistant.**
Den starter altid i *skygge*: den viser, hvad den ville gøre, men styrer intet, før du siger til.

![Energipilot](docs/screens_da.png)

- **Levende energiflow** og **dagens og morgendagens plan**.
- **Lærer selv**: husets forbrug, hvad dine solceller giver, og den gennemgår hver nat gårsdagen og retter sig.
- **Din stil**: Billigst muligt, Mest sol, Tryghed, Bilen først eller Batteriet først – plus finjustering.
- **Finder selv det du har** og viser kun det. Vejr, spotpriser, solprognose og helligdage er indbygget.
- **Styrer mange mærker**: Growatt, Huawei, SolaX, Sungrow, SolarEdge, Fox ESS, GivEnergy og alle andre via selvvalgte
  kontroller; ladere fra KEBA, Easee, Zaptec, go-e, Wallbox, OCPP m.fl.
- **Altid skygge først**, kort til dashboards og knapper i Home Assistant.

**Installation:** *Indstillinger → Apps → Butik → ⋮ → Repositories* → tilføj
`https://github.com/Clahen86/Energy-pilot`, installér **Energipilot**, start den, og følg guiden.

MIT-licens.
