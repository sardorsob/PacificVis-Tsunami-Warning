# C6 — exploration

Preliminary descriptive results; no model fit or causal identification.

```json
{
  "retained": 1011,
  "accepted": 981,
  "structural": 30,
  "exact_observed": 495,
  "absent_observed": 233,
  "absent_observed_with_peak": 179,
  "tables": {
    "availability-era": [
      {
        "group": "2007-2013",
        "retained_rows": 680,
        "accepted_rows": 667,
        "structural_rows": 13,
        "exact_observed": 296,
        "availability": 0.44377811094452774,
        "events": 17
      },
      {
        "group": "2014plus",
        "retained_rows": 219,
        "accepted_rows": 203,
        "structural_rows": 16,
        "exact_observed": 167,
        "availability": 0.8226600985221675,
        "events": 8
      },
      {
        "group": "pre2007",
        "retained_rows": 112,
        "accepted_rows": 111,
        "structural_rows": 1,
        "exact_observed": 32,
        "availability": 0.2882882882882883,
        "events": 6
      }
    ],
    "availability-header_family": [
      {
        "group": "arrival_eta_utc",
        "retained_rows": 43,
        "accepted_rows": 43,
        "structural_rows": 0,
        "exact_observed": 28,
        "availability": 0.6511627906976745,
        "events": 5
      },
      {
        "group": "computed_observed_utc",
        "retained_rows": 366,
        "accepted_rows": 363,
        "structural_rows": 3,
        "exact_observed": 8,
        "availability": 0.02203856749311295,
        "events": 9
      },
      {
        "group": "estimated_observed_gmt_jday",
        "retained_rows": 157,
        "accepted_rows": 141,
        "structural_rows": 16,
        "exact_observed": 110,
        "availability": 0.7801418439716312,
        "events": 1
      },
      {
        "group": "estimated_observed_utc_jday",
        "retained_rows": 445,
        "accepted_rows": 434,
        "structural_rows": 11,
        "exact_observed": 349,
        "availability": 0.804147465437788,
        "events": 16
      }
    ],
    "availability-provider": [
      {
        "group": "unknown",
        "retained_rows": 1011,
        "accepted_rows": 981,
        "structural_rows": 30,
        "exact_observed": 495,
        "availability": 0.5045871559633027,
        "events": 31
      }
    ],
    "availability-distance_band": [
      {
        "group": "0\u2013500km",
        "retained_rows": 29,
        "accepted_rows": 29,
        "structural_rows": 0,
        "exact_observed": 22,
        "availability": 0.7586206896551724,
        "events": 14
      },
      {
        "group": "10000\u201320050km",
        "retained_rows": 136,
        "accepted_rows": 136,
        "structural_rows": 0,
        "exact_observed": 41,
        "availability": 0.3014705882352941,
        "events": 10
      },
      {
        "group": "2000\u20135000km",
        "retained_rows": 76,
        "accepted_rows": 76,
        "structural_rows": 0,
        "exact_observed": 38,
        "availability": 0.5,
        "events": 13
      },
      {
        "group": "5000\u201310000km",
        "retained_rows": 205,
        "accepted_rows": 205,
        "structural_rows": 0,
        "exact_observed": 82,
        "availability": 0.4,
        "events": 13
      },
      {
        "group": "500\u20132000km",
        "retained_rows": 82,
        "accepted_rows": 82,
        "structural_rows": 0,
        "exact_observed": 55,
        "availability": 0.6707317073170732,
        "events": 13
      },
      {
        "group": "unknown",
        "retained_rows": 483,
        "accepted_rows": 453,
        "structural_rows": 30,
        "exact_observed": 257,
        "availability": 0.5673289183222958,
        "events": 26
      }
    ],
    "availability-peak_present": [
      {
        "group": "False",
        "retained_rows": 152,
        "accepted_rows": 122,
        "structural_rows": 30,
        "exact_observed": 33,
        "availability": 0.27049180327868855,
        "events": 11
      },
      {
        "group": "True",
        "retained_rows": 859,
        "accepted_rows": 859,
        "structural_rows": 0,
        "exact_observed": 462,
        "availability": 0.5378346915017462,
        "events": 25
      }
    ],
    "availability-by-event": [
      {
        "group": "official20100227063411530_30",
        "retained_rows": 95,
        "accepted_rows": 95,
        "structural_rows": 0,
        "exact_observed": 0,
        "availability": 0.0,
        "events": 1
      },
      {
        "group": "official20110311054624120_30",
        "retained_rows": 163,
        "accepted_rows": 152,
        "structural_rows": 11,
        "exact_observed": 130,
        "availability": 0.8552631578947368,
        "events": 1
      },
      {
        "group": "us10006jbi",
        "retained_rows": 4,
        "accepted_rows": 4,
        "structural_rows": 0,
        "exact_observed": 4,
        "availability": 1.0,
        "events": 1
      },
      {
        "group": "us20002yaw",
        "retained_rows": 2,
        "accepted_rows": 2,
        "structural_rows": 0,
        "exact_observed": 2,
        "availability": 1.0,
        "events": 1
      },
      {
        "group": "us20003k7a",
        "retained_rows": 157,
        "accepted_rows": 141,
        "structural_rows": 16,
        "exact_observed": 110,
        "availability": 0.7801418439716312,
        "events": 1
      },
      {
        "group": "us20007z80",
        "retained_rows": 11,
        "accepted_rows": 11,
        "structural_rows": 0,
        "exact_observed": 10,
        "availability": 0.9090909090909091,
        "events": 1
      },
      {
        "group": "us2000cmy3",
        "retained_rows": 35,
        "accepted_rows": 35,
        "structural_rows": 0,
        "exact_observed": 35,
        "availability": 1.0,
        "events": 1
      },
      {
        "group": "usb000pq41",
        "retained_rows": 2,
        "accepted_rows": 2,
        "structural_rows": 0,
        "exact_observed": 2,
        "availability": 1.0,
        "events": 1
      },
      {
        "group": "usc000f1s0",
        "retained_rows": 81,
        "accepted_rows": 81,
        "structural_rows": 0,
        "exact_observed": 59,
        "availability": 0.7283950617283951,
        "events": 1
      },
      {
        "group": "usc000f40j",
        "retained_rows": 1,
        "accepted_rows": 1,
        "structural_rows": 0,
        "exact_observed": 0,
        "availability": 0.0,
        "events": 1
      },
      {
        "group": "usc000phx5",
        "retained_rows": 3,
        "accepted_rows": 3,
        "structural_rows": 0,
        "exact_observed": 0,
        "availability": 0.0,
        "events": 1
      },
      {
        "group": "usc000piqj",
        "retained_rows": 5,
        "accepted_rows": 5,
        "structural_rows": 0,
        "exact_observed": 4,
        "availability": 0.8,
        "events": 1
      },
      {
        "group": "usp000d3mb",
        "retained_rows": 1,
        "accepted_rows": 1,
        "structural_rows": 0,
        "exact_observed": 1,
        "availability": 1.0,
        "events": 1
      },
      {
        "group": "usp000d9h1",
        "retained_rows": 1,
        "accepted_rows": 1,
        "structural_rows": 0,
        "exact_observed": 1,
        "availability": 1.0,
        "events": 1
      },
      {
        "group": "usp000db93",
        "retained_rows": 1,
        "accepted_rows": 1,
        "structural_rows": 0,
        "exact_observed": 1,
        "availability": 1.0,
        "events": 1
      },
      {
        "group": "usp000dt25",
        "retained_rows": 1,
        "accepted_rows": 1,
        "structural_rows": 0,
        "exact_observed": 0,
        "availability": 0.0,
        "events": 1
      },
      {
        "group": "usp000eg5g",
        "retained_rows": 39,
        "accepted_rows": 39,
        "structural_rows": 0,
        "exact_observed": 25,
        "availability": 0.6410256410256411,
        "events": 1
      },
      {
        "group": "usp000exfn",
        "retained_rows": 69,
        "accepted_rows": 68,
        "structural_rows": 1,
        "exact_observed": 4,
        "availability": 0.058823529411764705,
        "events": 1
      },
      {
        "group": "usp000f2ab",
        "retained_rows": 28,
        "accepted_rows": 27,
        "structural_rows": 1,
        "exact_observed": 1,
        "availability": 0.037037037037037035,
        "events": 1
      },
      {
        "group": "usp000fjta",
        "retained_rows": 40,
        "accepted_rows": 39,
        "structural_rows": 1,
        "exact_observed": 0,
        "availability": 0.0,
        "events": 1
      },
      {
        "group": "usp000gs2d",
        "retained_rows": 18,
        "accepted_rows": 18,
        "structural_rows": 0,
        "exact_observed": 0,
        "availability": 0.0,
        "events": 1
      },
      {
        "group": "usp000gsmz",
        "retained_rows": 9,
        "accepted_rows": 9,
        "structural_rows": 0,
        "exact_observed": 0,
        "availability": 0.0,
        "events": 1
      },
      {
        "group": "usp000gtnc",
        "retained_rows": 1,
        "accepted_rows": 1,
        "structural_rows": 0,
        "exact_observed": 0,
        "availability": 0.0,
        "events": 1
      },
      {
        "group": "usp000h1ys",
        "retained_rows": 71,
        "accepted_rows": 71,
        "structural_rows": 0,
        "exact_observed": 3,
        "availability": 0.04225352112676056,
        "events": 1
      },
      {
        "group": "usp000h2g9",
        "retained_rows": 35,
        "accepted_rows": 35,
        "structural_rows": 0,
        "exact_observed": 0,
        "availability": 0.0,
        "events": 1
      },
      {
        "group": "usp000hrw0",
        "retained_rows": 4,
        "accepted_rows": 4,
        "structural_rows": 0,
        "exact_observed": 2,
        "availability": 0.5,
        "events": 1
      },
      {
        "group": "usp000j3mq",
        "retained_rows": 7,
        "accepted_rows": 7,
        "structural_rows": 0,
        "exact_observed": 7,
        "availability": 1.0,
        "events": 1
      },
      {
        "group": "usp000j48h",
        "retained_rows": 23,
        "accepted_rows": 23,
        "structural_rows": 0,
        "exact_observed": 10,
        "availability": 0.43478260869565216,
        "events": 1
      },
      {
        "group": "usp000j9nm",
        "retained_rows": 2,
        "accepted_rows": 2,
        "structural_rows": 0,
        "exact_observed": 2,
        "availability": 1.0,
        "events": 1
      },
      {
        "group": "usp000jqvm",
        "retained_rows": 10,
        "accepted_rows": 10,
        "structural_rows": 0,
        "exact_observed": 9,
        "availability": 0.9,
        "events": 1
      },
      {
        "group": "usp000juhz",
        "retained_rows": 92,
        "accepted_rows": 92,
        "structural_rows": 0,
        "exact_observed": 73,
        "availability": 0.7934782608695652,
        "events": 1
      }
    ],
    "within-event-peak-presence": [
      {
        "event_id": "official20100227063411530_30",
        "reference": "False",
        "other": "True",
        "key": "peak_present",
        "n_reference": 1,
        "n_other": 94,
        "difference": 0.0
      },
      {
        "event_id": "us20003k7a",
        "reference": "False",
        "other": "True",
        "key": "peak_present",
        "n_reference": 6,
        "n_other": 135,
        "difference": 1.0
      },
      {
        "event_id": "usc000phx5",
        "reference": "False",
        "other": "True",
        "key": "peak_present",
        "n_reference": 1,
        "n_other": 2,
        "difference": 0.0
      },
      {
        "event_id": "usp000gs2d",
        "reference": "False",
        "other": "True",
        "key": "peak_present",
        "n_reference": 2,
        "n_other": 16,
        "difference": 0.0
      },
      {
        "event_id": "usp000gsmz",
        "reference": "False",
        "other": "True",
        "key": "peak_present",
        "n_reference": 1,
        "n_other": 8,
        "difference": 0.0
      }
    ],
    "within-event-peak-size": [
      {
        "event_id": "official20110311054624120_30",
        "exact_observed_n": 130,
        "not_exact_observed_n": 22,
        "native_median_difference": 35.0,
        "unit_scope": "official20110311054624120_30/1/estimated_observed_utc_jday; native units unknown; no pooled size"
      },
      {
        "event_id": "us20003k7a",
        "exact_observed_n": 109,
        "not_exact_observed_n": 26,
        "native_median_difference": 11.0,
        "unit_scope": "us20003k7a/1/estimated_observed_gmt_jday; native units unknown; no pooled size"
      },
      {
        "event_id": "us20007z80",
        "exact_observed_n": 10,
        "not_exact_observed_n": 1,
        "native_median_difference": 3.5,
        "unit_scope": "us20007z80/1/estimated_observed_utc_jday; native units unknown; no pooled size"
      },
      {
        "event_id": "usc000f1s0",
        "exact_observed_n": 59,
        "not_exact_observed_n": 22,
        "native_median_difference": 1.5,
        "unit_scope": "usc000f1s0/1/estimated_observed_utc_jday; native units unknown; no pooled size"
      },
      {
        "event_id": "usc000piqj",
        "exact_observed_n": 4,
        "not_exact_observed_n": 1,
        "native_median_difference": 3.0,
        "unit_scope": "usc000piqj/1/estimated_observed_utc_jday; native units unknown; no pooled size"
      },
      {
        "event_id": "usp000f2ab",
        "exact_observed_n": 1,
        "not_exact_observed_n": 26,
        "native_median_difference": -1.5,
        "unit_scope": "usp000f2ab/1/computed_observed_utc; native units unknown; no pooled size"
      },
      {
        "event_id": "usp000h1ys",
        "exact_observed_n": 3,
        "not_exact_observed_n": 68,
        "native_median_difference": 224.8,
        "unit_scope": "usp000h1ys/1/computed_observed_utc; native units unknown; no pooled size"
      },
      {
        "event_id": "usp000hrw0",
        "exact_observed_n": 2,
        "not_exact_observed_n": 2,
        "native_median_difference": 5.5,
        "unit_scope": "usp000hrw0/1/estimated_observed_utc_jday; native units unknown; no pooled size"
      },
      {
        "event_id": "usp000j48h",
        "exact_observed_n": 10,
        "not_exact_observed_n": 13,
        "native_median_difference": 2.0,
        "unit_scope": "usp000j48h/1/estimated_observed_utc_jday; native units unknown; no pooled size"
      },
      {
        "event_id": "usp000jqvm",
        "exact_observed_n": 9,
        "not_exact_observed_n": 1,
        "native_median_difference": -13.0,
        "unit_scope": "usp000jqvm/1/estimated_observed_utc_jday; native units unknown; no pooled size"
      },
      {
        "event_id": "usp000juhz",
        "exact_observed_n": 73,
        "not_exact_observed_n": 19,
        "native_median_difference": 2.5,
        "unit_scope": "usp000juhz/1/estimated_observed_utc_jday; native units unknown; no pooled size"
      }
    ]
  },
  "opportunities": "Heterogeneous opportunities; not an operating-station census",
  "mechanism": "MCAR/MAR/MNAR unidentified; contrasts descriptive only"
}
```
