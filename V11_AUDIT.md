# V1.1 Audit checklist

## Admin / Model
- Brand: choose existing or type a new brand name; new brand is created on Save.
- Model / Generation.
- Segment: blank / A / B / C / D / E.
- Body type: structured list.
- Market positioning: blank / Mass / Premium / Luxury.
- Production/import: blank / CBU / CKD / SKD.
- Production country.
- Thailand launch: Quarter + year only.
- Seats.
- Payload capacity.
- Current / Discontinued.
- Consumer description.
- Image URL.
- Unconfirmed flags.

## Powertrain
- Add multiple configurations.
- ICE: cc, engine code, power, torque.
- HEV: cc, engine code, optional motor output, power, torque.
- PHEV / REEV: cc, engine code, battery kWh + chemistry, motor kW, power, torque.
- BEV: battery kWh + chemistry, motor kW, power, torque; no cc field.
- Edit/remove from the same Model panel.

## Trim
- Add multiple trims.
- Name / current price / current-discontinued.
- Link trim to one or more model powertrains.
- Free-text equipment & safety description.
- Optional seat/payload override.
- Edit/remove from the same Model panel.
- Model min/max price derives from current trims after Save.

## Public
- `/models`: brand logo rail, structured filters, current models only.
- `/brands/[brand]`: current-model catalog for that brand.
- `/models/[model]`: consumer page with description, trims/prices, powertrain details, registration summary and news.
- If a production program exists, the consumer page links to `/production/[model]`.
- `/production`: industry-only view.
- `/plants`: capacity / estimated production / utilization / number of models.
- `/reports`: blurred future-paywall TDR Report preview.
- No public “Upcoming / รุ่นใหม่” category.

## Delete/edit
- Model: edit, Discontinue, or hard-delete with confirmation.
- Trim / powertrain: remove in Model editor and Save.
- Production program: edit/delete.
- Brand: edit/delete; deletion blocked while models use it.
- Plant / company / event: edit/delete.
