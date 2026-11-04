# B9 — confirmation

Preliminary descriptive results; no model fit or causal identification.

```json
{
  "T-OBS": {
    "branch": "B9",
    "triggered": true,
    "scalar": 0.3858280896310002,
    "detail": {
      "selected_route": "near_far",
      "cutoffs": [
        {
          "cutoff_reference_minutes": 30,
          "near_n": 1,
          "far_n": 21,
          "difference": 0.3858280896310002
        },
        {
          "cutoff_reference_minutes": 60,
          "near_n": 1,
          "far_n": 21,
          "difference": 0.3858280896310002
        },
        {
          "cutoff_reference_minutes": 90,
          "near_n": 1,
          "far_n": 21,
          "difference": 0.3858280896310002
        }
      ],
      "origin_precision_ratios": {
        "n": 0,
        "finite_n": 0,
        "median": "unknown",
        "q10": "unknown",
        "q90": "unknown",
        "mad": "unknown"
      },
      "origin_route_status": "original-report ancestry unidentifiable"
    },
    "checks_maximum": 2,
    "status": "exploratory_screen"
  },
  "NCEI-native-duration": {
    "branch": "B9",
    "triggered": true,
    "scalar": 0.6427138965958735,
    "detail": {
      "selected_route": "near_far",
      "cutoffs": [
        {
          "cutoff_reference_minutes": 30,
          "near_n": 25,
          "far_n": 126,
          "difference": 0.703225493442146
        },
        {
          "cutoff_reference_minutes": 60,
          "near_n": 39,
          "far_n": 112,
          "difference": 0.5829213092870258
        },
        {
          "cutoff_reference_minutes": 90,
          "near_n": 43,
          "far_n": 108,
          "difference": 0.4619814860699292
        }
      ],
      "origin_precision_ratios": {
        "n": 151,
        "finite_n": 151,
        "median": 0.001,
        "q10": 0.0,
        "q90": 0.047,
        "mad": 0.0006666666666666668,
        "min": 0.0,
        "max": 0.047
      },
      "origin_route_status": "native-source comparison only"
    },
    "checks_maximum": 2,
    "status": "exploratory_screen"
  }
}
```
