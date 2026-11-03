# B7 — exploration

Preliminary descriptive results; no model fit or causal identification.

```json
{
  "NTWC-reports": {
    "branch": "B7",
    "triggered": true,
    "scalar": 0.5343718102338793,
    "detail": {
      "selected_route": "era",
      "peak_size_contrast_present": true,
      "availability_era": [
        {
          "accepted_rows": 667,
          "availability": 0.44377811094452774,
          "events": 17,
          "exact_observed": 296,
          "group": "2007-2013",
          "retained_rows": 680,
          "structural_rows": 13
        },
        {
          "accepted_rows": 203,
          "availability": 0.8226600985221675,
          "events": 8,
          "exact_observed": 167,
          "group": "2014plus",
          "retained_rows": 219,
          "structural_rows": 16
        },
        {
          "accepted_rows": 111,
          "availability": 0.2882882882882883,
          "events": 6,
          "exact_observed": 32,
          "group": "pre2007",
          "retained_rows": 112,
          "structural_rows": 1
        }
      ],
      "within_event": [
        {
          "difference": 0.0,
          "event_id": "official20100227063411530_30",
          "key": "peak_present",
          "n_other": 94,
          "n_reference": 1,
          "other": "True",
          "reference": "False"
        },
        {
          "difference": 1.0,
          "event_id": "us20003k7a",
          "key": "peak_present",
          "n_other": 135,
          "n_reference": 6,
          "other": "True",
          "reference": "False"
        },
        {
          "difference": 0.0,
          "event_id": "usc000phx5",
          "key": "peak_present",
          "n_other": 2,
          "n_reference": 1,
          "other": "True",
          "reference": "False"
        },
        {
          "difference": 0.0,
          "event_id": "usp000gs2d",
          "key": "peak_present",
          "n_other": 16,
          "n_reference": 2,
          "other": "True",
          "reference": "False"
        },
        {
          "difference": 0.0,
          "event_id": "usp000gsmz",
          "key": "peak_present",
          "n_other": 8,
          "n_reference": 1,
          "other": "True",
          "reference": "False"
        }
      ],
      "scope": "NTWC exact-UTC availability only; NCEI availability not measured here",
      "mechanism": "not identified; calendar/format/era confounding"
    },
    "checks_maximum": 2,
    "status": "exploratory_screen"
  }
}
```
