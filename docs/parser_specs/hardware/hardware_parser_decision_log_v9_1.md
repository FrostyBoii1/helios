# Hardware Parser Decision Log v9.1

This log records parser decisions that are not obvious from aliases alone. Owner-approved manual corrections belong here, not hidden inside code.

| Rule ID | Match / Trigger | Action | Reason | Confidence |
|---|---|---|---|---|
| ignore_used_solax_10kw | `Used 10kw Solax` | Ignore; output no hardware | Existing/used equipment, not newly installed hardware. | manual_correction |
| corr_solis_gr3p5k_au | `S5-GR3P5K` | Output `S5-GR3P5K-AU` | Non-AU and AU text are treated as the same actual hardware for this CRM parser. | manual_correction |
| corr_sma_10kw | `SMA 10kW`, `Self supplied SMA 10kW` | Output `STP10.0-3AV-40` | Manual source customer-file lookup confirmed actual SMA model. | manual_correction |
| corr_solax_hybrid_normal | `Solax 5kw Hybrid/5kw normal` | Output `X1-HYBRID-5.0-D-G4` and `X1-BOOST-5K-G4` | Bundle contains one hybrid and one normal SolaX inverter. | manual_correction |
| corr_fronius_reuse | `Reusing Fronius Inverter` | Output `SYMO-6.0-3-M` | Manual source customer-file lookup confirmed reused Fronius model. | manual_correction |
| corr_customer_supplied | `Customer supplied/install only` | Output `SH10RT` | Manual source customer-file lookup confirmed actual hardware. | manual_correction |
| corr_solax_15_20 | `1 x 15kw 3p/1 x 20kw 3p` | Output `X3-PRO-15K-G2` and `X3-PRO-20K-G2` | Bundle contains two SolaX three-phase inverters. | manual_correction |
| note_ct | Any CT/ct meter fragment | `site_notes.ct`; display in Job Internal Notes if needed | CT references are site/config notes, not hardware labels for v1. | exact |
| note_export_limit | `2kw export`, `3kw export`, `5kw export`, etc. | `site_notes.export_limit`; display in Job Internal Notes if needed | Export limit is a site/config note, not a hardware model. | exact |
| note_underground | `underground` | `site_notes.underground`; display in Job Internal Notes if needed | Installation condition, not hardware. | exact |
| note_wifi_comms | WiFi/comms/logger/stick wording | `site_notes.comms`; display in Job Internal Notes if needed | Communication accessories are not classified as hardware for v1. | exact |
| unmatched_raw_hardware | Hardware phrase cannot be confidently resolved | Put exact relevant phrase into editable hardware field; set `unconfirmed_raw_text`; preserve source fragment | Hardware fields are editable textboxes, not dropdowns. Preserve source value rather than guessing. | unconfirmed_raw_text |
| source_examples_not_aliases | Any `source_examples` entry | Do not match as alias unless promoted into `exact_aliases` or `loose_aliases` | Full workbook strings often contain bundles, meter, batteries, and notes. | n/a |
| workflow_boundary | Parsed hardware/site notes | Do not create labels, tasks, approval states, or decommissioning decisions | Workflow automation belongs in separate rules, not hardware parser. | n/a |
| manual_edit_protection | Existing staff-edited hardware field | Do not overwrite without explicit confirmation | Staff corrections are more trusted than parser-owned seeded values. | n/a |
| parser_version_storage | Every parser run | Store `hardware_parser_rules_v9_1` on parsed job | Required for debugging old imports. | n/a |


---

# v9.1 Added Decisions

## D-v9.1-001 — Source Examples Are Not Aliases

**Decision:** `source_examples` are evidence only and must not be used by the runtime alias matcher.

**Reason:** Full workbook strings often contain bundles. Treating them as aliases would collapse inverter, battery, meter, and note information into one incorrect hardware match.

## D-v9.1-002 — Ambiguous Hardware Preserves Raw Text

**Decision:** Ambiguous fragments such as `Solax 5kw` are preserved in the editable inverter field as raw text with `confidence: unconfirmed_raw_text`.

**Reason:** `Solax 5kw` could mean `X1-BOOST-5K-G4`, `X1-SMT-5K-G2`, or `X1-HYBRID-5.0-D-G4`. Guessing would silently corrupt CRM hardware data.

## D-v9.1-003 — Customer Supplied / Install Only Correction

**Decision:** `Customer supplied/install only` maps to `SH10RT` only because this was manually confirmed from source customer files.

**Reason:** This is not a general parser inference. It is an owner-approved business correction.

## D-v9.1-004 — Reusing Fronius Correction

**Decision:** `Reusing Fronius Inverter` maps to `SYMO-6.0-3-M` only because this was manually confirmed from source customer files.

**Reason:** Reusing/existing hardware would normally be a guard phrase, but this specific text has a confirmed correction.

## D-v9.1-005 — Used Solax Ignore

**Decision:** `Used 10kw Solax` is ignored.

**Reason:** It refers to existing/used equipment, not newly installed hardware for CRM hardware seeding.

## D-v9.1-006 — Hardware Parser Does Not Create Workflow Labels

**Decision:** The hardware parser must not create approval/decommission/admin/task labels.

**Reason:** Hardware extraction and workflow automation are separate responsibilities. Workflow rules may consume parser output later.

## D-v9.1-007 — v1 YAML Runtime Scope

**Decision:** v1 may use YAML as the runtime source. Do not build the full hardware catalogue database/UI unless separately scoped.

**Reason:** The parser can be implemented safely first without overbuilding the CRM hardware catalogue management system.


## v9 Validation Cleanup Decisions

Scope: validation-cleanup pass only. Parser implementation was not performed.

### Non-obvious resolutions

- `alpha_ess_smile_m5_inverter`: `ALPHA ESS M5 5KW INVERTER AND 15KW BATTERY` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `alpha_ess_smile_m5_s_inv`: `Alpha ESS Smile M5/15kw Alpha Stack` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `alpha_ess_smile_m5_s_inv`: `Alpha ESS Smile M5/30kw Alpha Stack` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `alpha_ess_smile_s5`: `Alpha ESS 10.1/Smile 5` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `alpha_ess_smile_s5`: `Alpha ESS SMILE-S5/SMILE-BAT-13.3P` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `goodwe_gw10kau_dt`: `GoodWe GW10KAU-DT/3 phase CT` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `neovolt_bw_inv_sph5k`: `Neovolt BW-INV-SPH5K +Neovolt BW-BAT-9.6P` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `s5_gr1p10k`: `Solis S5-GR1P10K - smart meter` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `s5_gr1p10k`: `Solis 10kw with meter` removed from `loose_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `s5_gr1p5k`: `Solis 5kw and Vast 10kw and 21.6kw - install Vast and batteries only - Solis 5kw was installed` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `s5_gr1p5k`: `Solis S5-GR1P5K - Alpha 20W battery` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `s5_gr1p6k`: `Solis S5-GR1P6K - 3kw export` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `s5_gr3p10k_au`: `10kw Solis 3P with meter` removed from `loose_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `saj_h2_10k_s3`: `SAJ H2-10K-S3 Inverter - SAJ B2-5.0-HV1 - 30kw hr Battery` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `saj_h2_15k_t3`: `SAJ 15KW 3P INVERTER AND 25KW BATTERIES` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `saj_h2_20k_t3_au`: `SAJ 20KW 3 PHASE INVERTER - 40KW BATTERY STORAGE - 3phase` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `saj_h2_20k_t3_au`: `SAJ 20KW AND 30KW BATTERY` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `saj_h2_25k_t3_au`: `SAJ 25KW INVERTER AND 30KW STORAGE` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `saj_h2_25k_t3_au`: `SAJ 25KW INVERTER AND 40KW STORAGE` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `sh10rs`: `SH10RS - 12.8KW BATTERY` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `sh10rt`: `Sungrow SBR224 · 22.4kWh - existing SH10RT` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `sigenergy_sigenstor_inverter`: `Sigenergy SigenStor EC 30.0 TP +Sigenergy SigenStor-30T-48` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `sigenergy_sigenstor_inverter`: `Sigenergy SigenStor-10S-24 -24.18KWh` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `sigenergy_sigenstor_inverter`: `Sigenergy SigenStor-12S-48 (AS4777-2 2020) · 48.36kWh` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `sigenergy_sigenstor_inverter`: `Sigenergy SigenStor-30T-48 · 48.36kWh` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `sigenergy_sigenstor_inverter`: `Sigenergy SigenStor-30T-48 · 48.36kWh AND 10KW SINGLE PHASE - INCLUDING GATEWAYS` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `swatten_all_in_one_19_2kwh_inverter`: `Swatten All In One 19.2 with 5kw 3 phase Hybrid Inverter` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `swatten_all_in_one_19_2kwh_inverter`: `Swatten All In One 19.2 with 5kw Hybrid Inverter` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `x1_boost_5k_g4`: `Solax 5kw - Alpha ESS SMILE-M-BAT-5P IV · 20kWh - all black rail` removed from `loose_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `x1_smt_10k_g2`: `Solax 10kw Hybrid and 21.6kwhr battery Solax` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `x1_vast_10k`: `10KW VAST SOLAX AND 28.8KW BATTERY` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `x1_vast_10k`: `Solax Vast 10kw and 28.8kw battery Solax` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `x1_vast_10k`: `Solis 5kw and Vast 10kw and 21.6kw - install Vast and batteries only - Solis 5kw was installed` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `x1_vast_10k`: `Vast 10kw and t-bat21.6 with base` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `x3_ultra_20k`: `Solax Ultra 20kw and Solax 28.8kw Battery` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `ecactus_10kwh_battery`: `ECACTUS 10KW BATTERY` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `lg_resu_10kwh_low_voltage`: `LGRESU Low voltage 10kw hr` removed from `loose_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `neovolt_bw_bat_10_1p`: `BW 5SPBK Inverter Neovolt - Neovolt BW-BAT-9.6P · 9.6kWh - now a 10.1 BATTERY` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `neovolt_bw_bat_10_1p`: `Neovolt BW-BAT - 10.1kw hr` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `neovolt_bw_bat_10_1p`: `Neovolt BW-BAT-10.1/AC COUPLE 5KW HYBRID NEOVOLT` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `neovolt_bw_bat_10_1p`: `Neovolt BW-BAT-10.1P · 10.1kWh` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `neovolt_bw_bat_10_1p`: `Neovolt BW-BAT-10.1P · 10.1kWh - USE THE 5KW DC HYBRID INVERTER ONLY` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `neovolt_bw_bat_10_1p`: `Neovolt BW-BAT-10.1kWh` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `neovolt_bw_bat_10_1p`: `Neovolt BW-BAT-10.1kw hr` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `neovolt_bw_bat_9_6p`: `5KW Hybrid Neovolt and 9.6kw Battery Neovolt` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `neovolt_bw_bat_9_6p`: `5kw Hybrid Neovolt - Neovolt BW-BAT-9.6P · 9.6kWh` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `neovolt_bw_bat_9_6p`: `BW 5SPBK Inverter Neovolt - Neovolt BW-BAT-9.6P · 9.6kWh - now a 10.1 BATTERY` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `neovolt_bw_bat_9_6p`: `NEOVOLT BW-BAT-9.6P II · 19.2kWh` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `neovolt_bw_bat_9_6p`: `Neovolt BW-BAT-9.6P · 9.6kWh` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `neovolt_bw_bat_9_6p`: `Neovolt BW-BAT-9.6P · 9.6kWh - ALREADY HAVE` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `neovolt_bw_bat_9_6p`: `Neovolt BW-BAT-9.6P/ac couple` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `neovolt_bw_bat_9_6p`: `Neovolt BW-INV-SPH5K +Neovolt BW-BAT-9.6P` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `neovolt_bw_bat_9_6p_ii`: `NEOVOLT BW-BAT-9.6P II · 19.2kWh` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `saj_b2_20_0_hv1`: `SAJ B2-20.0-HV1 · 20kWh` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `saj_b2_25_0_hv1`: `SAJ 15KW 3P INVERTER AND 25KW BATTERIES` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `saj_b2_5_0_hv1`: `SAJ H2-10K-S3 Inverter - SAJ B2-5.0-HV1 - 30kw hr Battery` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `sbr096`: `5KW Hybrid Neovolt and 9.6kw Battery Neovolt` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `sbr096`: `BW 5SPBK Inverter Neovolt - Neovolt BW-BAT-9.6P · 9.6kWh - now a 10.1 BATTERY` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `sbr128`: `SH10RS - 12.8KW BATTERY` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `sbr128`: `Sungrow SBR128 · 12.8kWh` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `sbr128`: `Sungrow SBR128 · 12.8kWh - second stack` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `sbr160`: `Sungrow SBR160 · 16kWh` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `sbr192`: `NEOVOLT BW-BAT-9.6P II · 19.2kWh` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `sbr192`: `Sungrow SBR192 · 19.2kWh` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `sbr960`: `SBR960 Battery and Base` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `smile_bat_10_1p`: `10.1kWh Alpha-ESS (Smile5 10.1kWh)` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `smile_bat_10_1p`: `ALPHA ESS 10KW BATTERY` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `smile_bat_10_1p`: `Alpha ESS SMILE-BAT-10.1P · 10.08kWh` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `smile_bat_10_1p`: `Alpha ESS SMILE-G3-BAT-10.1P · 10.1kWh extension batt` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `smile_bat_10_1p`: `Alpha-ESS (Smile5 10.1kWh) battery` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `smile_bat_13_3p`: `Alpha ESS 13.3P Battery` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `smile_bat_13_3p`: `Alpha ESS SMILE-BAT-13.3P - 13.34KWh` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `smile_bat_13_3p`: `Alpha ESS SMILE-BAT-13.3P - 13.34KWh - send meter 3 phase` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `smile_bat_13_3p`: `Alpha ESS SMILE-BAT-13.3P 13.34kWh` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `smile_bat_13_3p`: `Alpha ESS SMILE-BAT-13.3P · 13.34kWh` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `smile_bat_13_3p`: `Alpha ESS SMILE-BAT-13.3P · 13.34kWh - take meter` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `smile_bat_13_3p`: `Alpha ESS SMILE-BAT-13.3P · 13.3kWh` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `smile_bat_13_3p`: `Alpha ESS SMILE-S5/SMILE-BAT-13.3P` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `smile_bat_13_9p`: `Alpha 13.9 and 5kw M5` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `smile_bat_13_9p`: `Alpha ESS SMILE-BAT-13.9P · 13.3kWh` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `smile_bat_13_9p`: `Alpha ESS SMILE-M-BAT-13.9P · 13.99kWh` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `smile_g3_bat_10_1p`: `Alpha ESS SMILE-G3-BAT-10.1P - chint meter` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `smile_g3_bat_10_1p`: `Alpha ESS SMILE-G3-BAT-10.1P · 10.1kWh extension batt` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `smile_m_bat_5p`: `ALPHA ESS M5 5KW INVERTER AND 15KW BATTERY` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `smile_m_bat_5p_iii`: `Alpha ESS SMILE-M-BAT-5P III - 15KW BATTERY` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `smile_m_bat_5p_iii`: `Alpha ESS SMILE-M-BAT-5P III · 15kWh` removed from `loose_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `smile_m_bat_5p_iv`: `Alpha ESS SMILE-M-BAT-5P IV - 20KW BATTERY` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `smile_m_bat_5p_iv`: `Alpha ESS SMILE-M-BAT-5P IV · 20kWh` removed from `loose_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `smile_m_bat_5p_iv`: `Solax 5kw - Alpha ESS SMILE-M-BAT-5P IV · 20kWh - all black rail` removed from `loose_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `smile_m_bat_5p_v`: `Alpha ESS SMILE-M-BAT-5P VI - 30KW BATTERY` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `smile_m_bat_5p_v`: `Alpha ESS SMILE-M-BAT-5P V · 25kWh` removed from `loose_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `smile_m_bat_5p_v`: `Alpha ESS SMILE-M-BAT-5P VI · 30kWh` removed from `loose_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `sigenergy_sigenstor_battery`: `Sigenergy SigenStor EC 30.0 TP +Sigenergy SigenStor-30T-48` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `sigenergy_sigenstor_battery`: `Sigenergy SigenStor-10S-24 -24.18KWh` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `sigenergy_sigenstor_battery`: `Sigenergy SigenStor-12S-48 (AS4777-2 2020) · 48.36kWh` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `sigenergy_sigenstor_battery`: `Sigenergy SigenStor-25T-48 · 48.36kWh/Gateway` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `sigenergy_sigenstor_battery`: `Sigenergy SigenStor-30T-48 · 48.36kWh` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `sigenergy_sigenstor_battery`: `Sigenergy SigenStor-30T-48 · 48.36kWh AND 10KW SINGLE PHASE - INCLUDING GATEWAYS` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `solax_t_bat_hs21_6`: `Vast 10kw and t-bat21.6 with base` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `solax_t_bat_hs28_8`: `10KW VAST SOLAX AND 28.8KW BATTERY` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `solax_t_bat_hs28_8`: `SolaX Power VAST 10k+ SolaX Power T-BAT HS28.8 · 29.4kWh` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `solax_t_bat_hs28_8`: `Solax Ultra 20kw and Solax 28.8kw Battery` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `solax_t_bat_hs28_8`: `Solax Vast 10kw and 28.8kw battery Solax` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `solax_t_bat_hs32_4`: `UPGRADE TO SOLAX 20 AND 32KW HRS` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `solax_t_bat_hs43_2`: `30kw Ultra Solax and T-BAT HS43.2kw battery` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `solax_t_bat_hs43_2`: `Solax 20kw Inverter and 43.2kw Solax Battery` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `solax_t_bat_hs43_2`: `VAST 10K INVERTER AND T-BAT HS43.2 BATTERY - 12 batteries of 3.6kw hr` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `solax_t_bat_hs43_2`: `VAST 10K INVERTER AND T-BAT HS43.2 BATTERY - 12 batteries of 3.6kw hrs` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `swatten_all_in_one_19_2kwh_battery`: `SWATTEN 19.2WKW BATTERY` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `swatten_all_in_one_19_2kwh_battery`: `Swatten All In One 19.2 with 5kw 3 phase Hybrid Inverter` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `swatten_all_in_one_19_2kwh_battery`: `Swatten All In One 19.2 with 5kw Hybrid Inverter` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `swatten_all_in_one_19_2kwh_battery`: `Swatten All in One 19.2kw batt` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `t_bat_hs43_2`: `30kw Ultra Solax and T-BAT HS43.2kw battery` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `t_bat_hs43_2`: `VAST 10K INVERTER AND T-BAT HS43.2 BATTERY - 12 batteries of 3.6kw hr` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `t_bat_hs43_2`: `VAST 10K INVERTER AND T-BAT HS43.2 BATTERY - 12 batteries of 3.6kw hrs` removed from `exact_aliases` and retained as `source_examples` only. Reason: bundle/source/note string moved to source_examples.
- `sg10_0rs`: `Sungrow (SG10.0RS-ADA)` removed from `exact_aliases` and retained as `source_examples` only. Reason: removed from direct matcher due alias collision.
- `sg10_0rs`: `Sungrow SG10.0RS-ADA` removed from `exact_aliases` and retained as `source_examples` only. Reason: removed from direct matcher due alias collision.
- `sg5_0rs`: `Sungrow 5kw - SG5.0RS-ADA` removed from `exact_aliases` and retained as `source_examples` only. Reason: removed from direct matcher due alias collision.
- `swatten_all_in_one_19_2kwh_inverter`: `SWATTEN 19.2 ALL IN ONE 5KW` removed from `exact_aliases` and retained as `source_examples` only. Reason: removed from direct matcher due alias collision.
- `swatten_all_in_one_19_2kwh_battery`: `SWATTEN 19.2 ALL IN ONE 5KW` removed from `exact_aliases` and retained as `source_examples` only. Reason: removed from direct matcher due alias collision.
- `swatten_all_in_one_19_2kwh_inverter`: `Swatten 19.2 ALL IN ONE` removed from `exact_aliases` and retained as `source_examples` only. Reason: removed from direct matcher due alias collision.
- `swatten_all_in_one_19_2kwh_battery`: `Swatten 19.2 ALL IN ONE` removed from `exact_aliases` and retained as `source_examples` only. Reason: removed from direct matcher due alias collision.
- `swatten_all_in_one_19_2kwh_inverter`: `Swatten 19.2 ALL IN ONE - 3 phase` removed from `exact_aliases` and retained as `source_examples` only. Reason: removed from direct matcher due alias collision.
- `swatten_all_in_one_19_2kwh_battery`: `Swatten 19.2 ALL IN ONE - 3 phase` removed from `exact_aliases` and retained as `source_examples` only. Reason: removed from direct matcher due alias collision.
- `swatten_all_in_one_19_2kwh_inverter`: `Swatten 19.2kw All In One` removed from `exact_aliases` and retained as `source_examples` only. Reason: removed from direct matcher due alias collision.
- `swatten_all_in_one_19_2kwh_battery`: `Swatten 19.2kw All In One` removed from `exact_aliases` and retained as `source_examples` only. Reason: removed from direct matcher due alias collision.
- `tesla_powerwall_3_inverter`: `TESLA POWERWALL 3` removed from `loose_aliases` and retained as `source_examples` only. Reason: removed from direct matcher due alias collision.
- `tesla_powerwall_3_battery`: `TESLA POWERWALL 3` removed from `loose_aliases` and retained as `source_examples` only. Reason: removed from direct matcher due alias collision.
- `goodwe_10kw`: `GOODWE 10KW` removed from `exact_aliases` and retained as `source_examples` only. Reason: ambiguous capacity-only alias moved out of direct matcher.
- `s5_gr1p5k`: `Solis 5kw` removed from `loose_aliases` and retained as `source_examples` only. Reason: ambiguous capacity-only alias moved out of direct matcher.
- `sg5_0rs`: `Sungrow 5kw` removed from `loose_aliases` and retained as `source_examples` only. Reason: ambiguous capacity-only alias moved out of direct matcher.
- `x1_boost_5k_g4`: `SolaX 5kW` removed from `loose_aliases` and retained as `source_examples` only. Reason: ambiguous capacity-only alias moved out of direct matcher.
- `x1_smt_10k_g2`: `SolaX 10kW` removed from `loose_aliases` and retained as `source_examples` only. Reason: ambiguous capacity-only alias moved out of direct matcher.

### Explicit safeguards added

- Capacity-only/vague aliases such as `Solax 5kw`, `Solax 10kw`, `Goodwe 10kw`, `Sungrow 5kw`, and `Solis 5kw` are ambiguous raw-text examples, not direct model aliases.
- Bundle/source strings with batteries, meters, CT, export, WiFi/comms, installation notes, or quantities are evidence/test inputs only unless promoted into a clean exact/loose alias.
- Runtime validation must fail if exact/loose alias collisions return.

### v9 Source Example Deduplication
- `sg10_0rs`: removed `Sungrow (SG10.0RS-ADA)` from `source_examples` because the same normalized text remains an active direct alias. This prevents source_examples from being loaded as aliases during validation.
- `sg10_0rs`: removed `Sungrow SG10.0RS-ADA` from `source_examples` because the same normalized text remains an active direct alias. This prevents source_examples from being loaded as aliases during validation.
- `sg5_0rs`: removed `Sungrow 5kw - SG5.0RS-ADA` from `source_examples` because the same normalized text remains an active direct alias. This prevents source_examples from being loaded as aliases during validation.
- `x1_boost_6k_g4`: removed `X1-BOOST-6K-G4` from `source_examples` because the same normalized text remains an active direct alias. This prevents source_examples from being loaded as aliases during validation.
- `x1_smt_10k_g2`: removed `X1-SMT-10K-G2` from `source_examples` because the same normalized text remains an active direct alias. This prevents source_examples from being loaded as aliases during validation.
