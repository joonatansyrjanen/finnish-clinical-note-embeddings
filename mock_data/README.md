# Mock vascular surgery data (verisuonikirurgia)

Synthetic copies of the 26 HUS Acamedic tables for the vascular surgery cohort. Same file names, same columns in the same order, same date formats as far as we know them, and the IDs link across tables exactly as in the real export (henkilotunnus, shjakso_id, operaatio_id, maarays_id, ac_numero, tulos_id, visit_id ...). Code written against these files should run on the real folder unchanged.

Nothing here is real. henkilotunnus values have valid check characters but use individual numbers 900-999, which are reserved for test identifiers.

## Planted structure (what the pipeline should find)

| Signal | How it is planted |
|---|---|
| Source (hospital) | Tornisairaala writes full sentences under headed sections, Jorvi writes terse abbreviated notes (oik./vas., RR, St:, Ark:), Peijas uses numbered UPPERCASE sections with a "Sanelu purettu" footer |
| Era | Tornisairaala notes from 1.11.2022 use a new plan heading and an instruction footer |
| Note type | Each merkinta_valilehti_selite has its own skeleton (Poliklinikkakäynti, Päivittäismerkintä, Hoitotyön merkintä, Leikkauskertomus, Loppuarvio, Konsultaatio, Puhelinkontakti) |
| Diagnosis | I70 / I71 / I65 / I83 / I74 each have their own vocabulary but share boilerplate, so they separate less than source does |
| Confounding | AAA and carotid patients go mostly to Tornisairaala, varicose veins mostly to Jorvi and Peijas |

Sanity check with TF-IDF + logistic regression, cross-validation grouped by patient: hospital 0.93 (majority 0.44), diagnosis group 0.84 (majority 0.46), note type 1.00.

The diagnosis label for a note comes from a join, as in the real data: notes → `apotti_lahete.lahete_paadiagnoosi_koodi` on henkilotunnus, or `Apotti_osastohoito.paadiagnoosi_koodi` on shjakso_id for ward episodes.

## Free-text columns

- `Apotti_potilaskertomus.merkinta_teksti` (main text, 50-1400 characters, with line breaks)
- `Apotti_kuvantaminen_lausunto.lausunto_teksti` (radiology reports)
- `Apotti_kuvantaminen_tutkimus.pyynto_teksti` (imaging requests)
- `Myplus_naytetiedot.lausunto` (pathology)

Procedure codes (PEQ10, PDQ22, PAF21 ...) follow the NCSP format but are placeholders, I have not checked against the THL code list.
