# B1 — confirmation

Preliminary descriptive results; no model fit or causal identification.

```json
{
  "T-OBS": {
    "branch": "B1",
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
      "native_numeric_ratio": {
        "n": 151,
        "finite_n": 151,
        "median": 1.0,
        "q10": 0.9999733579335807,
        "q90": 1.0005146383192038,
        "mad": 6.661338147750939e-16,
        "min": 0.9988185334795483,
        "max": 1.0081426191554768
      },
      "land_shadow": "unavailable: no approved coastline/bathymetric path input; no acquisition"
    },
    "checks_maximum": 2,
    "status": "exploratory_screen"
  }
}
```
