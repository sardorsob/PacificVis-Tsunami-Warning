# C4 — exploration

Preliminary descriptive results; no model fit or causal identification.

```json
{
  "T-OBS": {
    "physical_site_id": {
      "components": 3,
      "raw_rows": 236,
      "largest_component_rows": 233,
      "profiles": [
        {
          "component": 0,
          "rows": 233,
          "events": 11,
          "sites": 158,
          "cells": 233,
          "event_mad": 0.10268247807298203,
          "site_mad": 0.10469824537441254,
          "residual_mad": 0.0,
          "site_residual_ratio": "unknown",
          "event_residual_ratio": "unknown",
          "site_ratio_low": "unknown",
          "site_ratio_high": "unknown",
          "bootstrap_valid": 0,
          "residual_degrees": 65
        },
        {
          "component": 1,
          "rows": 2,
          "events": 2,
          "sites": 1,
          "cells": 2,
          "event_mad": 0.0061584926880290415,
          "site_mad": 0.0,
          "residual_mad": 0.0,
          "site_residual_ratio": "unknown",
          "event_residual_ratio": "unknown",
          "site_ratio_low": "unknown",
          "site_ratio_high": "unknown",
          "bootstrap_valid": 0,
          "residual_degrees": 0
        },
        {
          "component": 2,
          "rows": 1,
          "events": 1,
          "sites": 1,
          "cells": 1,
          "event_mad": 0.0,
          "site_mad": 0.0,
          "residual_mad": 0.0,
          "site_residual_ratio": "unknown",
          "event_residual_ratio": "unknown",
          "site_ratio_low": "unknown",
          "site_ratio_high": "unknown",
          "bootstrap_valid": 0,
          "residual_degrees": 0
        }
      ],
      "largest_event_effects": [
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "official20110311054624120_30",
          "effect": -0.17992454558291143,
          "site_key": "physical_site_id"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "us10006jbi",
          "effect": 0.5620924344079059,
          "site_key": "physical_site_id"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "us20003k7a",
          "effect": -0.059970709741798106,
          "site_key": "physical_site_id"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "us20007z80",
          "effect": 0.03292688677829492,
          "site_key": "physical_site_id"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usc000f1s0",
          "effect": -0.05918052545604449,
          "site_key": "physical_site_id"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000h1ys",
          "effect": -0.1570220123592394,
          "site_key": "physical_site_id"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000hrw0",
          "effect": -0.20889176353897013,
          "site_key": "physical_site_id"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000j3mq",
          "effect": 0.07308082051668247,
          "site_key": "physical_site_id"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000j48h",
          "effect": 0.0,
          "site_key": "physical_site_id"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000jqvm",
          "effect": 0.10268247807298203,
          "site_key": "physical_site_id"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000juhz",
          "effect": 0.16155917480481438,
          "site_key": "physical_site_id"
        }
      ]
    },
    "site_1km": {
      "components": 3,
      "raw_rows": 236,
      "largest_component_rows": 233,
      "profiles": [
        {
          "component": 0,
          "rows": 233,
          "events": 11,
          "sites": 143,
          "cells": 233,
          "event_mad": 0.12737446965748117,
          "site_mad": 0.10739774269886443,
          "residual_mad": 0.0011134073757243443,
          "site_residual_ratio": 96.45862335786592,
          "event_residual_ratio": 114.40059805119914,
          "site_ratio_low": "unknown",
          "site_ratio_high": "unknown",
          "bootstrap_valid": 0,
          "residual_degrees": 80
        },
        {
          "component": 1,
          "rows": 2,
          "events": 2,
          "sites": 1,
          "cells": 2,
          "event_mad": 0.0061584926880290415,
          "site_mad": 0.0,
          "residual_mad": 0.0,
          "site_residual_ratio": "unknown",
          "event_residual_ratio": "unknown",
          "site_ratio_low": "unknown",
          "site_ratio_high": "unknown",
          "bootstrap_valid": 0,
          "residual_degrees": 0
        },
        {
          "component": 2,
          "rows": 1,
          "events": 1,
          "sites": 1,
          "cells": 1,
          "event_mad": 0.0,
          "site_mad": 0.0,
          "residual_mad": 0.0,
          "site_residual_ratio": "unknown",
          "event_residual_ratio": "unknown",
          "site_ratio_low": "unknown",
          "site_ratio_high": "unknown",
          "bootstrap_valid": 0,
          "residual_degrees": 0
        }
      ],
      "largest_event_effects": [
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "official20110311054624120_30",
          "effect": -0.12737446965748117,
          "site_key": "site_1km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "us10006jbi",
          "effect": 0.589956874457979,
          "site_key": "site_1km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "us20003k7a",
          "effect": -0.00742063381636783,
          "site_key": "site_1km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "us20007z80",
          "effect": 0.08547696270372523,
          "site_key": "site_1km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usc000f1s0",
          "effect": -0.006630449530614216,
          "site_key": "site_1km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000h1ys",
          "effect": -0.10447193643380909,
          "site_key": "site_1km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000hrw0",
          "effect": -0.15634168761353984,
          "site_key": "site_1km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000j3mq",
          "effect": 0.4216225364038668,
          "site_key": "site_1km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000j48h",
          "effect": 0.0,
          "site_key": "site_1km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000jqvm",
          "effect": 0.1855484463720903,
          "site_key": "site_1km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000juhz",
          "effect": 0.21410925073024464,
          "site_key": "site_1km"
        }
      ]
    },
    "site_2km": {
      "components": 2,
      "raw_rows": 236,
      "largest_component_rows": 234,
      "profiles": [
        {
          "component": 0,
          "rows": 234,
          "events": 12,
          "sites": 142,
          "cells": 234,
          "event_mad": 0.11260797828033801,
          "site_mad": 0.11009565495205456,
          "residual_mad": 0.0013474833242631268,
          "site_residual_ratio": 81.70465115942012,
          "event_residual_ratio": 83.56910712933524,
          "site_ratio_low": 19.19384881170189,
          "site_ratio_high": 619669158.2578927,
          "bootstrap_valid": 13,
          "residual_degrees": 81
        },
        {
          "component": 1,
          "rows": 2,
          "events": 2,
          "sites": 1,
          "cells": 2,
          "event_mad": 0.0061584926880290415,
          "site_mad": 0.0,
          "residual_mad": 0.0,
          "site_residual_ratio": "unknown",
          "event_residual_ratio": "unknown",
          "site_ratio_low": "unknown",
          "site_ratio_high": "unknown",
          "bootstrap_valid": 0,
          "residual_degrees": 0
        }
      ],
      "largest_event_effects": [
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "official20110311054624120_30",
          "effect": -0.12405924489217397,
          "site_key": "site_2km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "us10006jbi",
          "effect": 0.5932720992232858,
          "site_key": "site_2km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "us20003k7a",
          "effect": -0.004105409051060719,
          "site_key": "site_2km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "us20007z80",
          "effect": 0.0887921874690323,
          "site_key": "site_2km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usc000f1s0",
          "effect": -0.0033152247653071057,
          "site_key": "site_2km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usc000piqj",
          "effect": -0.03216731926017189,
          "site_key": "site_2km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000h1ys",
          "effect": -0.10115671166850206,
          "site_key": "site_2km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000hrw0",
          "effect": -0.1530264628482326,
          "site_key": "site_2km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000j3mq",
          "effect": 0.42493776116917364,
          "site_key": "site_2km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000j48h",
          "effect": 0.0033152247653071057,
          "site_key": "site_2km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000jqvm",
          "effect": 0.18886367113739755,
          "site_key": "site_2km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000juhz",
          "effect": 0.21742447549555188,
          "site_key": "site_2km"
        }
      ]
    },
    "site_5km": {
      "components": 2,
      "raw_rows": 236,
      "largest_component_rows": 234,
      "profiles": [
        {
          "component": 0,
          "rows": 234,
          "events": 12,
          "sites": 141,
          "cells": 234,
          "event_mad": 0.11260797828033801,
          "site_mad": 0.10739774269886443,
          "residual_mad": 0.009702174547564002,
          "site_residual_ratio": 11.069450685756792,
          "event_residual_ratio": 11.606467985943558,
          "site_ratio_low": "unknown",
          "site_ratio_high": "unknown",
          "bootstrap_valid": 0,
          "residual_degrees": 82
        },
        {
          "component": 1,
          "rows": 2,
          "events": 2,
          "sites": 1,
          "cells": 2,
          "event_mad": 0.0061584926880290415,
          "site_mad": 0.0,
          "residual_mad": 0.0,
          "site_residual_ratio": "unknown",
          "event_residual_ratio": "unknown",
          "site_ratio_low": "unknown",
          "site_ratio_high": "unknown",
          "bootstrap_valid": 0,
          "residual_degrees": 0
        }
      ],
      "largest_event_effects": [
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "official20110311054624120_30",
          "effect": -0.12405924489217397,
          "site_key": "site_5km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "us10006jbi",
          "effect": 0.5932720992232858,
          "site_key": "site_5km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "us20003k7a",
          "effect": -0.004105409051060719,
          "site_key": "site_5km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "us20007z80",
          "effect": 0.0887921874690323,
          "site_key": "site_5km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usc000f1s0",
          "effect": -0.0033152247653071057,
          "site_key": "site_5km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usc000piqj",
          "effect": -0.03216731926017189,
          "site_key": "site_5km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000h1ys",
          "effect": -0.10115671166850206,
          "site_key": "site_5km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000hrw0",
          "effect": -0.1530264628482326,
          "site_key": "site_5km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000j3mq",
          "effect": 0.42493776116917364,
          "site_key": "site_5km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000j48h",
          "effect": 0.0033152247653071057,
          "site_key": "site_5km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000jqvm",
          "effect": 0.18886367113739755,
          "site_key": "site_5km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000juhz",
          "effect": 0.21742447549555188,
          "site_key": "site_5km"
        }
      ]
    }
  },
  "NCEI-native-duration": {
    "physical_site_id": {
      "components": 2,
      "raw_rows": 1070,
      "largest_component_rows": 1069,
      "profiles": [
        {
          "component": 0,
          "rows": 1069,
          "events": 32,
          "sites": 438,
          "cells": 1066,
          "event_mad": 0.1542670519179255,
          "site_mad": 0.12133937521670815,
          "residual_mad": 0.03651489454137648,
          "site_residual_ratio": 3.3230104246696834,
          "event_residual_ratio": 4.224770572543195,
          "site_ratio_low": 4.108823590654277,
          "site_ratio_high": 942.5483304302364,
          "bootstrap_valid": 250,
          "residual_degrees": 597
        },
        {
          "component": 1,
          "rows": 1,
          "events": 1,
          "sites": 1,
          "cells": 1,
          "event_mad": 0.0,
          "site_mad": 0.0,
          "residual_mad": 0.0,
          "site_residual_ratio": "unknown",
          "event_residual_ratio": "unknown",
          "site_ratio_low": "unknown",
          "site_ratio_high": "unknown",
          "bootstrap_valid": 0,
          "residual_degrees": 0
        }
      ],
      "largest_event_effects": [
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "official20100227063411530_30",
          "effect": -0.1167259799123595,
          "site_key": "physical_site_id"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "official20110311054624120_30",
          "effect": -0.11625387140105037,
          "site_key": "physical_site_id"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "us10006jbi",
          "effect": 1.3830781683250497,
          "site_key": "physical_site_id"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "us20003k7a",
          "effect": -0.14834902769472447,
          "site_key": "physical_site_id"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "us2000cmy3",
          "effect": 0.11983290721019343,
          "site_key": "physical_site_id"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usc000f1s0",
          "effect": -0.07253821434953092,
          "site_key": "physical_site_id"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usc000f40j",
          "effect": 0.4150014318847581,
          "site_key": "physical_site_id"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usc000phx5",
          "effect": 0.10509657221264929,
          "site_key": "physical_site_id"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usc000piqj",
          "effect": 3.289853651485551,
          "site_key": "physical_site_id"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp0007jcu",
          "effect": -0.1601850761411265,
          "site_key": "physical_site_id"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp0008mdk",
          "effect": 0.22985184957962354,
          "site_key": "physical_site_id"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000bbpf",
          "effect": 0.007150067517797771,
          "site_key": "physical_site_id"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000bnvq",
          "effect": 0.3756887453399198,
          "site_key": "physical_site_id"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000bnyr",
          "effect": 0.43569006131508026,
          "site_key": "physical_site_id"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000d3mb",
          "effect": 0.5207046028139898,
          "site_key": "physical_site_id"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000d9h1",
          "effect": 1.4680190732730607,
          "site_key": "physical_site_id"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000db93",
          "effect": 0.5382500976907809,
          "site_key": "physical_site_id"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000dt25",
          "effect": 0.3607847061430566,
          "site_key": "physical_site_id"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000eg5g",
          "effect": -0.2156542773170908,
          "site_key": "physical_site_id"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000exfn",
          "effect": -0.18949596503274913,
          "site_key": "physical_site_id"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000f2ab",
          "effect": -0.1223045876846274,
          "site_key": "physical_site_id"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000fjta",
          "effect": -0.09516499071407264,
          "site_key": "physical_site_id"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000gs2d",
          "effect": -0.14598025750895977,
          "site_key": "physical_site_id"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000gsmz",
          "effect": -0.12009505181818497,
          "site_key": "physical_site_id"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000h1ys",
          "effect": -0.11296342993336063,
          "site_key": "physical_site_id"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000h2g9",
          "effect": -0.09813609725831987,
          "site_key": "physical_site_id"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000hrw0",
          "effect": -0.007150067517797771,
          "site_key": "physical_site_id"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000j3mq",
          "effect": 0.6219657675288262,
          "site_key": "physical_site_id"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000j48h",
          "effect": -0.2143304243020267,
          "site_key": "physical_site_id"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000j9nm",
          "effect": 0.46355068539287364,
          "site_key": "physical_site_id"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000jqvm",
          "effect": 0.041432700854469554,
          "site_key": "physical_site_id"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000juhz",
          "effect": -0.025005540938751514,
          "site_key": "physical_site_id"
        }
      ]
    },
    "site_1km": {
      "components": 2,
      "raw_rows": 1070,
      "largest_component_rows": 1069,
      "profiles": [
        {
          "component": 0,
          "rows": 1069,
          "events": 32,
          "sites": 432,
          "cells": 1066,
          "event_mad": 0.1542670519179255,
          "site_mad": 0.12073667251739321,
          "residual_mad": 0.03745561732395608,
          "site_residual_ratio": 3.2234596875852786,
          "event_residual_ratio": 4.118662645008883,
          "site_ratio_low": "unknown",
          "site_ratio_high": "unknown",
          "bootstrap_valid": 0,
          "residual_degrees": 603
        },
        {
          "component": 1,
          "rows": 1,
          "events": 1,
          "sites": 1,
          "cells": 1,
          "event_mad": 0.0,
          "site_mad": 0.0,
          "residual_mad": 0.0,
          "site_residual_ratio": "unknown",
          "event_residual_ratio": "unknown",
          "site_ratio_low": "unknown",
          "site_ratio_high": "unknown",
          "bootstrap_valid": 0,
          "residual_degrees": 0
        }
      ],
      "largest_event_effects": [
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "official20100227063411530_30",
          "effect": -0.1167259799123595,
          "site_key": "site_1km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "official20110311054624120_30",
          "effect": -0.11625387140105037,
          "site_key": "site_1km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "us10006jbi",
          "effect": 1.3830781683250497,
          "site_key": "site_1km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "us20003k7a",
          "effect": -0.14834902769472447,
          "site_key": "site_1km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "us2000cmy3",
          "effect": 0.11983290721019343,
          "site_key": "site_1km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usc000f1s0",
          "effect": -0.07253821434953092,
          "site_key": "site_1km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usc000f40j",
          "effect": 0.4150014318847581,
          "site_key": "site_1km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usc000phx5",
          "effect": 0.10509657221264929,
          "site_key": "site_1km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usc000piqj",
          "effect": 3.289853651485551,
          "site_key": "site_1km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp0007jcu",
          "effect": -0.1601850761411265,
          "site_key": "site_1km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp0008mdk",
          "effect": 0.22985184957962354,
          "site_key": "site_1km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000bbpf",
          "effect": 0.007150067517797771,
          "site_key": "site_1km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000bnvq",
          "effect": 0.3756887453399198,
          "site_key": "site_1km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000bnyr",
          "effect": 0.43569006131508026,
          "site_key": "site_1km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000d3mb",
          "effect": 0.5207046028139898,
          "site_key": "site_1km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000d9h1",
          "effect": 1.4680190732730607,
          "site_key": "site_1km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000db93",
          "effect": 0.5382500976907809,
          "site_key": "site_1km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000dt25",
          "effect": 0.3607847061430566,
          "site_key": "site_1km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000eg5g",
          "effect": -0.2156542773170908,
          "site_key": "site_1km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000exfn",
          "effect": -0.18949596503274913,
          "site_key": "site_1km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000f2ab",
          "effect": -0.11833779030068708,
          "site_key": "site_1km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000fjta",
          "effect": -0.09516499071407264,
          "site_key": "site_1km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000gs2d",
          "effect": -0.14598025750895977,
          "site_key": "site_1km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000gsmz",
          "effect": -0.12009505181818497,
          "site_key": "site_1km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000h1ys",
          "effect": -0.11296342993336063,
          "site_key": "site_1km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000h2g9",
          "effect": -0.09813609725831987,
          "site_key": "site_1km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000hrw0",
          "effect": -0.007150067517797771,
          "site_key": "site_1km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000j3mq",
          "effect": 0.6219657675288262,
          "site_key": "site_1km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000j48h",
          "effect": -0.2143304243020267,
          "site_key": "site_1km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000j9nm",
          "effect": 0.46355068539287364,
          "site_key": "site_1km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000jqvm",
          "effect": 0.041432700854469554,
          "site_key": "site_1km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000juhz",
          "effect": -0.025005540938751514,
          "site_key": "site_1km"
        }
      ]
    },
    "site_2km": {
      "components": 2,
      "raw_rows": 1070,
      "largest_component_rows": 1069,
      "profiles": [
        {
          "component": 0,
          "rows": 1069,
          "events": 32,
          "sites": 431,
          "cells": 1066,
          "event_mad": 0.1597436798511637,
          "site_mad": 0.12091430737305918,
          "residual_mad": 0.03795987682088084,
          "site_residual_ratio": 3.185318749679057,
          "event_residual_ratio": 4.208224399803438,
          "site_ratio_low": 3.914672003303929,
          "site_ratio_high": 304.2729623931266,
          "bootstrap_valid": 261,
          "residual_degrees": 604
        },
        {
          "component": 1,
          "rows": 1,
          "events": 1,
          "sites": 1,
          "cells": 1,
          "event_mad": 0.0,
          "site_mad": 0.0,
          "residual_mad": 0.0,
          "site_residual_ratio": "unknown",
          "event_residual_ratio": "unknown",
          "site_ratio_low": "unknown",
          "site_ratio_high": "unknown",
          "bootstrap_valid": 0,
          "residual_degrees": 0
        }
      ],
      "largest_event_effects": [
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "official20100227063411530_30",
          "effect": -0.11464643145898264,
          "site_key": "site_2km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "official20110311054624120_30",
          "effect": -0.1141743229476735,
          "site_key": "site_2km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "us10006jbi",
          "effect": 1.3851577167784261,
          "site_key": "site_2km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "us20003k7a",
          "effect": -0.14626947924134756,
          "site_key": "site_2km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "us2000cmy3",
          "effect": 0.1219124556635703,
          "site_key": "site_2km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usc000f1s0",
          "effect": -0.07045866589615406,
          "site_key": "site_2km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usc000f40j",
          "effect": 0.41708098033813484,
          "site_key": "site_2km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usc000phx5",
          "effect": 0.10717612066602615,
          "site_key": "site_2km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usc000piqj",
          "effect": 3.291933199938928,
          "site_key": "site_2km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp0007jcu",
          "effect": -0.1581055276877496,
          "site_key": "site_2km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp0008mdk",
          "effect": 0.23193139803300045,
          "site_key": "site_2km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000bbpf",
          "effect": 0.0050705190644209095,
          "site_key": "site_2km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000bnvq",
          "effect": 0.3777682937932966,
          "site_key": "site_2km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000bnyr",
          "effect": 0.43776960976845697,
          "site_key": "site_2km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000d3mb",
          "effect": 0.5227841512673672,
          "site_key": "site_2km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000d9h1",
          "effect": 1.4690588474717698,
          "site_key": "site_2km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000db93",
          "effect": 0.5403296461441583,
          "site_key": "site_2km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000dt25",
          "effect": 0.36286425459643334,
          "site_key": "site_2km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000eg5g",
          "effect": -0.2135747288637139,
          "site_key": "site_2km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000exfn",
          "effect": -0.18741641657937222,
          "site_key": "site_2km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000f2ab",
          "effect": -0.11625824184731025,
          "site_key": "site_2km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000fjta",
          "effect": -0.09308544226069579,
          "site_key": "site_2km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000gs2d",
          "effect": -0.14805980607425168,
          "site_key": "site_2km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000gsmz",
          "effect": -0.1613818320145778,
          "site_key": "site_2km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000h1ys",
          "effect": -0.1108838814799838,
          "site_key": "site_2km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000h2g9",
          "effect": -0.09605654880494299,
          "site_key": "site_2km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000hrw0",
          "effect": -0.0050705190644209095,
          "site_key": "site_2km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000j3mq",
          "effect": 0.6240453159822036,
          "site_key": "site_2km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000j48h",
          "effect": -0.2122508758486498,
          "site_key": "site_2km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000j9nm",
          "effect": 0.46563023384625035,
          "site_key": "site_2km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000jqvm",
          "effect": 0.043512249307846425,
          "site_key": "site_2km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000juhz",
          "effect": -0.02292599248537464,
          "site_key": "site_2km"
        }
      ]
    },
    "site_5km": {
      "components": 2,
      "raw_rows": 1070,
      "largest_component_rows": 1069,
      "profiles": [
        {
          "component": 0,
          "rows": 1069,
          "events": 32,
          "sites": 429,
          "cells": 1066,
          "event_mad": 0.1597436798511637,
          "site_mad": 0.12014188989630542,
          "residual_mad": 0.03849251631933512,
          "site_residual_ratio": 3.12117526689096,
          "event_residual_ratio": 4.149993170774421,
          "site_ratio_low": "unknown",
          "site_ratio_high": "unknown",
          "bootstrap_valid": 0,
          "residual_degrees": 606
        },
        {
          "component": 1,
          "rows": 1,
          "events": 1,
          "sites": 1,
          "cells": 1,
          "event_mad": 0.0,
          "site_mad": 0.0,
          "residual_mad": 0.0,
          "site_residual_ratio": "unknown",
          "event_residual_ratio": "unknown",
          "site_ratio_low": "unknown",
          "site_ratio_high": "unknown",
          "bootstrap_valid": 0,
          "residual_degrees": 0
        }
      ],
      "largest_event_effects": [
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "official20100227063411530_30",
          "effect": -0.11464643145898264,
          "site_key": "site_5km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "official20110311054624120_30",
          "effect": -0.1141743229476735,
          "site_key": "site_5km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "us10006jbi",
          "effect": 1.3851577167784261,
          "site_key": "site_5km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "us20003k7a",
          "effect": -0.14626947924134756,
          "site_key": "site_5km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "us2000cmy3",
          "effect": 0.1219124556635703,
          "site_key": "site_5km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usc000f1s0",
          "effect": -0.07045866589615406,
          "site_key": "site_5km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usc000f40j",
          "effect": 0.41708098033813484,
          "site_key": "site_5km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usc000phx5",
          "effect": 0.10717612066602615,
          "site_key": "site_5km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usc000piqj",
          "effect": 3.291933199938928,
          "site_key": "site_5km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp0007jcu",
          "effect": -0.1581055276877496,
          "site_key": "site_5km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp0008mdk",
          "effect": 0.23193139803300045,
          "site_key": "site_5km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000bbpf",
          "effect": 0.0050705190644209095,
          "site_key": "site_5km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000bnvq",
          "effect": 0.3777682937932966,
          "site_key": "site_5km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000bnyr",
          "effect": 0.43776960976845697,
          "site_key": "site_5km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000d3mb",
          "effect": 0.5105284875739867,
          "site_key": "site_5km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000d9h1",
          "effect": 1.4690588474717698,
          "site_key": "site_5km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000db93",
          "effect": 0.5403296461441583,
          "site_key": "site_5km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000dt25",
          "effect": 0.36286425459643334,
          "site_key": "site_5km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000eg5g",
          "effect": -0.2135747288637139,
          "site_key": "site_5km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000exfn",
          "effect": -0.18741641657937222,
          "site_key": "site_5km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000f2ab",
          "effect": -0.11625824184731025,
          "site_key": "site_5km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000fjta",
          "effect": -0.09308544226069579,
          "site_key": "site_5km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000gs2d",
          "effect": -0.14805980607425168,
          "site_key": "site_5km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000gsmz",
          "effect": -0.1613818320145778,
          "site_key": "site_5km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000h1ys",
          "effect": -0.1108838814799838,
          "site_key": "site_5km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000h2g9",
          "effect": -0.09605654880494299,
          "site_key": "site_5km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000hrw0",
          "effect": -0.0050705190644209095,
          "site_key": "site_5km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000j3mq",
          "effect": 0.6240453159822036,
          "site_key": "site_5km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000j48h",
          "effect": -0.2122508758486498,
          "site_key": "site_5km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000j9nm",
          "effect": 0.46563023384625035,
          "site_key": "site_5km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000jqvm",
          "effect": 0.043512249307846425,
          "site_key": "site_5km"
        },
        {
          "component": 0,
          "component_relative": true,
          "kind": "event",
          "id": "usp000juhz",
          "effect": -0.02292599248537464,
          "site_key": "site_5km"
        }
      ]
    }
  }
}
```
