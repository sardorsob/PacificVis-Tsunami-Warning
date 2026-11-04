# B7 — confirmation

Preliminary descriptive results; no model fit or causal identification.

```json
{
  "NTWC-reports": {
    "branch": "B7",
    "triggered": true,
    "scalar": 0.4181818181818182,
    "detail": {
      "selected_route": "era",
      "peak_size_contrast_present": true,
      "availability_era": [
        {
          "accepted_rows": 50,
          "availability": 0.4,
          "events": 7,
          "exact_observed": 20,
          "group": "2007-2013",
          "retained_rows": 55,
          "structural_rows": 5
        },
        {
          "accepted_rows": 11,
          "availability": 0.8181818181818182,
          "events": 4,
          "exact_observed": 9,
          "group": "2014plus",
          "retained_rows": 11,
          "structural_rows": 0
        },
        {
          "accepted_rows": 100,
          "availability": 0.54,
          "events": 3,
          "exact_observed": 54,
          "group": "pre2007",
          "retained_rows": 100,
          "structural_rows": 0
        }
      ],
      "within_event": [],
      "scope": "NTWC exact-UTC availability only; NCEI availability not measured here",
      "mechanism": "not identified; calendar/format/era confounding"
    },
    "checks_maximum": 2,
    "status": "exploratory_screen"
  }
}
```
