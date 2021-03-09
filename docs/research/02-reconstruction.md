# Reconstructing the published age schedule

A published central rate and fixed a(x) jointly identify the death probability for a closed interval. To evaluate the implementation against external values, the v2 comparison loads published mx and ax and verifies qx, lx, dx, remaining person-years and e(x) from the complete WPP 2024 schedules. It compares interval person-years using differences in published Tx because the field labeled Lx equals lx across the sampled export.

The frozen frame covers 42 countries, both sexes, 1990, 2019 and 2021, and 101 ages. At 249 of 252 tables, eligible e(x) has maximum absolute reconstruction error 0.000052 years. Three tables include old-age capped rates incompatible with their reported qx. We retain their identifiers and ages. The eligible comparison tests arithmetic under the published method, using a synthetic radix of 100,000. [Reference protocol and example](../REFERENCE_PROTOCOL_V2.md)
