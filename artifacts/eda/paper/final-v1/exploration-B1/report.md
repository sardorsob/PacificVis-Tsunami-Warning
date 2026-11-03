# B1 — exploration

Preliminary descriptive results; no model fit or causal identification.

```json
{
  "T-OBS": {
    "branch": "B1",
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
      "native_numeric_ratio": {
        "n": 0,
        "finite_n": 0,
        "median": "unknown",
        "q10": "unknown",
        "q90": "unknown",
        "mad": "unknown"
      },
      "land_shadow": "unavailable: no approved coastline/bathymetric path input; no acquisition"
    },
    "checks_maximum": 2,
    "status": "exploratory_screen"
  },
  "NCEI-native-duration": {
    "branch": "B1",
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
      "native_numeric_ratio": {
        "n": 1070,
        "finite_n": 1070,
        "median": 1.0,
        "q10": 0.9999999999999996,
        "q90": 1.0000036279300377,
        "mad": 2.220446049250313e-16,
        "min": 0.9940074988153922,
        "max": 1.0065165860799692
      },
      "land_shadow": "unavailable: no approved coastline/bathymetric path input; no acquisition"
    },
    "checks_maximum": 2,
    "status": "exploratory_screen"
  }
}
```
