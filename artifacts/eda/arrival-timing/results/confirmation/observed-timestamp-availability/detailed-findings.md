# C6 — confirmation

Preliminary descriptive results; no model fit or causal identification.

```json
{
  "retained": 166,
  "accepted": 161,
  "structural": 5,
  "exact_observed": 83,
  "absent_observed": 56,
  "absent_observed_with_peak": 11,
  "tables": {
    "availability-era": [
      {
        "group": "2007-2013",
        "retained_rows": 55,
        "accepted_rows": 50,
        "structural_rows": 5,
        "exact_observed": 20,
        "availability": 0.4,
        "events": 7
      },
      {
        "group": "2014plus",
        "retained_rows": 11,
        "accepted_rows": 11,
        "structural_rows": 0,
        "exact_observed": 9,
        "availability": 0.8181818181818182,
        "events": 4
      },
      {
        "group": "pre2007",
        "retained_rows": 100,
        "accepted_rows": 100,
        "structural_rows": 0,
        "exact_observed": 54,
        "availability": 0.54,
        "events": 3
      }
    ],
    "availability-header_family": [
      {
        "group": "arrival_eta_utc",
        "retained_rows": 100,
        "accepted_rows": 100,
        "structural_rows": 0,
        "exact_observed": 54,
        "availability": 0.54,
        "events": 3
      },
      {
        "group": "computed_observed_utc",
        "retained_rows": 36,
        "accepted_rows": 35,
        "structural_rows": 1,
        "exact_observed": 6,
        "availability": 0.17142857142857143,
        "events": 3
      },
      {
        "group": "estimated_observed_utc_jday",
        "retained_rows": 26,
        "accepted_rows": 26,
        "structural_rows": 0,
        "exact_observed": 23,
        "availability": 0.8846153846153846,
        "events": 8
      },
      {
        "group": "unknown",
        "retained_rows": 4,
        "accepted_rows": 0,
        "structural_rows": 4,
        "exact_observed": 0,
        "availability": "unknown",
        "events": 0
      }
    ],
    "availability-provider": [
      {
        "group": "unknown",
        "retained_rows": 166,
        "accepted_rows": 161,
        "structural_rows": 5,
        "exact_observed": 83,
        "availability": 0.515527950310559,
        "events": 14
      }
    ],
    "availability-distance_band": [
      {
        "group": "0\u2013500km",
        "retained_rows": 5,
        "accepted_rows": 5,
        "structural_rows": 0,
        "exact_observed": 1,
        "availability": 0.2,
        "events": 3
      },
      {
        "group": "10000\u201320050km",
        "retained_rows": 7,
        "accepted_rows": 7,
        "structural_rows": 0,
        "exact_observed": 0,
        "availability": 0.0,
        "events": 2
      },
      {
        "group": "2000\u20135000km",
        "retained_rows": 8,
        "accepted_rows": 8,
        "structural_rows": 0,
        "exact_observed": 7,
        "availability": 0.875,
        "events": 3
      },
      {
        "group": "5000\u201310000km",
        "retained_rows": 9,
        "accepted_rows": 9,
        "structural_rows": 0,
        "exact_observed": 6,
        "availability": 0.6666666666666666,
        "events": 2
      },
      {
        "group": "500\u20132000km",
        "retained_rows": 14,
        "accepted_rows": 14,
        "structural_rows": 0,
        "exact_observed": 8,
        "availability": 0.5714285714285714,
        "events": 5
      },
      {
        "group": "unknown",
        "retained_rows": 123,
        "accepted_rows": 118,
        "structural_rows": 5,
        "exact_observed": 61,
        "availability": 0.5169491525423728,
        "events": 10
      }
    ],
    "availability-peak_present": [
      {
        "group": "False",
        "retained_rows": 105,
        "accepted_rows": 100,
        "structural_rows": 5,
        "exact_observed": 54,
        "availability": 0.54,
        "events": 3
      },
      {
        "group": "True",
        "retained_rows": 61,
        "accepted_rows": 61,
        "structural_rows": 0,
        "exact_observed": 29,
        "availability": 0.47540983606557374,
        "events": 11
      }
    ],
    "availability-by-event": [
      {
        "group": "official20010623203314130_33",
        "retained_rows": 61,
        "accepted_rows": 61,
        "structural_rows": 0,
        "exact_observed": 23,
        "availability": 0.3770491803278688,
        "events": 1
      },
      {
        "group": "official20030925195006360_27",
        "retained_rows": 20,
        "accepted_rows": 20,
        "structural_rows": 0,
        "exact_observed": 15,
        "availability": 0.75,
        "events": 1
      },
      {
        "group": "us1000gjaz",
        "retained_rows": 4,
        "accepted_rows": 4,
        "structural_rows": 0,
        "exact_observed": 4,
        "availability": 1.0,
        "events": 1
      },
      {
        "group": "us20009x42",
        "retained_rows": 1,
        "accepted_rows": 1,
        "structural_rows": 0,
        "exact_observed": 1,
        "availability": 1.0,
        "events": 1
      },
      {
        "group": "usb000pr89",
        "retained_rows": 1,
        "accepted_rows": 1,
        "structural_rows": 0,
        "exact_observed": 1,
        "availability": 1.0,
        "events": 1
      },
      {
        "group": "usb000sk6k",
        "retained_rows": 5,
        "accepted_rows": 5,
        "structural_rows": 0,
        "exact_observed": 3,
        "availability": 0.6,
        "events": 1
      },
      {
        "group": "usp000cd1n",
        "retained_rows": 19,
        "accepted_rows": 19,
        "structural_rows": 0,
        "exact_observed": 16,
        "availability": 0.8421052631578947,
        "events": 1
      },
      {
        "group": "usp000fshy",
        "retained_rows": 14,
        "accepted_rows": 13,
        "structural_rows": 1,
        "exact_observed": 0,
        "availability": 0.0,
        "events": 1
      },
      {
        "group": "usp000g3eq",
        "retained_rows": 1,
        "accepted_rows": 1,
        "structural_rows": 0,
        "exact_observed": 0,
        "availability": 0.0,
        "events": 1
      },
      {
        "group": "usp000gv5p",
        "retained_rows": 21,
        "accepted_rows": 21,
        "structural_rows": 0,
        "exact_observed": 6,
        "availability": 0.2857142857142857,
        "events": 1
      },
      {
        "group": "usp000h5np",
        "retained_rows": 4,
        "accepted_rows": 0,
        "structural_rows": 4,
        "exact_observed": 0,
        "availability": "unknown",
        "events": 0
      },
      {
        "group": "usp000hr97",
        "retained_rows": 5,
        "accepted_rows": 5,
        "structural_rows": 0,
        "exact_observed": 4,
        "availability": 0.8,
        "events": 1
      },
      {
        "group": "usp000jeag",
        "retained_rows": 1,
        "accepted_rows": 1,
        "structural_rows": 0,
        "exact_observed": 1,
        "availability": 1.0,
        "events": 1
      },
      {
        "group": "usp000jr83",
        "retained_rows": 7,
        "accepted_rows": 7,
        "structural_rows": 0,
        "exact_observed": 7,
        "availability": 1.0,
        "events": 1
      },
      {
        "group": "usp000jrsw",
        "retained_rows": 2,
        "accepted_rows": 2,
        "structural_rows": 0,
        "exact_observed": 2,
        "availability": 1.0,
        "events": 1
      }
    ],
    "within-event-peak-presence": [],
    "within-event-peak-size": [
      {
        "event_id": "usb000sk6k",
        "exact_observed_n": 3,
        "not_exact_observed_n": 2,
        "native_median_difference": -18.5,
        "unit_scope": "usb000sk6k/1/estimated_observed_utc_jday; native units unknown; no pooled size"
      },
      {
        "event_id": "usp000gv5p",
        "exact_observed_n": 6,
        "not_exact_observed_n": 15,
        "native_median_difference": -0.6000000000000005,
        "unit_scope": "usp000gv5p/1/computed_observed_utc; native units unknown; no pooled size"
      },
      {
        "event_id": "usp000hr97",
        "exact_observed_n": 4,
        "not_exact_observed_n": 1,
        "native_median_difference": 3.5,
        "unit_scope": "usp000hr97/1/estimated_observed_utc_jday; native units unknown; no pooled size"
      }
    ]
  },
  "opportunities": "Heterogeneous opportunities; not an operating-station census",
  "mechanism": "MCAR/MAR/MNAR unidentified; contrasts descriptive only"
}
```
