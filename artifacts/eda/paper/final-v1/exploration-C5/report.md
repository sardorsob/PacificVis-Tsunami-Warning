# C5 — exploration

Preliminary descriptive results; no model fit or causal identification.

```json
{
  "posthoc_P1": {
    "n": 56,
    "finite_n": 56,
    "median": -0.14699999999999136,
    "q10": -0.7925833333333685,
    "q90": 0.4523333333333994,
    "mad": 0.5993333333332771,
    "min": -26.430500000000052,
    "max": 19.85300000000001,
    "ci_low": -0.18316666666669335,
    "ci_high": 0.45233333333328574,
    "identity_approved": false,
    "interpretation": "posthoc geography only; no onset equivalence or independence"
  },
  "linked": {
    "n": 0,
    "finite_n": 0,
    "median": "unknown",
    "q10": "unknown",
    "q90": "unknown",
    "mad": "unknown",
    "ci_low": "unknown",
    "ci_high": "unknown",
    "categories": {},
    "interpretation": "geographic comparisons only; lineage unresolved"
  },
  "T-OBS": {
    "header_family": [
      {
        "group": "computed_observed_utc",
        "n": 4,
        "finite_n": 4,
        "median": -0.03951407958708607,
        "q10": -0.16374693030692938,
        "q90": -0.020655242506849632,
        "mad": 0.015230167253891466,
        "min": -0.21435022660627837,
        "max": -0.015212237767332182
      },
      {
        "group": "estimated_observed_gmt_jday",
        "n": 86,
        "finite_n": 86,
        "median": 0.035031471234197635,
        "q10": -0.09900240783132452,
        "q90": 0.2791424428920388,
        "mad": 0.057324500132566875,
        "min": -0.6031068231396874,
        "max": 0.6423435477208669
      },
      {
        "group": "estimated_observed_utc_jday",
        "n": 146,
        "finite_n": 146,
        "median": 0.06918131214907253,
        "q10": -0.0880017992804491,
        "q90": 0.6055112844845152,
        "mad": 0.14209872871105728,
        "min": -5.124550566534354,
        "max": 2.1157762039458885
      }
    ],
    "within-header_family": {
      "contrasts": 0,
      "n": 0,
      "finite_n": 0,
      "median": "unknown",
      "q10": "unknown",
      "q90": "unknown",
      "mad": "unknown"
    },
    "era": [
      {
        "group": "2007-2013",
        "n": 135,
        "finite_n": 135,
        "median": 0.04771086616741689,
        "q10": -0.08836841242164972,
        "q90": 0.5710782621696496,
        "mad": 0.1342268150519998,
        "min": -0.5798094681518574,
        "max": 2.1157762039458885
      },
      {
        "group": "2014plus",
        "n": 100,
        "finite_n": 100,
        "median": 0.03958434836926316,
        "q10": -0.08567443821746983,
        "q90": 0.3666713789390548,
        "mad": 0.0590280511407572,
        "min": -5.124550566534354,
        "max": 1.551996028112706
      },
      {
        "group": "pre2007",
        "n": 1,
        "finite_n": 1,
        "median": -0.04567257227511511,
        "q10": -0.04567257227511511,
        "q90": -0.04567257227511511,
        "mad": 0.0,
        "min": -0.04567257227511511,
        "max": -0.04567257227511511
      }
    ],
    "within-era": {
      "contrasts": 0,
      "n": 0,
      "finite_n": 0,
      "median": "unknown",
      "q10": "unknown",
      "q90": "unknown",
      "mad": "unknown"
    },
    "provider": [
      {
        "group": "unknown",
        "n": 236,
        "finite_n": 236,
        "median": 0.040969727277932716,
        "q10": -0.08832980993399088,
        "q90": 0.5038218364954636,
        "mad": 0.09274532620725257,
        "min": -5.124550566534354,
        "max": 2.1157762039458885
      }
    ],
    "within-provider": {
      "contrasts": 0,
      "n": 0,
      "finite_n": 0,
      "median": "unknown",
      "q10": "unknown",
      "q90": "unknown",
      "mad": "unknown"
    },
    "precision_seconds": [
      {
        "group": "60",
        "n": 156,
        "finite_n": 156,
        "median": 0.048659114765185515,
        "q10": -0.08832980993399088,
        "q90": 0.45175300632874327,
        "mad": 0.086813051902416,
        "min": -0.3961491785152382,
        "max": 1.551996028112706
      },
      {
        "group": "unknown",
        "n": 80,
        "finite_n": 80,
        "median": 0.03612835936490179,
        "q10": -0.08159699057510153,
        "q90": 0.5643547661333521,
        "mad": 0.09609180051649521,
        "min": -5.124550566534354,
        "max": 2.1157762039458885
      }
    ],
    "within-precision_seconds": {
      "contrasts": 8,
      "n": 8,
      "finite_n": 8,
      "median": -49.5,
      "q10": -413.0,
      "q90": 368.9,
      "mad": 255.0,
      "min": -609.0,
      "max": 391.99999999999994
    },
    "identity_tier": [
      {
        "group": "header_exact",
        "n": 236,
        "finite_n": 236,
        "median": 0.040969727277932716,
        "q10": -0.08832980993399088,
        "q90": 0.5038218364954636,
        "mad": 0.09274532620725257,
        "min": -5.124550566534354,
        "max": 2.1157762039458885
      }
    ],
    "within-identity_tier": {
      "contrasts": 0,
      "n": 0,
      "finite_n": 0,
      "median": "unknown",
      "q10": "unknown",
      "q90": "unknown",
      "mad": "unknown"
    },
    "time_evidence_tier": [
      {
        "group": "native_explicit_doy",
        "n": 232,
        "finite_n": 232,
        "median": 0.04493948535682432,
        "q10": -0.08810979785264716,
        "q90": 0.5202012466518168,
        "mad": 0.09638932656507679,
        "min": -5.124550566534354,
        "max": 2.1157762039458885
      },
      {
        "group": "source_reviewed_rule",
        "n": 4,
        "finite_n": 4,
        "median": -0.03951407958708607,
        "q10": -0.16374693030692938,
        "q90": -0.020655242506849632,
        "mad": 0.015230167253891466,
        "min": -0.21435022660627837,
        "max": -0.015212237767332182
      }
    ],
    "within-time_evidence_tier": {
      "contrasts": 0,
      "n": 0,
      "finite_n": 0,
      "median": "unknown",
      "q10": "unknown",
      "q90": "unknown",
      "mad": "unknown"
    },
    "identity_scope": [
      {
        "group": "authoritative_provider_site",
        "n": 100,
        "finite_n": 100,
        "median": 0.06327676357832229,
        "q10": -0.0892439012116416,
        "q90": 0.5691376597850929,
        "mad": 0.10135724235053499,
        "min": -0.22534327289927777,
        "max": 1.3855353745286547
      },
      {
        "group": "source_qualified_geographic_site",
        "n": 136,
        "finite_n": 136,
        "median": 0.0347247673892471,
        "q10": -0.0881948117187433,
        "q90": 0.4290362288766082,
        "mad": 0.09199861359471606,
        "min": -5.124550566534354,
        "max": 2.1157762039458885
      }
    ],
    "within-identity_scope": {
      "contrasts": 6,
      "n": 6,
      "finite_n": 6,
      "median": -242.75,
      "q10": -488.5,
      "q90": 168.49999999999994,
      "mad": 126.99999999999999,
      "min": -609.0,
      "max": 450.99999999999994
    },
    "measurement_family": [
      {
        "group": "reported_water_level_unknown_sensor",
        "n": 236,
        "finite_n": 236,
        "median": 0.040969727277932716,
        "q10": -0.08832980993399088,
        "q90": 0.5038218364954636,
        "mad": 0.09274532620725257,
        "min": -5.124550566534354,
        "max": 2.1157762039458885
      }
    ],
    "within-measurement_family": {
      "contrasts": 0,
      "n": 0,
      "finite_n": 0,
      "median": "unknown",
      "q10": "unknown",
      "q90": "unknown",
      "mad": "unknown"
    },
    "qualifier": [
      {
        "group": "[\"estimate:blank\"]",
        "n": 1,
        "finite_n": 1,
        "median": 0.1455948999144976,
        "q10": 0.1455948999144976,
        "q90": 0.1455948999144976,
        "mad": 0.0,
        "min": 0.1455948999144976,
        "max": 0.1455948999144976
      },
      {
        "group": "[\"estimate:date_ambiguous\"]",
        "n": 3,
        "finite_n": 3,
        "median": -0.015212237767332182,
        "q10": -0.0506807061256717,
        "q90": 0.32589485038736615,
        "mad": 0.0443355854479244,
        "min": -0.05954782321525658,
        "max": 0.4111716224260407
      },
      {
        "group": "[\"estimate:footnoted_value\"]",
        "n": 1,
        "finite_n": 1,
        "median": -0.031225198710358996,
        "q10": -0.031225198710358996,
        "q90": -0.031225198710358996,
        "mad": 0.0,
        "min": -0.031225198710358996,
        "max": -0.031225198710358996
      },
      {
        "group": "[\"estimate:source_absent_explicit\"]",
        "n": 75,
        "finite_n": 75,
        "median": 0.03665272239870832,
        "q10": -0.11090049921807589,
        "q90": 0.5662230195435702,
        "mad": 0.09598305541902552,
        "min": -5.124550566534354,
        "max": 2.1157762039458885
      },
      {
        "group": "[]",
        "n": 156,
        "finite_n": 156,
        "median": 0.048659114765185515,
        "q10": -0.08832980993399088,
        "q90": 0.45175300632874327,
        "mad": 0.086813051902416,
        "min": -0.3961491785152382,
        "max": 1.551996028112706
      }
    ],
    "within-qualifier": {
      "contrasts": 10,
      "n": 10,
      "finite_n": 10,
      "median": 41.0,
      "q10": -362.3,
      "q90": 627.4,
      "mad": 319.5,
      "min": -391.99999999999994,
      "max": 793.0
    }
  },
  "NCEI-native-duration": {
    "header_family": [
      {
        "group": "NCEI_native",
        "n": 1070,
        "finite_n": 1070,
        "median": 0.062278858876187365,
        "q10": -0.09291977581360056,
        "q90": 0.6718773014361386,
        "mad": 0.11539059425226436,
        "min": -3.082380822449964,
        "max": 3.4653642630189734
      }
    ],
    "within-header_family": {
      "contrasts": 0,
      "n": 0,
      "finite_n": 0,
      "median": "unknown",
      "q10": "unknown",
      "q90": "unknown",
      "mad": "unknown"
    },
    "era": [
      {
        "group": "2007-2013",
        "n": 773,
        "finite_n": 773,
        "median": 0.0658623650386932,
        "q10": -0.09102051756056263,
        "q90": 0.6483869505198565,
        "mad": 0.1203837104574757,
        "min": -2.319258212990191,
        "max": 3.1888106205999747
      },
      {
        "group": "2014plus",
        "n": 150,
        "finite_n": 150,
        "median": 0.046432777454291634,
        "q10": -0.04462808207032936,
        "q90": 0.395609321159909,
        "mad": 0.06372939881663929,
        "min": -0.6105128441284098,
        "max": 3.4653642630189734
      },
      {
        "group": "pre2007",
        "n": 147,
        "finite_n": 147,
        "median": 0.07313547662780863,
        "q10": -0.10344338972269268,
        "q90": 0.9470138976882266,
        "mad": 0.1898697144219315,
        "min": -3.082380822449964,
        "max": 1.8610556758904193
      }
    ],
    "within-era": {
      "contrasts": 0,
      "n": 0,
      "finite_n": 0,
      "median": "unknown",
      "q10": "unknown",
      "q90": "unknown",
      "mad": "unknown"
    },
    "provider": [
      {
        "group": "unknown",
        "n": 1070,
        "finite_n": 1070,
        "median": 0.062278858876187365,
        "q10": -0.09291977581360056,
        "q90": 0.6718773014361386,
        "mad": 0.11539059425226436,
        "min": -3.082380822449964,
        "max": 3.4653642630189734
      }
    ],
    "within-provider": {
      "contrasts": 0,
      "n": 0,
      "finite_n": 0,
      "median": "unknown",
      "q10": "unknown",
      "q90": "unknown",
      "mad": "unknown"
    },
    "precision_seconds": [
      {
        "group": "60",
        "n": 1070,
        "finite_n": 1070,
        "median": 0.062278858876187365,
        "q10": -0.09291977581360056,
        "q90": 0.6718773014361386,
        "mad": 0.11539059425226436,
        "min": -3.082380822449964,
        "max": 3.4653642630189734
      }
    ],
    "within-precision_seconds": {
      "contrasts": 0,
      "n": 0,
      "finite_n": 0,
      "median": "unknown",
      "q10": "unknown",
      "q90": "unknown",
      "mad": "unknown"
    },
    "identity_tier": [
      {
        "group": "unknown",
        "n": 1070,
        "finite_n": 1070,
        "median": 0.062278858876187365,
        "q10": -0.09291977581360056,
        "q90": 0.6718773014361386,
        "mad": 0.11539059425226436,
        "min": -3.082380822449964,
        "max": 3.4653642630189734
      }
    ],
    "within-identity_tier": {
      "contrasts": 0,
      "n": 0,
      "finite_n": 0,
      "median": "unknown",
      "q10": "unknown",
      "q90": "unknown",
      "mad": "unknown"
    },
    "time_evidence_tier": [
      {
        "group": "unknown",
        "n": 1070,
        "finite_n": 1070,
        "median": 0.062278858876187365,
        "q10": -0.09291977581360056,
        "q90": 0.6718773014361386,
        "mad": 0.11539059425226436,
        "min": -3.082380822449964,
        "max": 3.4653642630189734
      }
    ],
    "within-time_evidence_tier": {
      "contrasts": 0,
      "n": 0,
      "finite_n": 0,
      "median": "unknown",
      "q10": "unknown",
      "q90": "unknown",
      "mad": "unknown"
    },
    "identity_scope": [
      {
        "group": "source_native_position",
        "n": 1070,
        "finite_n": 1070,
        "median": 0.062278858876187365,
        "q10": -0.09291977581360056,
        "q90": 0.6718773014361386,
        "mad": 0.11539059425226436,
        "min": -3.082380822449964,
        "max": 3.4653642630189734
      }
    ],
    "within-identity_scope": {
      "contrasts": 0,
      "n": 0,
      "finite_n": 0,
      "median": "unknown",
      "q10": "unknown",
      "q90": "unknown",
      "mad": "unknown"
    },
    "measurement_family": [
      {
        "group": "deep_ocean_gauge",
        "n": 73,
        "finite_n": 73,
        "median": -0.0369133182428439,
        "q10": -0.33711822264244495,
        "q90": 0.10005775515237636,
        "mad": 0.09018830872834326,
        "min": -3.082380822449964,
        "max": 0.5892419682866612
      },
      {
        "group": "tide_gauge",
        "n": 997,
        "finite_n": 997,
        "median": 0.07006018312768719,
        "q10": -0.07401430851390042,
        "q90": 0.7136457729058822,
        "mad": 0.1192204447786448,
        "min": -2.319258212990191,
        "max": 3.4653642630189734
      }
    ],
    "within-measurement_family": {
      "contrasts": 13,
      "n": 13,
      "finite_n": 13,
      "median": 202.5,
      "q10": 3.2000000000000117,
      "q90": 324.5,
      "mad": 108.0,
      "min": -112.0,
      "max": 641.0
    },
    "qualifier": [
      {
        "group": "{\"doubtful\": \"n\", \"firstMotion\": \"F\", \"publish\": true}",
        "n": 53,
        "finite_n": 53,
        "median": 0.17473420729840453,
        "q10": -0.08883700805577145,
        "q90": 1.1964324030769093,
        "mad": 0.2458592390281137,
        "min": -0.4308201907982656,
        "max": 3.4653642630189734
      },
      {
        "group": "{\"doubtful\": \"n\", \"firstMotion\": \"R\", \"publish\": true}",
        "n": 482,
        "finite_n": 482,
        "median": 0.073142898835061,
        "q10": -0.06474280796570041,
        "q90": 0.8653415389736415,
        "mad": 0.12236865165857413,
        "min": -2.319258212990191,
        "max": 3.1888106205999747
      },
      {
        "group": "{\"doubtful\": \"n\", \"firstMotion\": \"unknown\", \"publish\": true}",
        "n": 535,
        "finite_n": 535,
        "median": 0.030917634097620855,
        "q10": -0.11330717166407109,
        "q90": 0.4078908402294845,
        "mad": 0.09382355264940712,
        "min": -3.082380822449964,
        "max": 1.8960893021319651
      }
    ],
    "within-qualifier": {
      "contrasts": 28,
      "n": 28,
      "finite_n": 28,
      "median": 135.75,
      "q10": -131.85,
      "q90": 561.85,
      "mad": 130.5,
      "min": -424.0,
      "max": 835.0
    }
  }
}
```
