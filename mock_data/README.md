# Mock vascular surgery data (verisuonikirurgia)

Synthetic copies of the 28 HUS Acamedic tables for the vascular surgery cohort, 600 patients. File names, columns and column order were checked against the real export headers (26.10.2026). Formats match too: `;` separator, timestamps like `2024-10-10T21:00:00.000Z`, date-only columns like `2024-10-10`, booleans as `true` / `false`, `.` as the decimal separator and `, ` inside `*_lista` columns. Code written against these files should run on the real folder unchanged.

Nothing here is real. The henkilötunnus values in `MOCK_avainlista` have valid check characters but use individual numbers 900-999, which are reserved for test identifiers. Staff names in note headers and referrals are made up from common Finnish names.

## How the IDs work

- Only `MOCK_avainlista` has the real-format henkilötunnus. **Every other table has the pseudonym** (`MOCK_1234567`) in its `henkilotunnus` column, so join tables to each other on that column directly.
- IDs are 64-character hex hashes. The same ID gets the same hash everywhere, so `shjakso_id` still joins to `luotu_shjakso_id` and `tehty_shjakso_id`, `maarays_id` to `ylamaarays_id`, and so on.
- `BCB_*` tables store ICD-10 and NCSP codes directly in `main_diagnosis_id`, `diagnosis_id` and `procedure_id`.

## Notes

Like the real export, `merkinta_teksti` has no line breaks. About 2% of the notes start with a stamp, `Lisännyt SURNAME, FIRSTNAME dd.mm.yyyy hh:mm`, with no role. Staff names repeat within a hospital, so the stamp alone gives away the source. The other notes start straight with the note itself.

The diagnosis of a note is the main diagnosis (`paadiagnoosi = true`) of its care episode in `Apotti_diagnoosi`, joined on `shjakso_id`.

## Answer key

`_mock_truth.csv` has one row per patient, keyed by the pseudonym: hospital, true diagnosis group and code, the code that was recorded (differs for the label-noise patients), operation and whether the patient speaks Swedish. It does not exist in Acamedic, so the pipeline must not depend on it.

## Planted structure (what the pipeline should find)

| Signal | How it is planted |
|---|---|
| Source (hospital) | Tornisairaala writes full sentences under headed sections, Jorvi writes terse abbreviated notes (oik./vas., RR, St:, Ark:), Peijas uses numbered UPPERCASE sections with a "Sanelu purettu" footer. Each named doctor uses their hospital's style in about 60 % of their notes and the shared Apotti template otherwise, and has their own habit of abbreviating. Each hospital also has its own staff names in the header |
| Era | Tornisairaala notes from 1.11.2022 use a new plan heading and an instruction footer |
| Note type | Each `merkinta_valilehti_selite` has its own skeleton |
| Diagnosis | 12 codes in 5 groups. The groups (I70, I71, I65, I83, I74) have their own vocabulary. Inside a group the codes differ from not at all to clearly: G45.9 vs I65.2 (none), I83.1 vs I83.9 (weak), E11.5, T82.8 and I83.0 (moderate), R02 (clear), ruptured I71.3 vs I71.4 (strong) |
| Confounding | AAA and carotid patients go mostly to Tornisairaala, varicose veins mostly to Jorvi and Peijas |

## Realism added on top (things we expect in the real Apotti data)

| Feature | How it is made |
|---|---|
| Copy-forward | Ward notes reuse sections of the previous day's note, and sometimes the whole note with "Vointi ja suunnitelma ennallaan." added |
| Long tail of length | Short administrative notes ("Ei vastannut puhelimeen ..."), and long discharge summaries with the full medication list, a lab table, standard home instructions and copied operation and imaging text. Lab tables and home instructions are never abbreviated, as they come from fixed templates |
| Other writers | Physiotherapy (tab Kuntoutus), social work (tab Sosiaalityö), infectious diseases and cardiology consultations, written in the shared template |
| Label noise | For 12 % of patients the referral and outpatient episodes carry a neighbouring code in the same group or an unrelated one (I10, M79.6, R10.4, Z09.8). Operation and ward episodes carry the true code, or R02 after an amputation |
| Notes per patient | Some ward stays are prolonged by a complication, with 1-3 nursing notes a day, so a few patients produce many notes |
| Time | During COVID-19 (3/2020-12/2021) most controls are by phone. AAA and carotid follow-up goes on for 1-4 yearly controls |
| Language | Patients from bilingual towns are sometimes Swedish-speaking, and part of their outpatient and phone notes are in Swedish (the medication list stays in Finnish) |

## Sanity check

`scripts/check_mock_signals.py`, TF-IDF and logistic regression, cross-validation grouped by patient, header line removed. Accuracy, with the majority class in brackets:

| Label | All notes (11 028) | Doctors' notes only (4 300) |
|---|---|---|
| Hospital | 0.65 (0.46) | 0.74 (0.45) |
| Note type | 1.00 (0.39) | 1.00 (0.53) |
| Recorded diagnosis code | 0.43 (0.21) | 0.67 (0.18) |

With the header line, hospital accuracy is 0.94. Nursing and physiotherapy notes say almost nothing about the diagnosis, so diagnosis should also be reported for doctors' notes alone. On doctors' notes TF-IDF gets the true group right 95 % of the time and the true code 69 % of the time.

Within-group AUROC per code (doctors' notes): G45.9 0.58, I83.1 0.61, I83.9 0.68, I70.2 0.69, E11.5 0.70, I83.0 0.74, I74.3 / T82.8 0.74, R02 0.77, I71.3 / I71.4 0.86.

About 5 % of notes are under 40 characters and 1 % over 2500 characters (roughly 512 tokens). The recorded diagnosis differs from the true one in about 7 % of notes.

## Things to check against the real export

- The tab names `Kuntoutus` and `Sosiaalityö`, and the specialty codes of the new writers, are guesses. `scripts/inspect_real_categories.py` lists the real values.
- Codes such as procedure, imaging, specialty and SNOMED codes follow the real formats but are placeholders.
