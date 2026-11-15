# Energy Pilot visual assets

These assets are presentation only. Equipment visibility, normalized power signs,
source/destination allocation, settings, control actions and forecasts remain in
the existing application and card code.

- `spring_*`, `summer_*`, `autumn_*`, `winter_*`: the twelve existing garden
  backgrounds from `/config/image/Claude dia/Energy_pilot/`.
- `battery`, `car`, `charger`, `grid`, `solar`: existing transparent object layers
  from the same folder. They are rendered only for installed equipment.
- `house`, `house-winter`: edited using the built-in imagegen tool. They contain
  no solar panels or optional equipment, so a home without solar does not show
  solar equipment baked into its house image.

The shared `../energy-scene.js` renders the layers and live animations in both the
app and the Lovelace card. Weather and country-specific holiday selection still
come from `scene.py`. Disabling scene effects removes seasonal/weather/holiday
animation; energy movement remains independent. Reduced motion disables the CSS
animations. Flow allocation is the existing inferred allocation from power
measurements, not a new device-level measurement.

Generated asset prompts (built-in imagegen; no API/CLI fallback):

## House

Edit this existing isolated house render into the base house asset for a premium energy app. Preserve exactly the house silhouette, perspective and centered camera and overall square composition. REMOVE ALL solar panels completely: roof must be plain continuous dark slate tiles so the app can separately add solar equipment only for homes that have it. Remove cyan and purple neon edge strips, replace with believable subtle metallic edges. Keep warm interior lighting and convincing glass, wood, slate and stone textures. Refine toward a tasteful semi-realistic architectural visualization, not futuristic, not cartoon. Retain small bushes and garden lights at the base, but do not introduce sky or large scenery. No car, charger, battery, power lines, solar panels, text, labels or logos. Clean genuinely transparent background. House fully visible with margins. This is an edited reusable house-only layer.

## Winter house

Edit this house layer into the WINTER variant for the same energy app. Preserve the exact house, camera, perspective, scale and centered placement on the same transparent square canvas. Change only the season: physically believable soft snow lying on the entire slate roof, roof edges, shrubs, terrace edges, subtle frost on glass. Keep the glass facade, timber, slate textures and warm interior lights. No falling snow or sky: these are animated by the app. No solar panels, no car, no battery, no charger, no neon, no labels. Same house geometry and bounding box, genuinely transparent background. Premium semi-realistic architectural illustration.

## Validation

From the repository root:

```
node --experimental-default-type=module --test tests/test_visual_scene.mjs
python -m pytest -q tests/test_cards_assets.py tests/test_scene.py tests/test_runtime_storm.py tests/test_battstats.py tests/test_things.py tests/test_chargers.py tests/test_batteries.py
```

Local browser verification uses read-only API snapshots; no control POSTs or
Home Assistant service calls are needed to inspect the design. Validate in a local preview before installing the source in the running add-on
or copying it to live dashboard resources.
Backups (`*.before-visual-redesign-*`) preserve the pre-existing uncommitted
battery-card work and must be kept out of the eventual Git commit.
