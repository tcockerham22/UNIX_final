# Smoke-test facts: Earth and geography

This document provides stable, short facts for checking whether Ada retrieves
the corpus, includes a source, and distinguishes grounded answers from general
knowledge. It is intentionally ordinary reference material rather than a
technical exploit example.

## Oceans and continents

Earth has five commonly named oceans: the Pacific, Atlantic, Indian, Southern,
and Arctic Oceans. The Pacific Ocean is the largest and deepest of these oceans.
It stretches from the Arctic region in the north to the Southern Ocean in the
south and lies between Asia and Australia on its western side and the Americas
on its eastern side. The Mariana Trench is in the western Pacific, and its
Challenger Deep is the deepest known point in Earth's ocean.

The Atlantic Ocean is the second-largest ocean. It separates the Americas from
Europe and Africa. The Indian Ocean lies between eastern Africa, southern Asia,
western Australia, and the Southern Ocean. The Southern Ocean encircles
Antarctica. The Arctic Ocean is the smallest and shallowest of the five named
oceans. Ocean boundaries are conventions used for geography and science; water
circulates continuously between them.

The seven-continent model names Africa, Antarctica, Asia, Europe, North
America, Australia, and South America. Some educational systems combine or
divide regions differently, so the number of continents can depend on the
convention being taught. Asia is the largest continent by area. Australia is
the smallest continent in the seven-continent model. Antarctica is the
coldest, driest, and windiest continent.

## Geographic coordinates and maps

Latitude describes angular position north or south of the Equator. The Equator
is zero degrees latitude, while the poles are at ninety degrees north and south.
Longitude describes angular position east or west of a chosen prime meridian.
The international reference prime meridian passes through Greenwich, England.
Latitude and longitude are angles, not distances: one degree of longitude
corresponds to different ground distances at different latitudes.

Maps are projections from a curved surface to a flat surface. Every flat map
projection distorts at least one property, such as area, shape, distance, or
direction. The Mercator projection preserves local angles and is useful for
some navigation tasks, but it greatly enlarges regions near the poles. An
equal-area projection preserves relative areas but changes shapes. Map readers
should check the projection and scale before comparing sizes or distances.

The scale bar on a map relates a measured map distance to a ground distance.
A legend explains symbols and colors. A north arrow indicates map orientation
when the top of the map is not north. A thematic map emphasizes a particular
subject, such as population density or average rainfall, while a reference map
shows general features such as roads, borders, and settlements.

## How to verify a retrieved fact

For a smoke test, ask which ocean is largest and deepest, then check whether
the response says the Pacific Ocean and cites this file as its source. A good
retrieval-backed response should not invent a quotation or page number that
does not exist. The source is this Markdown document, not a textbook page.
The retrieved passage should contain the Pacific Ocean fact. If Ada gives a
different answer, inspect the retrieved source list and verify the embedding
model and database ingestion before drawing a conclusion about the model.

