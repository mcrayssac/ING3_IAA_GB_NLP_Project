# Interface

The Gradio app in `boxbox/app/` shows one race card beside the conversation about it. This file holds one spec per interface feature.

## Circle of doom

The circle is one lap measured in time. It shows where the card's car would rejoin the race if it boxed on this lap.

- Data comes from the race card only, so the screen never shows more than the model saw.
- The card gives the gap to the leader for each listed car, a reference lap time and the pit loss, all in seconds. It must list the cars within one pit loss behind the car, or the rejoin point has no neighbours.
- Cars run clockwise, so each car sits at `(gap mod lap_time) / lap_time × 360°` counter-clockwise from the leader at the top.
- The rejoin point is the car's gap plus the pit loss. A shaded sector covers the time spent in the pit lane.
- A car without a gap is listed as "gap missing" and not drawn. If the lap time or the pit loss is missing, the circle draws no rejoin point and names the missing field.
- A line under the circle states its assumption: the pit loss is fixed and the other cars keep their pace.
- The circle is a polar chart in `gr.Plot`, redrawn when the card changes.
- Tests check the angle and the rejoin point on hand-written cards, including a lapped car and a missing gap.
