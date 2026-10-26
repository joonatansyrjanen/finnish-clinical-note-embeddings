# Mock vascular surgery data (verisuonikirurgia)

Synthetic copies of the 28 HUS Acamedic tables for the vascular surgery cohort. File names, columns and column order were checked against the real export headers (26.10.2026). Formats match too: `;` separator, timestamps like `2024-10-10T21:00:00.000Z`, date-only columns like `2024-10-10`, booleans as `true` / `false`, `.` as the decimal separator and `, ` inside `*_lista` columns. Code written against these files should run on the real folder unchanged.

Nothing here is real. The henkilötunnus values in `MOCK_avainlista` have valid check characters but use individual numbers 900-999, which are reserved for test identifiers. Staff names in note headers and referrals are made up from common Finnish names.

## How the IDs work

- Only `MOCK_avainlista` has the real-format henkilötunnus. **Every other table has the pseudonym** (`MOCK_1234567`) in its `henkilotunnus` column, so join tables to each other on that column directly.
- IDs are 64-character hex hashes. The same ID gets the same hash everywhere, so `shjakso_id` still joins to `luotu_shjakso_id` and `tehty_shjakso_id`, `maarays_id` to `ylamaarays_id`, and so on.
- `BCB_*` tables store ICD-10 and NCSP codes directly in `main_diagnosis_id`, `diagnosis_id` and `procedure_id`.

## Notes

Each `merkinta_teksti` starts with a header line, `<role> SURNAME, FIRSTNAME dd.mm.yyyy hh:mm`, like the real notes. Staff names repeat within a hospital, so the header alone gives away the source. That is true of the real data as well, so it is worth comparing embeddings with and without the first line.

## Planted structure (what the pipeline should find)

| Signal | How it is planted |
|---|---|
| Source (hospital) | Tornisairaala writes full sentences under headed sections, Jorvi writes terse abbreviated notes (oik./vas., RR, St:, Ark:), Peijas uses numbered UPPERCASE sections with a "Sanelu purettu" footer. Each hospital also has its own staff names in the header |
| Era | Tornisairaala notes from 1.11.2022 use a new plan heading and an instruction footer |
| Note type | Each `merkinta_valilehti_selite` has its own skeleton |
| Diagnosis | I70 / I71 / I65 / I83 / I74 each have their own vocabulary but share boilerplate, so they separate less than source does |
| Confounding | AAA and carotid patients go mostly to Tornisairaala, varicose veins mostly to Jorvi and Peijas |

Sanity check with TF-IDF and logistic regression, cross-validation grouped by patient: hospital 0.98 with the header line and 0.94 without it; diagnosis group 0.83-0.85.

Codes such as procedure, imaging and SNOMED codes follow the real formats but are placeholders.
