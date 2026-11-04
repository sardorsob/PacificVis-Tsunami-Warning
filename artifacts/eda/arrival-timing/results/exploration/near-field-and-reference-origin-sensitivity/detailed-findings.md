# B9 — exploration

Preliminary descriptive results; no model fit or causal identification.

```json
{
  "T-OBS": {
    "branch": "B9",
    "triggered": true,
    "scalar": 0.47514719055064125,
    "detail": {
      "selected_route": "near_far",
      "cutoffs": [
        {
          "cutoff_reference_minutes": 30,
          "near_n": 19,
          "far_n": 217,
          "difference": 0.41818847474601556
        },
        {
          "cutoff_reference_minutes": 60,
          "near_n": 33,
          "far_n": 203,
          "difference": 0.36480946172874457
        },
        {
          "cutoff_reference_minutes": 90,
          "near_n": 50,
          "far_n": 186,
          "difference": 0.37372436643250245
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
    "scalar": 0.6020010222209724,
    "detail": {
      "selected_route": "near_far",
      "cutoffs": [
        {
          "cutoff_reference_minutes": 30,
          "near_n": 71,
          "far_n": 999,
          "difference": 0.7271802005724018
        },
        {
          "cutoff_reference_minutes": 60,
          "near_n": 160,
          "far_n": 910,
          "difference": 0.49358625665491646
        },
        {
          "cutoff_reference_minutes": 90,
          "near_n": 226,
          "far_n": 844,
          "difference": 0.45804223997916593
        }
      ],
      "origin_precision_ratios": {
        "n": 1070,
        "finite_n": 1070,
        "median": 0.0005,
        "q10": 0.0003333333333333333,
        "q90": 0.0015,
        "mad": 0.0001666666666666667,
        "min": 0.0,
        "max": 0.029833333333333333
      },
      "origin_route_status": "native-source comparison only"
    },
    "checks_maximum": 2,
    "status": "exploratory_screen"
  }
}
```
