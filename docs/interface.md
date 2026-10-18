# Interface

The Gradio app in `boxbox/app/` shows one race card beside the conversation about it. This file holds one spec per interface feature.

## Circle of doom

The circle is one lap measured in time. It shows where the card's car would rejoin the race if it boxed on this lap, compared with the car behind.

- Data comes from the race card only, so the screen never shows more than the model saw.
- It uses `gap_ahead` and `gap_behind` with their `driver_number`, `pit_loss_seconds` and `reference_lap_seconds`.
- Cars run clockwise and the card's car sits at the top. A gap of `g` seconds is `g / reference_lap_seconds × 360°`, clockwise for the car ahead and counter-clockwise for the car behind.
- The rejoin point sits one pit loss behind the car, followed by a 2.0-second band for the rejoin margin. The car behind is cleared when it sits past the end of the band, as in rule 6 of the contract.
- An `UNKNOWN` gap is listed as "gap unknown" and not drawn. A `NONE` gap is listed as "no car".
- Without `reference_lap_seconds` the circle is not drawn, and without `pit_loss_seconds` it has no rejoin point. The missing field is named in both cases.
- A line under the circle states its assumption: the pit loss is fixed and the other cars keep their pace.
- The circle is a polar chart in `gr.Plot`, redrawn when the card changes.
- The interface implementation must include tests of the angles and the rejoin point on hand-written cards, including an unknown gap and a missing lap time.
