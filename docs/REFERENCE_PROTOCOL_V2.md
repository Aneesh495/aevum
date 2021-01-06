# Reference reconstruction protocol v2

The original audit compared all output columns at face value. It found that the field labeled Lx equals lx in all 25,452 sampled rows, including the open age. This contradicts the usual definition of Lx as years lived in an age interval. For example, a 100+ life table row with 418.869 survivors and 811.357 remaining person-years has 811.357 person-years lived within that open interval, even though the column labeled Lx says 418.869. Keep the published fields in the raw table and report that discrepancy. Check person-years against successive published Tx values, with Tx after the tail equal to zero. All tolerance limits stay at v1 values.

Rows at the apparent central-rate cap of 1 can contain a published qx incompatible with their displayed mx and ax. A reference schedule with such a row is excluded from the matched-input test when the discrepancy exceeds the declared qx tolerance. Retain the affected population, period, and age. This is a statement about whether the columns can jointly identify the input to the reproduction, rather than a repair to the published rates.

The tested identity is an independent arithmetic reconstruction given the UN schedule and its a(x) assumptions. It does not validate the source mortality estimates as observed outcomes.
