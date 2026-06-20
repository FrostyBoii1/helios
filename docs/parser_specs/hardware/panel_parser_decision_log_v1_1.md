# Hardware Parser Panel Decision Log v1.1

## panel_decision_separate_panel_parser

Panel parsing remains separate from the inverter/battery/meter parser package because panels require wattage/quantity/system-size derivation logic.

## panel_decision_model_null_for_brand_only

Brand-only source values must not be placed into `model`.

`model` must only contain an actual catalogue model. Raw values such as `Longi` are preserved through `display_name` and `source_fragment`, with `model: null`.

## panel_decision_wattage_is_primary_disambiguator

Wattage is the primary disambiguator for panel model mapping.

## panel_decision_system_size_derivation

Future NAS/proposal parser may derive panel wattage from system size and existing panel quantity:

```text
system_size_kw / panel_quantity * 1000 = derived_panel_wattage_w
```

## panel_decision_wattage_tolerance

Derived wattage may match catalogue wattage within +/-2W.

## panel_decision_strict_ignore_values

Only these values are strict ignore values:

```text
-
/
N/A
na
```

## panel_decision_preserve_ambiguous_non_panel_values

Values such as `AE 440 or TW`, `TO AE PANELS`, `3 x tigo Optimisers`, battery references, and install notes must not become panel aliases, but must be preserved/routed if attached to a job.

## panel_decision_longi_415

`Longi 415`, `Longi 415W`, `Longi 415 `, and `LONGI 415` resolve to `415W LONGi Solar / LR5-54HPH-415M`.

## panel_decision_longi_440_tw_user_approved

`Longi 440/TW` resolves to `440W LONGi Solar / LR5-54HTH-440M` because user approved this mapping despite the `/TW` suffix.

## panel_decision_longi_475

`Longi 475` and `LONGI 475` resolve to `475W LONGi Solar / LR7-54HTH-475M`.

## panel_decision_ae_meteor_display_split

`AE Solar 440 Full Black` / `AE Black` and `AE Solar Meteor 440` share the supplied model value but remain separate display entries.

## panel_decision_case_sensitive_jinko_440

`Jinko 440` and `JINKO 440` are case-sensitive and resolve to different supplied model values:

```text
Jinko 440 -> JKM440N-54HL4
JINKO 440 -> JKM440N-54HL4R-B
```

## panel_decision_suntech_415_two_models

`Suntech 415` resolves to a shared display label, but model precision requires review if exact model matters.

Supplied model values:

```text
STP415S-78H/Vfh
Ultra V mini STP415S-C54/Umhm
```

## panel_decision_rec_460_two_models

`REC 460's` resolves to a shared display label, but model precision requires review if exact model matters.

Supplied model values:

```text
REC460AA Pure-RX
REC440AA 72
```

## panel_decision_tongwei_440_465_model_overlap

TW 440 and TW 465 share the supplied model reference `TWMNH-48HD465`, but retain different display wattages.

## panel_decision_conflict_proposal_wins

Proposal/NAS data wins over sheet data when they conflict. Original sheet evidence must still be preserved.


## panel_decision_v1_1_confidence_category_split

Decision: Confidence describes parsing certainty only.

Reason: Routed destination describes the category/path for non-panel values. Do not use category values such as `accessory_hardware` as confidence levels.

## panel_decision_v1_1_model_options_for_ambiguous_models

Decision: Ambiguous Suntech/REC entries use `model: null` plus `model_options`.

Reason: `model` must contain a single actual catalogue model only.

## panel_decision_v1_1_tw_brand_only_review

Decision: Standalone `TW` is brand evidence only and should not resolve to a Tongwei model unless wattage/system-size evidence supports it.

Reason: `TW` is too short and risky as a standalone alias.

## panel_decision_v1_1_wattage_only_preserve

Decision: Wattage-only values such as `440W panels` preserve wattage but do not infer brand/model.

Reason: Wattage alone is not enough to determine the panel manufacturer/model.


## panel_decision_v1_2_version_consistency_cleanup

Decision: Normalize fixture parser rule version references to `panel_rules_v1_1`.

Reason: The runtime rules file is versioned as `panel_rules_v1_1`; fixture outputs must reference the same rule version to avoid implementation confusion.

No catalogue mappings or parser behavior rules were changed.
