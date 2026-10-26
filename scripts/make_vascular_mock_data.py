"""
make_vascular_mock_data.py

Synthetic HUS Acamedic style tables for vascular surgery (verisuonikirurgia).
Every table has exactly the columns of the real Acamedic export, and the same
patients, care episodes (shjakso_id), operations and imaging orders link across
tables, so code written against these files runs on the real data unchanged.

Nothing here is real. The henkilotunnus values use individual numbers 900-999,
which are reserved for temporary/test identifiers and never given to real people.
As in the export, only MOCK_avainlista holds henkilotunnus; every other table has
the pseudonym (MOCK_1234567) in that column, and IDs are hex hashes.

Planted structure (so you can check the pipeline finds it):
  1. Source: each hospital writes in its own "dialect"
       Tornisairaala = style A (full sentences, headed sections)
       Jorvi         = style B (terse, abbreviated, one paragraph)
       Peijas        = style C (numbered UPPERCASE sections, "Sanelu purettu" footer)
  2. Era: Tornisairaala notes from ERA_CHANGE_DATE on use a new template
     (different plan heading + an instruction footer)
  3. Note type: each merkinta_valilehti_selite has its own skeleton
  4. Diagnosis: each diagnosis group has its own vocabulary, but shares the
     boilerplate, so it separates less than source does
  5. Confounding: AAA and carotid patients go mostly to Tornisairaala,
     varicose veins mostly to Jorvi and Peijas

Usage:
  python scripts/make_vascular_mock_data.py
  python scripts/make_vascular_mock_data.py --patients 600 --seed 1 --out mock_data
"""

import argparse
import hashlib
import re
from datetime import datetime, timedelta
from pathlib import Path
from random import Random

import pandas as pd


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

NUMBER_OF_PATIENTS = 300
SEED = 20240101
DEFAULT_OUTPUT_FOLDER = Path(__file__).resolve().parent.parent / "mock_data"

FIRST_REFERRAL_DATE = datetime(2019, 1, 1)
LAST_REFERRAL_DATE = datetime(2025, 6, 30)
ERA_CHANGE_DATE = datetime(2022, 11, 1)        # New note template at Tornisairaala
WELLBEING_AREAS_START = datetime(2023, 1, 1)   # Referrers become hyvinvointialueet

CSV_SEPARATOR = ";"
LIST_SEPARATOR = ", "                          # Inside *_lista columns

# Timestamps are written like the real export: ISO 8601 in UTC, e.g.
# 2024-10-10T21:00:00.000Z. They are generated as Helsinki local time and converted.
# Columns that hold only a date are written as 2024-10-10 (Helsinki date).
DATE_ONLY_COLUMNS = {"lahete_saapumis_pvm", "hoitopaatos_pvm", "operaatio_pvm", "mittaus_pvm",
                     "estimated_operation_date"}

# In the export every table except MOCK_avainlista has the pseudonym (e.g.
# MOCK_1234567) in the henkilotunnus column, and IDs are hex hashes.
STUDY_NUMBER = "MOCK"
HASH_LENGTH = 64                               # Real IDs are at least 40 hex characters; check

# Columns whose IDs are hashed. Columns in the same family get the same hash for the
# same underlying ID, so shjakso_id still joins to luotu_shjakso_id and tehty_shjakso_id.
ID_FAMILY = {
    "luotu_shjakso_id": "shjakso_id", "tehty_shjakso_id": "shjakso_id",
    "jatko_ohjakso_id": "ohjakso_id", "ylamaarays_id": "maarays_id",
    "ulkoinen_jarjestelma_nayte_id": "myplus_yleinen_nayte_id",
}
HASHED_ID_COLUMNS = set(ID_FAMILY) | {
    "shjakso_id", "ohjakso_id", "kayntitili_id", "hoiko_id", "tuotepaatos_id", "diagnoosi_kokonaisuus",
    "ac_numero", "maarays_id", "laakemaarays_id", "lahete_id", "operaatio_id", "merkinta_id",
    "hoitopaiva_id", "hoitokontakti_id", "suorite_id", "toimenpidekokonaisuus_id", "visit_id",
    "patient_id", "treatment_id", "form_id", "care_event_key", "multilab_potilas_id", "tulos_id",
    "multilab_nayte_id", "myplus_yleinen_nayte_id", "nayte_id", "vastaus_id", "vastauslomake_id",
    "diagnoosi_id", "patologia_nayte_id",
}

# Exact column order of every table, as in the Acamedic export (checked 26.10.2026).
# File name = table name + ".csv". Columns marked "guessed" were not visible in the
# check and are placeholders until confirmed.
COLUMNS = {
    "MOCK_avainlista": ["henkilotunnus", "pseudo_id"],
    "Apotti_diagnoosi": [
        "henkilotunnus", "shjakso_id", "tuotepaatos_id", "diagnoosi_kokonaisuus",
        "tuote_diagnoosi_jarjestys_numero", "potilas_ika_vuosina", "ilmoitettu_alku_hetki",
        "kontakti_alku_hetki", "kontakti_loppu_hetki", "kontakti_toimipiste_koodi",
        "kontakti_toimipiste_selite", "kontakti_kayntityyppi_koodi", "kontakti_kayntityyppi_selite",
        "potilas_sukupuoli_koodi", "potilas_sukupuoli_selite", "diagnoosi_koodi", "diagnoosi_selite",
        "syy_tai_oire", "paadiagnoosi", "pitkaaikaisdiagnoosi", "paivitys_hetki"],
    "Apotti_kaynti": [
        "henkilotunnus", "shjakso_id", "ohjakso_id", "ohjakso_jarn", "jatko_ohjakso_id", "kayntitili_id",
        "hoiko_id", "potilas_ika_vuosina", "kayntityyppi_koodi", "kayntityyppi_selite",
        "varaustyyppi_koodi", "varaustyyppi_selite", "paivakirurgia", "alku_hetki", "loppu_hetki",
        "toimipiste_koodi", "toimipiste_selite", "potilas_eala_koodi", "potilas_eala_selite",
        "paadiagnoosi_koodi", "paadiagnoosi_selite", "sivudiagnoosi_lista",
        "muut_hoitoon_liittyvat_diagnoosit_lista", "tulotapa_koodi", "tulotapa_selite",
        "mista_tuli_koodi", "mista_tuli_selite", "tulosyy_koodi_lista", "tulosyy_selite_lista",
        "lahettaja_koodi", "lahettaja_selite", "jatkohoito_toimipiste_selite", "jatkohoito_koodi",
        "jatkohoito_selite"],
    "Apotti_kuvantaminen_lausunto": [
        "ac_numero", "henkilotunnus", "maarays_id", "ylamaarays_id", "shjakso_id", "lausunto_hetki",
        "lausuja_ammatti_selite", "lausunto_teksti"],
    "Apotti_kuvantaminen_tutkimus": [
        "henkilotunnus", "maarays_id", "ylamaarays_id", "luotu_shjakso_id", "tehty_shjakso_id",
        "ac_numero", "potilas_ika_vuosina", "toimenpide_hetki", "toimenpide_koodi", "toimenpide_selite",
        "toimipiste_koodi", "toimipiste_selite", "lahete_tallennus_hetki", "ilmoittautumis_hetki",
        "lahettaja_toimipiste_koodi", "lahettaja_toimipiste_selite", "prioriteetti_koodi",
        "prioriteetti_selite", "liikkuminen_avustus", "eksponointi_lkm", "kuvantamislaite_id",
        "kuvantamislaite_inventaario_id", "kuvantamislaite_selite", "kuvantamislaite_sijainti_selite",
        "pyynto_teksti"],
    "Apotti_laakitys": [
        "henkilotunnus", "laakemaarays_id", "shjakso_id", "alku_hetki", "loppu_hetki",
        "hoito_ohjelma_alku_hetki", "hoito_ohjelma_loppu_hetki", "hoito_ohjelma_nimi",
        "kirjaaja_toimipiste_eala_koodi", "kirjaaja_toimipiste_eala_selite", "kirjaaja_toimipiste_koodi",
        "kirjaaja_toimipiste_selite", "laakemaarays_tila_koodi", "laakemaarays_tila_selite",
        "laakemaarays_luokka_koodi", "laakemaarays_luokka_selite", "laakerekisteri_koodi",
        "laakerekisteri_selite", "laake_clarity_id", "atc_koodi", "vaikuttava_aine", "vahvuus", "muoto",
        "maara", "antotapa_koodi", "antotapa_lyhenne", "antotapa_selite", "annostelu_annos",
        "annostelu_annos_yksikko", "annostelu_tyyppi_selite", "annostelu_erillis_ohje",
        "annostelu_minimi_annos", "annostelu_maksimi_annos", "narkoottinen_laake", "biologinen_laake",
        "veriplasma_valmiste", "biosimilaari_laake", "lopetus_syy_koodi", "lopetus_syy_selite",
        "laakemaarays_lahde_apotti_koodi", "laakemaarays_lahde_apotti_selite"],
    "Apotti_laakitys_antokirjaus": [
        "henkilotunnus", "laakemaarays_id", "rivi_id", "shjakso_id", "alku_hetki", "loppu_hetki",
        "kirjaaja_toimipiste_koodi", "kirjaaja_toimipiste_selite", "kirjaaja_toimipiste_eala_koodi",
        "kirjaaja_toimipiste_eala_selite", "potilas_pituus", "potilas_paino", "laake_clarity_id",
        "atc_koodi", "vaikuttava_aine", "vahvuus", "muoto", "annos", "annos_yksikko", "antotapa_koodi",
        "antotapa_lyhenne", "antotapa_selite", "antokirjaus_tapahtuma", "antokirjaus_status_tarkenne",
        "lisatieto", "infuusio_nopeus", "infuusio_yksikko", "laakeanto_kesto_koodi",
        "laakeanto_kesto_selite", "narkoottinen_laake", "biologinen_laake", "veriplasma_valmiste",
        "biosimilaari_laake"],
    "Apotti_lahete": [
        "henkilotunnus", "lahete_id", "lahete_cressida_id", "shjakso_id", "hoiko_id", "jono_id",
        "kayntitili_id", "lahete_saapumis_pvm", "kasittely_hetki",
        "lahete_hyvaksytty_ensimmainen_kerta_hetki", "palautus_hetki", "hoito_arvioitu_alku_hetki",
        "tietopyynto_hetki", "hoitopaatos_pvm", "potilas_eala_koodi", "potilas_eala_selite",
        "lahettaja_eala_koodi", "lahettaja_eala_selite", "lahettaja_toimipiste_koodi",
        "lahettaja_toimipiste_oid_koodi", "lahettaja_toimipiste_selite", "lahettaja_toimipiste_topi_koodi",
        "lahettaja_toimipiste_tulosalue", "lahettaja_koodi", "lahettaja_oid_koodi", "lahettaja_selite",
        "lahettaja_ytunnus", "lahettaja_topi_koodi", "alkup_lahettaja_sote_toimipiste_koodi",
        "alkup_lahettaja_selite", "lahettaja_tyyppi_koodi", "lahettaja_tyyppi_selite", "toimipiste_koodi",
        "toimipiste_oid_koodi", "toimipiste_selite", "sote_toimipiste_koodi", "sote_toimipiste_oid_koodi",
        "sote_toimipiste_selite", "lahete_tyyppi_koodi", "lahete_tyyppi_selite", "tila_koodi",
        "tila_selite", "peruttu", "peruttu_hetki", "lahete_suljettu_syy_koodi",
        "lahete_suljettu_syy_selite", "hoitotakuu_hoiko_koodi", "hoitotakuu_hoiko_selite",
        "lahettaja_henkilo_koodi", "lahettaja_henkilo_hus_koodi", "lahettaja_henkilo_nimi",
        "lahettaja_henkilo_nimike", "lahete_kiireellisyysluokka_koodi", "lahete_kiireellisyysluokka_selite",
        "lahete_paadiagnoosi_koodi", "lahete_paadiagnoosi_selite", "lahete_diagnoosi_icpc_2_koodi",
        "lahete_diagnoosi_icpc_2_selite", "lahete_sivudiagnoosit_lista_koodi",
        "lahete_sivudiagnoosit_lista_selite", "lahete_suunta_koodi", "lahete_suunta_selite",
        "lahete_tulotapa_koodi", "lahete_tulotapa_selite", "ulkoistus_syy_koodi", "ulkoistus_syy_selite",
        "palautus_syy_koodi", "palautus_syy_selite", "luotu_hetki", "paivitys_hetki"],
    "Apotti_leikkaus_operaatio": [
        "henkilotunnus", "operaatio_id", "shjakso_id", "potilas_ika_vuosina", "vo_hetki", "operaatio_pvm",
        "potilas_saliin_hetki", "potilas_salista_hetki", "viilto_hetki", "sulku_hetki",
        "potilas_eala_koodi", "potilas_eala_selite", "leikkaus_kiireellisyysluokka_koodi",
        "leikkaus_kiireellisyysluokka_selite", "paatoimenpide_koodi", "paatoimenpide_selite",
        "paatoimenpide_tyyppi", "paatoimenpide_lisakoodit_lista", "paatoimenpide_lisakoodit_selite",
        "paatoimenpide_puolisuus_koodi", "paatoimenpide_puolisuus_selite", "tulotapa_koodi",
        "tulotapa_selite", "hoitava_toimipiste_koodi", "hoitava_toimipiste_apotti_lyhenne",
        "hoitava_toimipiste_selite", "leikkaava_toimipiste_koodi", "leikkaava_toimipiste_selite",
        "leikkaussali", "jatkohoito_toimipiste_koodi", "jatkohoito_toimipiste_apotti_lyhenne",
        "jatkohoito_toimipiste_selite", "ensisijainen_anestesiamuoto", "asa_luokka_koodi",
        "asa_luokka_selite", "puhtausluokka_koodi", "puhtausluokka_selite", "preop_diagnoosi_koodi",
        "preop_diagnoosi_selite", "postop_diagnoosi_koodi", "postop_diagnoosi_selite"],
    "Apotti_leikkaus_toimenpide": [
        "henkilotunnus", "operaatio_id", "shjakso_id", "operaatio_pvm", "paatoimenpide",
        "toimenpide_koodi", "toimenpide_selite", "toimenpide_tyyppi", "toimenpide_lisakoodit_lista",
        "toimenpide_lisakoodit_selite", "toimenpide_puolisuus_koodi", "toimenpide_puolisuus_selite"],
    "Apotti_osastohoito": [
        "henkilotunnus", "shjakso_id", "ohjakso_id", "ohjakso_jarn", "jatko_ohjakso_id", "kayntitili_id",
        "potilas_ika_vuosina", "hoiko_id", "kontakti_vaihe", "potilas_eala_koodi", "potilas_eala_selite",
        "ohjakso_toimipiste_koodi", "ohjakso_toimipiste_selite", "ohjakso_tulokirjaus_selite",
        "ohjakso_lahtokirjaus_selite", "ohjakso_poissaolo_syy_koodi", "ohjakso_poissaolo_syy_selite",
        "ohjakso_alku_hetki", "ohjakso_loppu_hetki", "shjakso_tulosyy_koodi_lista",
        "shjakso_tulosyy_selite_lista", "paadiagnoosi_koodi", "paadiagnoosi_selite", "sivudiagnoosi_lista",
        "muut_hoitoon_liittyvat_diagnoosit_lista", "shjakso_tulotapa_koodi", "shjakso_tulotapa_selite",
        "kayntitili_tulotapa_koodi", "kayntitili_tulotapa_selite",
        "shjakso_lahettaja_koodi", "shjakso_lahettaja_selite",  # Guessed: nothing hidden between these?
        "shjakso_jatkohoito_toimipiste_selite", "shjakso_jatkohoito_koodi", "shjakso_jatkohoito_selite"],
    "Apotti_potilaskertomus": [
        "henkilotunnus", "shjakso_id", "kontaktityyppi_koodi", "kontaktityyppi_selite", "kayntityyppi_koodi",
        "kayntityyppi_selite", "toimipiste_koodi", "toimipiste_selite", "toimipiste_eala_koodi",
        "toimipiste_eala_selite", "shjakso_alku_hetki", "shjakso_loppu_hetki", "merkinta_id",
        "merkinta_valilehti_koodi", "merkinta_valilehti_selite", "merkinta_luonti_hetki",
        "merkinta_paivitys_hetki", "merkinta_teksti"],
    "Apotti_seurantalomake": [
        "henkilotunnus", "hoitopaiva_id", "hoitopaiva_rivi_id", "shjakso_id", "toimipiste_koodi",
        "toimipiste_selite", "kontakti_kirjaus_id", "lda_rivi_id", "mittaus_hetki", "kirjaus_hetki", "arvo",
        "yksikko", "arvo_kommentti_teksti", "arvo_tietotyyppi_koodi", "arvo_tietotyyppi_selite",
        "mittaus_jarjestelma_id", "mittaus_jarjestelma_selite", "mittaus_selite", "mittaus_lomakepohja_id",
        "mittaus_lomakepohja_jarjestelma_selite", "mittaus_lomakepohja_selite",
        "kirjaus_henkilo_ammatti_selite", "kuvaaja", "sallittu_min_arvo", "sallittu_max_arvo",
        "varoitus_min_arvo", "varoitus_max_arvo", "tallennus_laite_id"],  # Guessed: may continue
    "Apotti_toimenpide": [
        "henkilotunnus", "shjakso_id", "tuotepaatos_id", "hoitokontakti_id", "suorite_id",
        "toimenpidekokonaisuus_id", "potilas_ika_vuosina", "toimenpide_hetki", "potilas_eala_koodi",
        "potilas_eala_selite", "tilaava_toimipiste_koodi", "tilaava_toimipiste_selite",
        "toteuttava_toimipiste_koodi", "toteuttava_toimipiste_selite", "kayntityyppi_koodi",
        "kayntityyppi_selite", "potilas_sukupuoli_koodi", "potilas_sukupuoli_selite",
        "potilas_kotikunta_koodi", "potilas_kotikunta_selite", "toimenpide_koodi", "toimenpide_selite",
        "toimenpide_lisakoodit", "paatoimenpide", "uusinta_toimenpide", "kiireellinen", "asa_luokka_koodi",
        "suoritelaji_koodi", "suoritelaji_selite", "paivitys_hetki"],
    "Asiakas_BMI": [
        "henkilotunnus", "sukupuoli", "ika_mittaushetkella", "pituus", "paino", "bmi", "mittaus_pvm",
        "lahdejarjestelma"],
    "Asiakas_verenpaine": [
        "henkilotunnus", "lahdejarjestelma_mittaus_selite", "systolinen_verenpaine",
        "diastolinen_verenpaine", "mittaus_hetki", "lahdejarjestelma"],
    "BCB_verisuoni_form_data": [
        "visit_id", "patient_id", "henkilotunnus", "treatment_id", "form_id", "client_id", "template_code",
        "template_name", "version", "date_created", "last_updated", "user_created", "user_updated",
        "qs_pos", "qg_pos", "level", "qs_code", "qg_code", "question_code", "question_name",
        "string_answer", "number_answer", "date_answer", "boolean_answer", "list_answer", "options",
        "parent_code", "trigger_answer", "saved_from_my_health"],
    "BCB_verisuoni_treatment": [
        "treatment_id", "patient_id", "henkilotunnus", "version",
        "actual_operation_date", "asa_class", "date_created",  # Guessed: hidden in the check
        "difficulty", "estimated_operation_date", "finished", "integration_id", "last_updated", "notes",
        "owner_hospital_id", "priority", "short_description", "user_created", "user_updated", "class",
        "treatment_type_id", "cancelled"],
    "BCB_verisuoni_visit": [
        "visit_id", "treatment_id", "henkilotunnus", "patient_id", "version", "asa_class", "cancel_reason",
        "cancelled", "date_created", "date_visit_finished", "date_visited", "description",
        "follow_up_ward_id", "hospital_id",
        "last_updated",  # Guessed: hidden in the check
        "main_diagnosis_id", "main_procedure_id", "operating_room_end_time", "operating_room_start_time",
        "phase_id", "previous_ward_id", "priority", "procedure_end_time", "procedure_start_time",
        "room_id", "user_created", "user_updated", "visit_type_id", "ward_id", "cut_time",
        "wound_closing_time", "class", "cleanliness_class", "care_event_key", "care_event_type",
        "service_type", "appointment_diagnosis_id", "dosedap", "dosedlp",
        "radiological_procedure_end_time", "radiological_procedure_start_time", "unitdap", "unitdlp"],
    "BCB_verisuoni_visit_diagnoses": ["visit_id", "henkilotunnus", "patient_id", "diagnosis_id"],
    "BCB_verisuoni_visit_procedures": [
        "visit_id", "henkilotunnus", "patient_id", "visit_secondary_anesthesia_procedures_id",
        "procedure_id"],
    "Kohortti": ["henkilotunnus", "Apotti_kohortti", "visit_id", "treatment_id", "BCB_kohortti"],
    "Multilab_tulos": [
        "henkilotunnus", "multilab_potilas_id", "tulos_id", "multilab_nayte_id", "myplus_yleinen_nayte_id",
        "ulkoinen_jarjestelma_nayte_id", "patologia_nayte_id", "suorite_id", "potilas_ika_vuosina",
        "pyynto_hetki", "naytteenotto_hetki", "teko_hetki", "lahetys_hetki", "tutkimus_kuntaliiton_numero",
        "tutkimus_lyhenne", "tutkimus_pitkanimi", "tutkimus_eala_selite", "paatutkimus_kuntaliiton_numero",
        "paatutkimus_lyhenne", "paatutkimus_pitkanimi", "paatutkimus_eala_selite", "tulos", "yksikko",
        "viitearvot", "ala_viitearvo", "yla_viitearvo", "tulos_viitearvo_ulkopuolella", "tulos_epavarma",
        "vastaus_id", "lausunto", "kommentti", "tutkimus_lisatietoja", "tutkimus_mikrobituloksia",
        "pyytava_toimipiste_koodi", "pyytava_toimipiste_lyhenne", "pyytava_toimipiste_selite",
        "naytteenotto_toimipiste_koodi", "naytteenotto_toimipiste_lyhenne", "naytteenotto_toimipiste_selite",
        "tekopaikka_toimipiste_koodi", "tekopaikka_toimipiste_lyhenne", "tekopaikka_toimipiste_selite",
        "muutostiedot", "viimeinen_muutos_hetki"],
    "Multilab_tulos_lisatieto": [
        "henkilotunnus", "multilab_potilas_id", "tulos_id", "lisatieto_id", "multilab_nayte_id",
        "myplus_yleinen_nayte_id", "ulkoinen_jarjestelma_nayte_id", "pyynto_hetki", "naytteenotto_hetki",
        "teko_hetki", "lahetys_hetki", "tutkimus_kuntaliiton_numero", "tutkimus_lyhenne", "tutkimus_pitkanimi",
        "tutkimus_eala_selite", "tulos", "tutkimus_lisatieto_otsikko", "tutkimus_lisatieto_teksti",
        "viimeinen_muutos_hetki"],
    "Multilab_tulos_mikrobi": [
        "henkilotunnus", "multilab_potilas_id", "tulos_id", "mikrobi_tulos_id", "multilab_nayte_id",
        "myplus_yleinen_nayte_id", "ulkoinen_jarjestelma_nayte_id", "pyynto_hetki", "naytteenotto_hetki",
        "teko_hetki", "lahetys_hetki", "tutkimus_kuntaliiton_numero", "tutkimus_lyhenne", "tutkimus_pitkanimi",
        "tutkimus_eala_selite", "loydos_tyyppi_koodi", "loydos_tyyppi_selite", "tulos", "maara",
        "loydos_positiivinen", "kommentti_loydoskohtainen", "mikrobi_lyhenne", "mikrobi_pitkanimi",
        "mikrobi_ryhma_koodi", "mikrobi_ryhma_selite", "mikrobikanta_koodi", "mikrobikanta_selite",
        "mikrobi_whonet_koodi", "mikrobi_whonet_lyhenne", "mikrobi_whonet_selite", "alkup_mikrobitulostaulu",
        "viimeinen_muutos_hetki"],
    "Myplus_diagnoosi": [
        "henkilotunnus", "nayte_id", "vastaus_id", "diagnoosi_id", "myplus_yleinen_nayte_id",
        "patologia_nayte_id", "patologia_rivi_numero", "m_snomed", "diagnoosi", "diagnoosi_takaliite",
        "t_snomed", "elin", "elin_takaliite", "viimeinen_muutos_hetki"],
    "Myplus_lausuntolomake": [
        "henkilotunnus", "nayte_id", "vastaus_id", "vastauslomake_id", "vastauslomake_pohja_id",
        "myplus_yleinen_nayte_id", "patologia_nayte_id", "vastauslomake_nimi", "vastauslomake_tyyppi",
        "vastauslomake_jarjestys_numero", "vastaus_nimi", "vastaus_arvo", "vastaus_tarkenne",
        "vastaus_yksikko", "nayte_viimeisin_vastaus_hetki", "viimeinen_muutos_hetki"],
    "Myplus_naytetieto": [
        "henkilotunnus", "nayte_id", "vastaus_id", "myplus_yleinen_nayte_id", "patologia_nayte_id",
        "suorite_id", "potilas_ika_vuosina", "pyynto_hetki", "naytteenotto_hetki", "nayte_saapumis_hetki",
        "nayte_vastaus_hetki", "nayte_tyyppi", "nayte_paakategoria", "tutkimus_kuntaliiton_numero",
        "tutkimus_lyhenne", "tutkimus_pitkanimi", "tutkimus_eala_selite", "vastaus_jarjestys_numero",
        "pyytava_toimipiste_koodi", "pyytava_toimipiste_lyhenne", "pyytava_toimipiste_selite",
        "naytteenotto_toimipiste_koodi", "naytteenotto_toimipiste_lyhenne", "naytteenotto_toimipiste_nimi",
        "tekopaikka_toimipiste_koodi", "tekopaikka_toimipiste_lyhenne", "tekopaikka_toimipiste_nimi",
        "viimeinen_muutos_hetki", "lausunto"],
}


# ---------------------------------------------------------------------------
# Hospitals, diagnoses, procedures
# ---------------------------------------------------------------------------

HOSPITALS = {
    "Tornisairaala": {
        "style": "A",
        "clinic": "Verisuonikirurgian poliklinikka, Tornisairaala",
        "ward": "Osasto M12, Tornisairaala",
        "theatre": "Anestesia- ja leikkausyksikkö, Tornisairaala",
        "icu": "Teho-osasto, Meilahden sairaala",
        "angio": "Meilahden tornisairaalan angio, DSA",
        "angio_code": "78210071A",
        "radiology": "Meilahden tornisairaalan röntgen",
        "radiology_code": "78210012A",
        "laboratory": "Verisuonikirurgian poliklinikka, Tornisairaala",
        "towns": ["Helsinki"],
    },
    "Jorvi": {
        "style": "B",
        "clinic": "Verisuonikirurgian poliklinikka, Jorvin sairaala",
        "ward": "Kirurgian osasto K4, Jorvin sairaala",
        "theatre": "Anestesia- ja leikkausyksikkö, Jorvin sairaala",
        "icu": "Teho-osasto, Jorvin sairaala",
        "angio": "Jorvin sairaalan angio",
        "angio_code": "78230044A",
        "radiology": "Jorvin sairaalan röntgen",
        "radiology_code": "78230011A",
        "laboratory": "Verisuonikirurgian poliklinikka, Jorvin sairaala",
        "towns": ["Espoo", "Espoo", "Kirkkonummi", "Kauniainen", "Lohja"],
    },
    "Peijas": {
        "style": "C",
        "clinic": "Verisuonikirurgian poliklinikka, Peijaksen sairaala",
        "ward": "Kirurgian osasto 3B, Peijaksen sairaala",
        "theatre": "Anestesia- ja leikkausyksikkö, Peijaksen sairaala",
        "icu": "Teho-osasto, Peijaksen sairaala",
        "angio": "Peijaksen sairaalan angio",
        "angio_code": "78240031A",
        "radiology": "Peijaksen sairaalan röntgen",
        "radiology_code": "78240010A",
        "laboratory": "Verisuonikirurgian poliklinikka, Peijaksen sairaala",
        "towns": ["Vantaa", "Vantaa", "Kerava", "Tuusula", "Järvenpää", "Sipoo", "Porvoo"],
    },
}

# Referring health centres by town, before and after the wellbeing services counties
REFERRERS = {
    "Helsinki": ("Helsingin kaupunki", "Helsingin kaupunki", ["Malmin terveysasema", "Kalasataman terveysasema", "Myllypuron terveysasema", "Vuosaaren terveysasema"]),
    "Espoo": ("Espoon kaupunki", "Länsi-Uudenmaan hyvinvointialue", ["Tapiolan terveysasema", "Leppävaaran terveysasema", "Matinkylän terveysasema"]),
    "Kirkkonummi": ("Kirkkonummen kunta", "Länsi-Uudenmaan hyvinvointialue", ["Kirkkonummen terveysasema"]),
    "Kauniainen": ("Kauniaisten kaupunki", "Länsi-Uudenmaan hyvinvointialue", ["Kauniaisten terveysasema"]),
    "Lohja": ("Lohjan kaupunki", "Länsi-Uudenmaan hyvinvointialue", ["Lohjan terveysasema", "Lohjan sairaala, päivystys"]),
    "Vantaa": ("Vantaan kaupunki", "Vantaan ja Keravan hyvinvointialue", ["Tikkurilan terveysasema", "Myyrmäen terveysasema", "Korson terveysasema"]),
    "Kerava": ("Keravan kaupunki", "Vantaan ja Keravan hyvinvointialue", ["Keravan terveysasema"]),
    "Tuusula": ("Keski-Uudenmaan sote", "Keski-Uudenmaan hyvinvointialue", ["Hyrylän terveysasema"]),
    "Järvenpää": ("Keski-Uudenmaan sote", "Keski-Uudenmaan hyvinvointialue", ["Järvenpään terveysasema"]),
    "Sipoo": ("Sipoon kunta", "Itä-Uudenmaan hyvinvointialue", ["Sipoon terveysasema"]),
    "Porvoo": ("Porvoon kaupunki", "Itä-Uudenmaan hyvinvointialue", ["Porvoon terveyskeskus", "Porvoon sairaala, päivystys"]),
}

GROUPS = {
    "I70": {
        "code": "I70.2", "text": "Raajojen valtimoiden ateroskleroosi", "share": 0.40,
        "hospital_weights": {"Tornisairaala": 0.35, "Jorvi": 0.35, "Peijas": 0.30},
        "male_share": 0.60, "age_mean": 72, "age_sd": 9, "operation_share": 0.65,
        "procedures": {"pta": 0.55, "bypass": 0.30, "amputation": 0.15},
        "comorbidity": {"I10": 0.7, "E11.9": 0.4, "I25.1": 0.35, "E78.0": 0.5, "N18.3": 0.2, "F17.2": 0.45, "J44.9": 0.2, "I48.9": 0.15},
    },
    "I71": {
        "code": "I71.4", "text": "Vatsa-aortan aneurysma ilman mainintaa repeämästä", "share": 0.17,
        "hospital_weights": {"Tornisairaala": 0.70, "Jorvi": 0.15, "Peijas": 0.15},
        "male_share": 0.85, "age_mean": 74, "age_sd": 6, "operation_share": 0.50,
        "procedures": {"evar": 0.65, "open_aaa": 0.35},
        "comorbidity": {"I10": 0.7, "I25.1": 0.4, "E78.0": 0.5, "J44.9": 0.25, "F17.2": 0.35, "N18.3": 0.15, "I48.9": 0.15, "E11.9": 0.15},
    },
    "I65": {
        "code": "I65.2", "text": "Kaulavaltimon tukos ja ahtauma", "share": 0.15,
        "hospital_weights": {"Tornisairaala": 0.60, "Jorvi": 0.20, "Peijas": 0.20},
        "male_share": 0.65, "age_mean": 71, "age_sd": 8, "operation_share": 0.65,
        "procedures": {"cea": 1.0},
        "comorbidity": {"I10": 0.7, "E78.0": 0.55, "E11.9": 0.25, "I25.1": 0.3, "I48.9": 0.1, "F17.2": 0.3},
    },
    "I83": {
        "code": "I83.9", "text": "Alaraajan laskimolaajentumat ilman haavaumaa tai tulehdusta", "share": 0.20,
        "hospital_weights": {"Tornisairaala": 0.10, "Jorvi": 0.45, "Peijas": 0.45},
        "male_share": 0.35, "age_mean": 52, "age_sd": 12, "operation_share": 0.70,
        "procedures": {"rfa": 1.0},
        "comorbidity": {"I10": 0.2, "E78.0": 0.1},
    },
    "I74": {
        "code": "I74.3", "text": "Alaraajan valtimon embolia ja tromboosi", "share": 0.08,
        "hospital_weights": {"Tornisairaala": 0.50, "Jorvi": 0.25, "Peijas": 0.25},
        "male_share": 0.50, "age_mean": 76, "age_sd": 8, "operation_share": 0.90,
        "procedures": {"thrombectomy": 1.0},
        "comorbidity": {"I48.9": 0.7, "I10": 0.6, "I25.1": 0.3, "E11.9": 0.25, "N18.3": 0.25},
    },
}

COMORBIDITIES = {
    "I10": ("Essentiaalinen verenpainetauti", "Verenpainetauti"),
    "E11.9": ("Tyypin 2 diabetes ilman komplikaatioita", "Tyypin 2 diabetes"),
    "I25.1": ("Ateroskleroottinen sydänsairaus", "Sepelvaltimotauti"),
    "E78.0": ("Puhdas hyperkolesterolemia", "Hyperkolesterolemia"),
    "N18.3": ("Krooninen munuaistauti, vaihe 3", "Munuaisten vajaatoiminta, CKD 3"),
    "F17.2": ("Tupakan aiheuttama riippuvuus", "Tupakointi"),
    "J44.9": ("Keuhkoahtaumatauti, määrittämätön", "Keuhkoahtaumatauti"),
    "I48.9": ("Eteisvärinä tai eteislepatus, määrittämätön", "Eteisvärinä"),
}

# Procedure codes follow the NCSP format but are placeholders, not verified codes
PROCEDURES = {
    "pta": {"code": "PEQ10", "text": "Reisivaltimon pallolaajennus ja stenttaus", "endovascular": True,
            "anaesthesia": ["Paikallispuudutus"], "ward_days": (1, 2), "day_surgery": False, "minutes": (45, 120)},
    "bypass": {"code": "PEH20", "text": "Reisi-polvitaivevaltimon ohitusleikkaus laskimosiirteellä", "endovascular": False,
               "anaesthesia": ["Yleisanestesia", "Spinaalipuudutus"], "ward_days": (5, 9), "day_surgery": False, "minutes": (150, 300)},
    "amputation": {"code": "NGQ19", "text": "Säären amputaatio", "endovascular": False,
                   "anaesthesia": ["Spinaalipuudutus", "Yleisanestesia"], "ward_days": (7, 14), "day_surgery": False, "minutes": (60, 120)},
    "evar": {"code": "PDQ22", "text": "Vatsa-aortan aneurysman stenttigraftihoito (EVAR)", "endovascular": True,
             "anaesthesia": ["Yleisanestesia"], "ward_days": (2, 4), "day_surgery": False, "minutes": (90, 200)},
    "open_aaa": {"code": "PDG22", "text": "Vatsa-aortan aneurysman korjaus Y-proteesilla", "endovascular": False,
                 "anaesthesia": ["Yleisanestesia"], "ward_days": (7, 12), "day_surgery": False, "minutes": (180, 360)},
    "cea": {"code": "PAF21", "text": "Kaulavaltimon endarterektomia", "endovascular": False,
            "anaesthesia": ["Yleisanestesia", "Paikallispuudutus"], "ward_days": (1, 3), "day_surgery": False, "minutes": (90, 180)},
    "rfa": {"code": "PHD16", "text": "Ison kehräslaskimon radiotaajuusablaatio", "endovascular": True,
            "anaesthesia": ["Paikallispuudutus"], "ward_days": (0, 0), "day_surgery": True, "minutes": (40, 90)},
    "thrombectomy": {"code": "PEE10", "text": "Alaraajavaltimon trombembolektomia", "endovascular": False,
                     "anaesthesia": ["Yleisanestesia"], "ward_days": (4, 8), "day_surgery": False, "minutes": (60, 150)},
}

SEX_TEXT = {"1": "Mies", "2": "Nainen"}

# Real municipality codes
MUNICIPALITY_CODES = {
    "Helsinki": "091", "Espoo": "049", "Kirkkonummi": "257", "Kauniainen": "235", "Lohja": "444",
    "Vantaa": "092", "Kerava": "245", "Tuusula": "858", "Järvenpää": "186", "Sipoo": "753", "Porvoo": "638",
}

SOTE_NAMES = {"Tornisairaala": "Meilahden tornisairaala", "Jorvi": "Jorvin sairaala", "Peijas": "Peijaksen sairaala"}
THEATRE_ROOM_PREFIX = {"Tornisairaala": "TORNs", "Jorvi": "JORVs", "Peijas": "PEIJs"}

# Placeholder codes in the real formats (NCSP-like AAA99, imaging AA9AA)
SIDE_CODES = {"Oikea": "ZXA00", "Vasen": "ZXA10"}
ANAESTHESIA_CODES = {"Yleisanestesia": "WAA20", "Spinaalipuudutus": "WAB20", "Paikallispuudutus": "WAC10"}
OUTPATIENT_PROCEDURE_CODES = {"Nilkka-olkavarsipainesuhteen mittaus": "PZX10", "EKG": "SFA00", "Thoraxin röntgen": "XGD10"}

# Note tabs, contact and visit types (codes are placeholders in the real formats)
NOTE_TAB_CODES = {"Poliklinikkakäynti": "10", "Puhelinkontakti": "11", "Päivittäismerkintä": "12",
                  "Hoitotyön merkintä": "13", "Leikkauskertomus": "14", "Loppuarvio": "15", "Konsultaatio": "16"}
CONTACT_TYPE_CODES = {"Käynti": "1000101", "Puhelu": "1000102", "Sisäänkirjausjakso": "1000103"}
VISIT_TYPES = {"first": ("1", "Ensikäynti"), "control": ("2", "Uusintakäynti"), "phone": ("3", "Puhelinkontakti"),
               "ward": ("4", "Osastohoitojakso"), "theatre": ("5", "Toimenpidekäynti"), "imaging": ("6", "Tutkimuskäynti")}
KAYNTI_TYPES = {"Käynti": ("01", "Vastaanotto"), "Soitto": ("03", "Puhelu")}

# Every note starts with a header line like the real export:
#   "<role> SURNAME, FIRSTNAME 12.03.2024 14:05"
# The real first word is 8 letters long; check what it is and change NOTE_HEADER / roles
NOTE_HEADER = "{role} {name} {moment}"
NURSE_ROLES = ["Sairaanhoitaja"]
PHYSICIAN_ROLES = ["Erikoislääkäri", "Erikoislääkäri", "Erikoistuva lääkäri"]
ROLE_BY_TAB = {"Hoitotyön merkintä": NURSE_ROLES}

SURNAMES = ["VIRTANEN", "KORHONEN", "MÄKINEN", "NIEMINEN", "MÄKELÄ", "HÄMÄLÄINEN", "LAINE", "HEIKKINEN",
            "KOSKINEN", "JÄRVINEN", "LEHTONEN", "LEHTINEN", "SAARINEN", "SALMINEN", "HEINONEN", "NIEMI",
            "HEIKKILÄ", "KINNUNEN", "SALONEN", "TURUNEN", "SALO", "LAITINEN", "TUOMINEN", "RANTANEN",
            "KARJALAINEN", "JOKINEN", "MATTILA", "SAVOLAINEN", "LAHTINEN", "AHONEN"]
FIRST_NAMES = ["MARIA", "HELENA", "JOHANNA", "ANNA", "KAISA", "LAURA", "SANNA", "MINNA", "ELINA", "KATJA",
               "JUHANI", "MIKAEL", "MATTI", "ANTTI", "JUHA", "MARKO", "TIMO", "PETRI", "VILLE", "JUSSI"]
STAFF_RANDOM = Random(SEED + 1)  # Separate stream so staff lists do not shift the rest of the data
STAFF = {}

ASA_TEXTS = {1: "Terve", 2: "Lievä yleissairaus", 3: "Vakava yleissairaus", 4: "Henkeä uhkaava yleissairaus"}

SIDES = {
    "oikea": {"nom": "oikea", "gen": "oikean", "ine": "oikeassa", "ade": "oikealla", "label": "Oikea"},
    "vasen": {"nom": "vasen", "gen": "vasemman", "ine": "vasemmassa", "ade": "vasemmalla", "label": "Vasen"},
}



# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

generator = Random(SEED)
TABLES = {name: [] for name in COLUMNS}
PSEUDO_IDS = {}  # henkilotunnus -> pseudo_id
ID_COUNTERS = {}


def pick(options):
    """Random element of a list."""
    return generator.choice(options)


def pick_weighted(weights):
    """Random key of a {key: weight} dict."""
    keys = list(weights)
    return generator.choices(keys, weights=[weights[key] for key in keys])[0]


def chance(probability):
    """True with the given probability."""
    return generator.random() < probability


def between(low, high):
    """Random integer, both ends included."""
    return generator.randint(low, high)


def comma(value, decimals):
    """Number with a Finnish decimal comma, for free text."""
    return ("%." + str(decimals) + "f") % value


def comma_text(value, decimals):
    return comma(value, decimals).replace(".", ",")


def capitalise(text):
    return text[:1].upper() + text[1:]


def lower_first(text):
    """Lower-case the first letter, but leave acronyms such as VSM or ABI alone."""
    if len(text) > 1 and text[1].isupper():
        return text
    return text[:1].lower() + text[1:]


def next_id(name, start):
    """Running integer ID per kind of identifier."""
    ID_COUNTERS[name] = ID_COUNTERS.get(name, start) + between(1, 7)
    return ID_COUNTERS[name]


def add_row(table, **values):
    """Append one row. Columns not given stay empty; unknown columns are refused."""
    unknown = set(values) - set(COLUMNS[table])
    if unknown:
        raise KeyError("%s has no column(s) %s" % (table, sorted(unknown)))
    TABLES[table].append(values)
    return values


def unit_code(name, digits=7, letter=""):
    """Stable fake code for a unit or organisation, e.g. 2545006 or 78210012A."""
    number = int(hashlib.sha256(name.encode("utf-8")).hexdigest(), 16)
    return str(10 ** (digits - 1) + number % (9 * 10 ** (digits - 1))) + letter


def oid(name):
    """Fake OID in the real shape, e.g. 1.2.246.10.12345678.10.12345."""
    return "1.2.246.10.%s.10.%s" % (unit_code(name, 8), unit_code(name + "oid", 5))


def apotti_abbreviation(unit):
    """Osasto M12, Tornisairaala -> OSA M12 TOR."""
    words = re.findall(r"[\wÅÄÖåäö]+", unit)
    return " ".join(word[:3].upper() for word in words[:4])


def staff_member(organisation, role):
    """Same small pool of named staff per organisation and role, so authors repeat as in real data."""
    key = (organisation, role)
    if key not in STAFF:
        STAFF[key] = ["%s, %s" % (STAFF_RANDOM.choice(SURNAMES), STAFF_RANDOM.choice(FIRST_NAMES)) for number in range(4)]
    return pick(STAFF[key])


def at_time(day, first_hour, last_hour):
    """Random clock time on a given day."""
    return datetime(day.year, day.month, day.day, between(first_hour, last_hour), between(0, 59), between(0, 59))


def short_date(moment):
    return "%d.%d.%d" % (moment.day, moment.month, moment.year)


def last_sunday(year, month):
    """Last Sunday of March or October (both have 31 days)."""
    day = datetime(year, month, 31)
    return day - timedelta(days=(day.weekday() - 6) % 7)


def helsinki_offset_hours(local):
    """+3 in summer time (last Sunday of March 03:00 to last Sunday of October 04:00), otherwise +2."""
    summer_start = last_sunday(local.year, 3) + timedelta(hours=3)
    summer_end = last_sunday(local.year, 10) + timedelta(hours=4)
    return 3 if summer_start <= local < summer_end else 2


def format_moment(column, moment):
    """Helsinki local time -> 2024-10-10T21:00:00.000Z, or 2024-10-10 for date-only columns."""
    if column in DATE_ONLY_COLUMNS:
        return moment.strftime("%Y-%m-%d")
    utc = moment - timedelta(hours=helsinki_offset_hours(moment))
    return utc.strftime("%Y-%m-%dT%H:%M:%S") + ".000Z"


def make_henkilotunnus(birth_date, used):
    """Valid-checksum test HETU (individual number 900-999 = never a real person)."""
    while True:
        individual = between(900, 999)
        digits = birth_date.strftime("%d%m%y") + "%03d" % individual
        check = "0123456789ABCDEFHJKLMNPRSTUVWXY"[int(digits) % 31]
        century = "-" if birth_date.year < 2000 else "A"
        value = birth_date.strftime("%d%m%y") + century + "%03d" % individual + check
        if value not in used:
            used.add(value)
            return value


# ---------------------------------------------------------------------------
# Writing styles (the planted "source" signal)
# ---------------------------------------------------------------------------

HEADERS = {
    "A": {"reason": "Tulosyy", "history": "Esitiedot", "medication": "Lääkitys", "anamnesis": "Nykytila",
          "status": "Status", "imaging": "Tutkimukset", "plan": "Arvio ja suunnitelma",
          "day": "Postoperatiivinen päivä", "condition": "Vointi", "phone": "Puhelu",
          "procedure": "Toimenpide", "anaesthesia": "Anestesia", "indication": "Indikaatio",
          "description": "Toimenpiteen kuvaus", "instructions": "Jatko-ohjeet",
          "summary": "Yhteenveto", "course": "Hoidon kulku"},
    "B": {"reason": "Tsto", "history": "Aiemmin", "medication": "Lääk.", "anamnesis": "Anamn.",
          "status": "St", "imaging": "Tutk.", "plan": "Ark",
          "day": "POP", "condition": "Vointi", "phone": "Soitto",
          "procedure": "Tmp", "anaesthesia": "Anest.", "indication": "Ind.",
          "description": "Kulku", "instructions": "Jatko",
          "summary": "Yht.", "course": "Kulku"},
    "C": {"reason": "TULOSYY", "history": "TAUSTA", "medication": "LÄÄKITYS", "anamnesis": "NYKYTILA",
          "status": "LÖYDÖKSET", "imaging": "KUVANTAMINEN", "plan": "JOHTOPÄÄTÖS JA JATKO",
          "day": "HOITOPÄIVÄ", "condition": "VOINTI", "phone": "PUHELINKONTAKTI",
          "procedure": "TOIMENPIDE", "anaesthesia": "ANESTESIA", "indication": "INDIKAATIO",
          "description": "KUVAUS", "instructions": "JATKOHOITO",
          "summary": "YHTEENVETO", "course": "HOIDON KULKU"},
}

# Style B shorthand, longest first so "oikean" is caught before "oikea"
ABBREVIATIONS_STYLE_B = [
    ("molemmin puolin", "bil."), ("eivät tunnu", "ei palp."), ("ei tunnu", "ei palp."),
    ("oikean", "oik."), ("oikeassa", "oik."), ("oikealla", "oik."), ("oikea", "oik."),
    ("vasemman", "vas."), ("vasemmassa", "vas."), ("vasemmalla", "vas."), ("vasen", "vas."),
    ("Verenpaine", "RR"), ("verenpaine", "RR"), ("noin", "n."), ("poliklinikalla", "pkl:lla"),
    ("poliklinikalle", "pkl:lle"), ("poliklinikka", "pkl"), ("potilas", "pt"), ("Potilas", "Pt"),
    ("kontrolli", "ktrl"), ("Kontrolli", "Ktrl"), ("tarvittaessa", "tarv."), ("Syke", "P"),
    ("syke", "p"), ("leikkauksen", "leikk."), ("leikkaus", "leikk."), ("kuukauden", "kk:n"),
    ("viikon", "vk:n"), ("ultraäänessä", "UÄ:ssä"), ("tupakoi", "tup."), ("normaali", "nl"),
    ("kotiutus", "kotiin"), ("suunnitellaan", "suunn."), ("Suunnitellaan", "Suunn."),
]


def abbreviate(text):
    for long_form, short_form in ABBREVIATIONS_STYLE_B:
        text = re.sub(r"\b" + re.escape(long_form) + r"\b", short_form, text)
    return text


def render_note(style, sections, moment, footer=True):
    """Turn [(section_key, text), ...] into note text in a hospital's dialect."""
    new_era = moment >= ERA_CHANGE_DATE
    headers = HEADERS[style]
    if style == "A":
        parts = []
        for key, text in sections:
            header = headers[key]
            if key == "plan" and new_era:
                header = "Hoidon tarpeen arvio ja suunnitelma"
            if key in ("reason", "day", "procedure", "anaesthesia"):
                parts.append("%s: %s" % (header, text))
            else:
                parts.append("%s:\n%s" % (header, text))
        if footer and new_era and chance(0.85):
            parts.append("Potilaalle annettu kirjalliset ohjeet ja yhteystiedot.")
        return "\n\n".join(parts)
    if style == "B":
        parts = []
        for key, text in sections:
            if key == "day":
                parts.append("POP%s." % text)
                continue
            if chance(0.5):
                text = lower_first(text)
            text = text.replace("\n", " ").strip()
            if text[-1] not in ".!?":
                text += "."
            parts.append("%s: %s" % (headers[key], text))
        joined = " ".join(parts) if chance(0.6) else "\n".join(parts)
        return abbreviate(joined)
    parts = []
    for number, (key, text) in enumerate(sections, start=1):
        parts.append("%d. %s\n%s" % (number, headers[key], text))
    if footer:
        parts.append("Sanelu purettu %s." % short_date(moment + timedelta(days=between(0, 3))))
    return "\n\n".join(parts)


def join_some(options, low, high, context):
    """Pick low..high distinct sentences from a bank and fill them in."""
    count = min(len(options), between(low, high))
    chosen = generator.sample(options, count)
    return " ".join(sentence.format(**context) for sentence in chosen)


# ---------------------------------------------------------------------------
# Clinical sentence banks per diagnosis group
# ---------------------------------------------------------------------------

BANKS = {
    "I70": {
        "reason": ["Katkokävely {side_ine} alaraajassa", "{side_gen_cap} alaraajan iskemia ja leposärky",
                   "Parantumaton haava {side_ine} jalassa, iskemiaepäily", "Alaraajojen valtimotaudin arvio"],
        "anamnesis": [
            "Kävelymatka on lyhentynyt viimeisen vuoden aikana noin {walk_m} metriin, jonka jälkeen {side_gen} pohje kipeytyy ja pitää pysähtyä.",
            "Kipu helpottaa levossa muutamassa minuutissa.",
            "Viime viikkoina myös öistä leposärkyä {side_ine} jalkaterässä, nukkuu välillä jalka sängyn reunalta roikkuen.",
            "{side_gen_cap} isovarpaan kärjessä haava, joka ei ole parantunut {ulcer_weeks} viikossa kotisairaanhoidon haavanhoidosta huolimatta.",
            "Tupakoi edelleen noin {cigs} savuketta päivässä.",
            "Lopettanut tupakoinnin {quit_years} vuotta sitten.",
            "Kävelee päivittäin, mutta lenkki on jäänyt lyhyemmäksi kipujen vuoksi.",
        ],
        "status": [
            "ABI {side_nom} {abi_side}, {other_nom} {abi_other}.",
            "A. femoralis palpoituu molemmin puolin, {side_ade} puolella polvitaipeen ja jalkaterän pulssit eivät tunnu.",
            "Dopplerilla a. dorsalis pedis {side_ade} puolella monofaasinen signaali.",
            "Jalkaterä {side_ade} puolella viileä, kapillaaritäyttö hidastunut, karvoitus niukka.",
            "Isovarpaan kärjessä noin {ulcer_mm} mm kuiva nekroosi, ympärillä ei punoitusta.",
            "Varvaspaine {side_ade} puolella {toe_pressure} mmHg.",
        ],
        "imaging": [
            "TT-angiografiassa {side_gen} a. femoralis superficialiksen noin {occl_cm} cm pitkä okkluusio, distaalinen täyttyminen polvitaipeen tasolta.",
            "Duplex-UÄ:ssä {side_gen} AFS:n distaaliosassa merkittävä ahtauma, virtausnopeus {psv} cm/s.",
            "Iliakavaltimot molemmin puolin aukeat, lieviä kalkkeutumia.",
        ],
        "plan_operative": [
            "Suunnitellaan {side_gen} AFS-alueen PTA ja tarvittaessa stentti angiosalissa.",
            "Kriittinen iskemia, revaskularisaatio kiireellisesti. Laskimokartoitus ohitusta varten.",
            "Asia käsitelty verisuonimeetingissä, puolletaan femoropopliteaalista ohitusta.",
            "Kuolio etenevä eikä revaskularisaatiomahdollisuutta ole, joten suunnitellaan säären amputaatiota.",
        ],
        "plan_conservative": [
            "Katkokävely ei ole invalidisoiva, joten aloitetaan valvottu kävelyharjoittelu. Kontrolli puolen vuoden kuluttua.",
            "Ohjattu tupakoinnin lopettamisesta, statiini ja ASA jatkuvat.",
            "Ei tällä hetkellä toimenpideindikaatiota, uusi arvio jos oireet pahenevat.",
        ],
        "control_operative": [
            "Kävelymatka pidentynyt selvästi, ei enää leposärkyä.", "Haava parantunut hyvin.",
            "ABI toimenpiteen jälkeen {abi_post}.", "Jalkaterän pulssit tuntuvat.",
        ],
        "control_conservative": [
            "Kävelyharjoittelu aloitettu, matka pidentynyt noin {walk_m_later} metriin.",
            "Tupakointi vähentynyt.", "ABI ennallaan {abi_side}.",
        ],
        "daily": ["Jalka lämmin, jalkaterän pulssi tuntuu dopplerilla.", "ABI {abi_post}.",
                  "Punktiokohta nivusessa siisti, ei hematoomaa.", "Haavat siistit, säären turvotus vähäistä."],
        "phone": ["Soitettu potilaalle ja kerrottu TT-angiografian tuloksista. Toimenpideaika lähetetään kirjeitse.",
                  "Potilas soitti ja kysyi leikkausajasta. Ohjattu odottamaan kutsukirjettä.",
                  "Kontrollisoitto: haava parantunut ja kävelymatka pidentynyt, ei uusia oireita."],
    },
    "I71": {
        "reason": ["Vatsa-aortan aneurysman seuranta", "Sattumalöydöksenä todettu vatsa-aortan laajentuma",
                   "Vatsa-aortan aneurysman leikkausarvio"],
        "anamnesis": [
            "Vatsa-aortan aneurysma löytynyt sattumalta muun syyn vuoksi tehdyssä vatsan TT:ssä.",
            "Ei vatsa- tai selkäkipuja, ei muita uusia oireita.",
            "Sepelvaltimotauti, pallolaajennus tehty aiemmin, ei rintakipuja nykyisin.",
            "Isällä ollut vatsa-aortan aneurysma.",
            "Liikkuu omatoimisesti, kävelee päivittäin noin kilometrin.",
        ],
        "status": [
            "Vatsa pehmeä ja aristamaton, napakorkeudella palpoituu pulsoiva resistenssi.",
            "Verenpaine {systolic}/{diastolic}, syke {pulse}.",
            "Alaraajojen pulssit tuntuvat molemmin puolin.",
        ],
        "imaging": [
            "TT-angiossa infrarenaalinen aneurysma, maksimiläpimitta {diameter} mm, kasvua edellisestä noin {growth} mm. Proksimaalinen kaula {neck} mm.",
            "Vatsa-aortan UÄ:ssä aortan suurin poikkimitta {diameter} mm.",
            "Iliakavaltimot kapeat ja kalkkeutuneet.",
        ],
        "plan_operative": [
            "Läpimitta ylittää leikkausrajan, suunnitellaan EVAR. Anatomia soveltuu stenttigraftille.",
            "Kaula lyhyt ja kulmautunut, joten suositellaan avointa korjausta Y-proteesilla.",
            "Asia käsitelty verisuonimeetingissä, puolletaan korjausta.",
        ],
        "plan_conservative": [
            "Aneurysma alle leikkausrajan, seurantakuvaus vuoden kuluttua.",
            "Verenpaine hyvään hoitotasapainoon ja tupakoinnin lopetus.",
            "Ohjeistettu hakeutumaan päivystykseen, jos tulee äkillinen vatsa- tai selkäkipu.",
        ],
        "control_operative": [
            "Kontrolli-TT:ssä ei endovuotoa, aneurysmapussi pienentynyt.", "Haavat parantuneet siististi.",
            "Toipunut hyvin, kävelee päivittäin.",
        ],
        "control_conservative": [
            "Seuranta-UÄ:ssä läpimitta {diameter_later} mm.", "Ei oireita.", "Seuranta jatkuu vuoden välein.",
        ],
        "daily": ["Nivusten punktiokohdat siistit.", "Suolen toiminta käynnistymässä, ilmoja tulee.",
                  "Vatsa pehmeä, haava siisti.", "Diureesi riittävä, kreatiniini {creatinine}."],
        "phone": ["Soitettu potilaalle ja kerrottu seurantakuvauksen tuloksesta. Aneurysma ennallaan.",
                  "Potilas soitti, ollut lievää selkäkipua. Ohjattu päivystykseen arvioon.",
                  "Kontrollisoitto: toipunut hyvin, ei vatsakipuja."],
    },
    "I65": {
        "reason": ["TIA-oire, kaulavaltimoahtauma", "Oireinen kaulavaltimoahtauma", "Kaulavaltimoahtauman leikkausarvio"],
        "anamnesis": [
            "{symptom_days} päivää sitten {other_gen} käden kömpelyyttä ja puheen puuroutumista noin {symptom_minutes} minuutin ajan, oireet korjaantuneet täysin.",
            "Ohimenevä näönmenetys {side_ine} silmässä, kuin verho olisi laskeutunut silmän eteen.",
            "Hoidettu neurologian päivystyksessä TIA:na, aloitettu klopidogreeli ja statiini.",
            "Ei aiempia aivoverenkiertohäiriöitä.",
        ],
        "status": [
            "Neurologisesti nyt oireeton, ei puolieroja, puhe selkeää.",
            "Kaulalla {side_ade} puolella heikko sivuääni.",
            "Verenpaine {systolic}/{diastolic}, rytmi tasainen.",
        ],
        "imaging": [
            "Kaulasuonten doppler-UÄ:ssä {side_gen} ACI:n tyvessä noin {stenosis} % ahtauma, vastapuolella alle {other_stenosis} %.",
            "TT-angiossa {side_gen} ACI:n tyvessä kalkkeutunut plakki ja merkittävä ahtauma, intrakraniaaliset suonet aukeat.",
            "Pään TT:ssä ei tuoretta infarktia.",
        ],
        "plan_operative": [
            "Oireinen yli 70 % ahtauma, suunnitellaan {side_gen} puolen karotisendarterektomia kahden viikon sisällä oireesta.",
            "Leikkaus mahdollisesti paikallispuudutuksessa, anestesian arvio pyydetty.",
        ],
        "plan_conservative": [
            "Oireeton ahtauma, jatketaan konservatiivista hoitoa ja seurataan UÄ:llä.",
            "Lääkehoito optimoitu, ei leikkausindikaatiota.",
        ],
        "control_operative": [
            "Ei uusia neurologisia oireita.", "Kaulan haava parantunut siististi.", "Lievä tunnottomuus leuan alla, korjaantumassa.",
        ],
        "control_conservative": ["Ei uusia oireita.", "Seuranta-UÄ:ssä ahtauma ennallaan."],
        "daily": ["Neurologisesti oireeton, ei puolieroja.", "Kaulan haava siisti, ei hematoomaa.",
                  "Dreeni poistettu, eritettä vähän.", "Verenpaine tasapainossa."],
        "phone": ["Soitettu potilaalle ja kerrottu leikkausajasta.",
                  "Kontrollisoitto: ei uusia oireita, haava parantunut."],
    },
    "I83": {
        "reason": ["Alaraajojen suonikohjut", "{side_gen_cap} alaraajan laskimovajaatoiminta", "Suonikohjujen hoitoarvio"],
        "anamnesis": [
            "Suonikohjut {side_ine} säären sisäsivulla jo vuosien ajan, iltaisin särkyä ja turvotusta.",
            "Kohjut pahentuneet raskauksien jälkeen.",
            "Ei aiempia laskimotukoksia eikä pinnallisia laskimotulehduksia.",
            "Työssä paljon seisomista, tukisukat käytössä osittain.",
            "Säären alaosassa ihon tummumista ja kutinaa.",
        ],
        "status": [
            "{side_gen_cap} säären mediaalipuolella runsaasti varikoosia, CEAP C{ceap}.",
            "Nilkoissa lievää turvotusta, ihossa ei haavaumia.",
            "Malleolien seudussa hemosideriinipigmentaatiota.",
        ],
        "imaging": [
            "Laskimoiden UÄ:ssä VSM:n insuffisienssi nivustaipeesta polven alapuolelle, läpimitta {vsm_mm} mm. Syvät laskimot aukeat ja kompressoituvat.",
            "VSP normaali, perforanttien insuffisienssia säären alaosassa.",
        ],
        "plan_operative": [
            "Suunnitellaan VSM:n radiotaajuusablaatio ja kohjujen poisto päiväkirurgisesti.",
            "Oireinen laskimovajaatoiminta, hoito puollettu.",
        ],
        "plan_conservative": [
            "Kohjut ensisijaisesti kosmeettinen haitta, ei hoitoindikaatiota. Ohjattu tukisukkahoitoon.",
            "Vaahtoskleroterapia poliklinikalla myöhemmin.",
        ],
        "control_operative": ["Kohjut hävinneet, lievää kiristystä reidellä.", "Mustelmat haihtuneet.", "Ei tukoksen merkkejä."],
        "control_conservative": ["Tukisukat auttaneet särkyyn.", "Kohjut ennallaan."],
        "daily": ["Kotiutuu samana päivänä.", "Kompressiosidos paikallaan."],
        "phone": ["Soitettu potilaalle, toimenpideaika sovittu.",
                  "Kontrollisoitto: kohjut hävinneet, tyytyväinen tulokseen."],
    },
    "I74": {
        "reason": ["Akuutti alaraajaiskemia", "{side_gen_cap} jalan äkillinen kipu ja kylmyys"],
        "anamnesis": [
            "Noin {hours} tuntia sitten alkanut äkillinen {side_gen} jalan kipu, kylmyys ja puutuminen.",
            "Eteisvärinä, antikoagulaatio ollut tauolla hammastoimenpiteen vuoksi.",
            "Aiemmin kävelykykyinen ilman rajoitteita.",
        ],
        "status": [
            "{side_nom_cap} jalka kalpea ja kylmä polvesta alaspäin, pulssit eivät tunnu nivusesta alkaen.",
            "Tunto heikentynyt jalkaterässä, varpaiden liikkeet säilyneet.",
            "Syke epäsäännöllinen {pulse}/min.",
        ],
        "imaging": ["TT-angiossa {side_gen} a. femoralis communiksen embolus, distaalinen täyttyminen heikko."],
        "plan_operative": ["Päivystyksellinen trombembolektomia, hepariini-infuusio aloitettu.",
                           "Leikkauksen jälkeen antikoagulaatio jatkuu, kardiologin konsultaatio."],
        "plan_conservative": ["Iskemia lievä, aloitetaan hepariini ja seurataan tiiviisti."],
        "control_operative": ["Jalka lämmin, kävelee rollaattorilla.", "Antikoagulaatio jatkuu tauotta."],
        "control_conservative": ["Jalka lämmin, oireet helpottaneet."],
        "daily": ["Jalka lämmin, hepariini-infuusio jatkuu, APTT hoitotasolla.", "Säären lihakset pehmeät, ei aitio-oireyhtymän merkkejä.",
                  "Nivushaava siisti."],
        "phone": ["Kontrollisoitto: jalka lämmin, antikoagulaatio jatkuu."],
    },
}

DAILY_GENERAL = [
    "Yö mennyt rauhallisesti.", "Kivut hallinnassa suun kautta otettavilla kipulääkkeillä.",
    "Haava siisti, ei vuotoa eikä punoitusta.", "Mobilisoitu fysioterapeutin kanssa, kävelee rollaattorilla osastolla.",
    "Syö ja juo normaalisti.", "Lämpö {temperature} astetta, CRP {crp}.", "Verenpaine {systolic}/{diastolic}, syke {pulse}.",
]

DAILY_PLAN = ["Jatketaan nykyisellä hoidolla.", "Kotiutus huomenna, jos vointi sallii.", "Mobilisaatiota jatketaan.",
              "Kipulääkitystä vähennetään.", "Kontrollilaboratoriot huomenna aamulla."]

OPERATION_DESCRIPTIONS = {
    "pta": "Ultraääniohjattu antegradinen punktio {side_gen} a. femoralis communikseen, 6F holkki. Okkluusio ylitetty johtimella ja pallolaajennettu {balloon} mm pallolla. Jäännösahtauman vuoksi asetettu stentti {stent} x {stent_length} mm. Loppukuvauksessa hyvä virtaus distaaliseen suonistoon. Hemostaasi sulkulaitteella.",
    "bypass": "Nivusviilto {side_ade} puolella, a. femoralis communis esille. VSM preparoitu reideltä ja todettu hyvälaatuiseksi. Distaalinen anastomoosi polvitaipeen alapuolelle a. poplitealle, proksimaalinen anastomoosi AFC:hen. Siirteessä hyvä virtaus, jalkaterässä dopplersignaali. Haavat suljettu kerroksittain.",
    "amputation": "Säären amputaatio {side_ade} puolella pitkällä takaläpällä. Lihakset vitaalit, verenvuoto vähäistä. Sääriluu viistetty, hermot katkaistu korkealta. Haava suljettu dreenin kanssa.",
    "evar": "Molemmat nivuset punktoitu ultraääniohjatusti, preclose-tekniikka. Stenttigraftin runko-osa viety munuaisvaltimoiden alapuolelle, kontralateraalinen haara kanyloitu ja asetettu. Loppukuvauksessa ei endovuotoa. Punktiot suljettu.",
    "open_aaa": "Keskiviilto, transperitoneaalinen lähestyminen. Aortta suljettu infrarenaalisesti, aneurysma avattu ja lumbaalivaltimot ommeltu. Y-proteesi {graft} mm anastomosoitu aorttaan ja iliakoihin. Verenvuoto {blood} ml. Vatsa suljettu.",
    "cea": "Viilto m. sternocleidomastoideuksen etureunaan {side_ade} puolella. ACC, ACI ja ACE esille. Hepariini ja puristimet. Arteriotomia ACC:stä ACI:hin, plakki poistettu endarterektomialla. Paikka-angioplastia. Puristimet auki, hyvä virtaus. Haava suljettu dreenin kanssa.",
    "rfa": "Ultraääniohjattu VSM:n punktio polven tasolta. Katetri viety safenofemoraaliliitoksen alapuolelle, tumesenssipuudutus. Radiotaajuusablaatio {rfa_cm} cm matkalta. Kohjut poistettu mikroviilloista. Kompressiosidos.",
    "thrombectomy": "Nivusviilto {side_ade} puolella, AFC esille. Fogarty-katetrilla poistettu runsaasti tuoretta trombia proksimaalisesti ja distaalisesti. Hyvä takaisinvirtaus. Loppukuvauksessa säären suonet täyttyvät. Fasciotomia ei tarpeen.",
}


# ---------------------------------------------------------------------------
# Medications
# ---------------------------------------------------------------------------

# atc, substance, strength, form, amount, route, dose, unit, schedule, purpose, narcotic
MEDICINES = {
    "asa": ("B01AC06", "asetyylisalisyylihappo", "100 mg", "tabletti", "1 tabletti", "PO", 100, "mg", "x 1 /vrk klo 8", "Valtimotaudin estohoito", False),
    "clopidogrel": ("B01AC04", "klopidogreeli", "75 mg", "tabletti", "1 tabletti", "PO", 75, "mg", "x 1 /vrk klo 8", "Valtimotaudin estohoito", False),
    "atorvastatin": ("C10AA05", "atorvastatiini", "40 mg", "tabletti", "1 tabletti", "PO", 40, "mg", "x 1 /vrk klo 20", "Kolesterolin alentaminen", False),
    "rivaroxaban_low": ("B01AF01", "rivaroksabaani", "2,5 mg", "tabletti", "1 tabletti", "PO", 2.5, "mg", "x 2 /vrk klo 8 ja 20", "Valtimotaudin estohoito", False),
    "rivaroxaban_af": ("B01AF01", "rivaroksabaani", "20 mg", "tabletti", "1 tabletti", "PO", 20, "mg", "x 1 /vrk klo 18", "Eteisvärinä", False),
    "bisoprolol": ("C07AB07", "bisoprololi", "5 mg", "tabletti", "1 tabletti", "PO", 5, "mg", "x 1 /vrk klo 8", "Kohonnut verenpaine", False),
    "ramipril": ("C09AA05", "ramipriili", "5 mg", "tabletti", "1 tabletti", "PO", 5, "mg", "x 1 /vrk klo 8", "Kohonnut verenpaine", False),
    "metformin": ("A10BA02", "metformiini", "500 mg", "tabletti", "1 tabletti", "PO", 500, "mg", "x 2 /vrk klo 8 ja 20", "Tyypin 2 diabetes", False),
    "paracetamol": ("N02BE01", "parasetamoli", "1 g", "tabletti", "1 tabletti", "PO", 1, "g", "x 3 /vrk klo 8, 14 ja 20", "Kipu", False),
    "oxycodone": ("N02AA05", "oksikodoni", "5 mg", "kapseli", "1 kapseli", "PO", 5, "mg", "tarvittaessa enintään 6 kertaa vuorokaudessa", "Kipu", True),
    "enoxaparin": ("B01AB05", "enoksapariini", "40 mg/0,4 ml", "injektioneste", "0,4 ml", "SC", 40, "mg", "x 1 /vrk klo 20", "Laskimotukosten esto", False),
    "cefuroxime": ("J01DC02", "kefuroksiimi", "1,5 g", "injektiokuiva-aine", "1,5 g", "IV", 1.5, "g", "x 3 /vrk klo 6, 14 ja 22", "Infektion estohoito", False),
}

ROUTE_TEXT = {"PO": "suun kautta", "SC": "ihon alle", "IV": "laskimoon"}
ROUTE_CODES = {"PO": "15", "SC": "18", "IV": "11"}
MEDICINE_CLARITY_IDS = {key: 100000 + number * 1373 for number, key in enumerate(MEDICINES)}
ADMINISTRATION_HOURS = {"paracetamol": [8, 14, 20], "cefuroxime": [6, 14, 22], "enoxaparin": [20]}
WEEKDAY_SHORT = ["ma", "ti", "ke", "to", "pe", "la", "su"]


def add_medicine(patient, key, start, end, shjakso_id, unit, stop_reason):
    """One prescription; returns its laakemaarays_id."""
    atc, substance, strength, form, amount, route, dose, dose_unit, schedule, purpose, narcotic = MEDICINES[key]
    dose_text = comma_text(dose, 1).replace(",0", "")
    instruction = "%s %s %s, %s, ensimmäinen annos %s %s klo %d:%02d, %s, Käyttötarkoitukset: %s" % (
        dose_text, dose_unit, ROUTE_TEXT[route], schedule, WEEKDAY_SHORT[start.weekday()],
        start.strftime("%d.%m.%y"), start.hour, start.minute,
        "kunnes lopetetaan" if end is None else "hoitojakson ajan", purpose)
    inpatient = end is not None
    prescription_id = next_id("laakemaarays", 40000000)
    add_row("Apotti_laakitys",
            henkilotunnus=patient["henkilotunnus"], laakemaarays_id=prescription_id,
            shjakso_id=shjakso_id, alku_hetki=start, loppu_hetki=end,
            kirjaaja_toimipiste_eala_koodi="20", kirjaaja_toimipiste_eala_selite="Kirurgia",
            kirjaaja_toimipiste_koodi=unit_code(unit, 8), kirjaaja_toimipiste_selite=unit,
            laakemaarays_tila_koodi="2" if inpatient else "1",
            laakemaarays_tila_selite="Päättynyt" if inpatient else "Aktiivinen",
            laakemaarays_luokka_koodi="1", laakemaarays_luokka_selite="Normaali",
            laake_clarity_id=MEDICINE_CLARITY_IDS[key], atc_koodi=atc, vaikuttava_aine=substance,
            vahvuus=strength, muoto=form, maara=amount,
            antotapa_koodi=ROUTE_CODES[route], antotapa_lyhenne=route, antotapa_selite=ROUTE_TEXT[route],
            annostelu_annos=float(dose), annostelu_annos_yksikko=dose_unit,
            annostelu_tyyppi_selite="Tarvittaessa" if "tarvittaessa" in schedule else "Säännöllinen",
            annostelu_erillis_ohje=instruction,
            annostelu_minimi_annos=5.0 if key == "oxycodone" else None,
            annostelu_maksimi_annos=10.0 if key == "oxycodone" else None,
            narkoottinen_laake=narcotic, biologinen_laake=False, veriplasma_valmiste=False,
            biosimilaari_laake=False, lopetus_syy_koodi="10" if stop_reason else None, lopetus_syy_selite=stop_reason,
            laakemaarays_lahde_apotti_koodi="110" if inpatient else "100",
            laakemaarays_lahde_apotti_selite="Osastolla" if inpatient else "Avohoito")
    return prescription_id


def add_administrations(patient, key, prescription_id, start, end, shjakso_id, unit):
    """Ward administration records for one prescription (Apotti_laakitys_antokirjaus)."""
    atc, substance, strength, form, amount, route, dose, dose_unit, schedule, purpose, narcotic = MEDICINES[key]
    row_number = 0
    day = datetime(start.year, start.month, start.day)
    while day <= end:
        if key == "oxycodone":
            hours = sorted(generator.sample(range(7, 23), between(0, 3)))  # As needed
        else:
            hours = ADMINISTRATION_HOURS[key]
        for hour in hours:
            moment = day + timedelta(hours=hour, minutes=between(0, 40))
            if moment < start or moment > end:
                continue
            row_number += 1
            given = chance(0.95)
            add_row("Apotti_laakitys_antokirjaus",
                    henkilotunnus=patient["henkilotunnus"], laakemaarays_id=prescription_id, rivi_id=row_number,
                    shjakso_id=shjakso_id, alku_hetki=moment,
                    loppu_hetki=moment + timedelta(minutes=30) if route == "IV" else moment,
                    kirjaaja_toimipiste_koodi=unit_code(unit), kirjaaja_toimipiste_selite=unit,
                    kirjaaja_toimipiste_eala_koodi="20", kirjaaja_toimipiste_eala_selite="Kirurgia",
                    potilas_pituus=patient["height"], potilas_paino=patient["weight"],
                    laake_clarity_id=MEDICINE_CLARITY_IDS[key], atc_koodi=atc, vaikuttava_aine=substance,
                    vahvuus=strength, muoto=form, annos=float(dose) if given else None, annos_yksikko=dose_unit,
                    antotapa_koodi=ROUTE_CODES[route], antotapa_lyhenne=route, antotapa_selite=ROUTE_TEXT[route],
                    antokirjaus_tapahtuma="Annettu" if given else "Jätetty antamatta",
                    antokirjaus_status_tarkenne=None if given else pick(["Potilas kieltäytyi", "Potilas nukkui"]),
                    narkoottinen_laake=narcotic, biologinen_laake=False, veriplasma_valmiste=False,
                    biosimilaari_laake=False)
        day += timedelta(days=1)


def home_medicines(patient):
    """Regular medicines implied by diagnosis group and comorbidities."""
    keys = []
    arterial = patient["group_key"] in ("I70", "I71", "I65", "I74")
    atrial_fibrillation = "I48.9" in patient["comorbidities"]
    if atrial_fibrillation:
        keys.append("rivaroxaban_af")
    elif arterial:
        keys.append("asa")
    if patient["group_key"] == "I65":
        keys.append("clopidogrel")
    if patient["group_key"] == "I70" and not atrial_fibrillation and chance(0.3):
        keys.append("rivaroxaban_low")
    if arterial or "E78.0" in patient["comorbidities"]:
        keys.append("atorvastatin")
    if "I10" in patient["comorbidities"]:
        keys.append(pick(["ramipril", "bisoprolol"]))
    if "I25.1" in patient["comorbidities"] and "bisoprolol" not in keys:
        keys.append("bisoprolol")
    if "E11.9" in patient["comorbidities"]:
        keys.append("metformin")
    return keys


def medicine_list_text(keys):
    parts = []
    for key in keys:
        atc, substance, strength, form, amount, route, dose, dose_unit, schedule, purpose, narcotic = MEDICINES[key]
        parts.append("%s %s %s" % (substance, strength, schedule.split(" klo")[0]))
    return ", ".join(parts) if parts else "Ei säännöllistä lääkitystä."


# ---------------------------------------------------------------------------
# Laboratory
# ---------------------------------------------------------------------------

# Short name, long name, municipal number, unit, low, high, typical low, typical high, decimals
# (the long name is written with the specimen prefix, e.g. "B -Hemoglobiini", as in the export)
LAB_TESTS = [
    ("B -Hb", "Hemoglobiini", "1552", "g/l", 117, 167, 105, 160, 0),
    ("B -Leuk", "Leukosyytit", "2208", "E9/l", 3.4, 8.2, 4.5, 11.5, 1),
    ("B -Trom", "Trombosyytit", "2280", "E9/l", 150, 360, 140, 380, 0),
    ("P -Krea", "Kreatiniini", "4413", "umol/l", 50, 100, 55, 160, 0),
    ("P -K", "Kalium", "3471", "mmol/l", 3.3, 4.9, 3.4, 5.1, 1),
    ("P -Na", "Natrium", "3474", "mmol/l", 137, 145, 133, 144, 0),
    ("P -CRP", "C-reaktiivinen proteiini", "4520", "mg/l", 0, 3, 1, 40, 0),
    ("fP -Kol-LDL", "LDL-kolesteroli", "4516", "mmol/l", 0, 3.0, 1.2, 3.8, 1),
]


LAB_PANELS = {"B -Hb": ("2474", "B -PVKT", "B -Perusverenkuva ja trombosyytit"),
              "B -Leuk": ("2474", "B -PVKT", "B -Perusverenkuva ja trombosyytit"),
              "B -Trom": ("2474", "B -PVKT", "B -Perusverenkuva ja trombosyytit")}
LAB_SPECIALTY = "Kemia, hematologia, hyytymistutkimukset"


def lab_abbreviation(unit):
    """Osasto M12, Tornisairaala -> OSA3P (the real codes look like AAA9A)."""
    letters = re.sub(r"[^A-ZÅÄÖ]", "", unit.upper())
    return letters[:3] + unit_code(unit, 1) + "P"


def lab_context(patient, moment, unit):
    """Sample IDs, timestamps and places shared by every row of one sample."""
    laboratory = "HUS DIAGNOSTIIKKAKESKUS KLIININEN KEMIA, " + SOTE_NAMES[patient["hospital_name"]].upper()
    general_id = next_id("yleinen_nayte", 710000000)
    done = moment + timedelta(minutes=between(30, 180))
    return {
        "ids": dict(multilab_potilas_id=patient["multilab_id"], multilab_nayte_id=next_id("multilab_nayte", 700000000),
                    myplus_yleinen_nayte_id=general_id, ulkoinen_jarjestelma_nayte_id=general_id),
        "times": dict(pyynto_hetki=moment - timedelta(hours=between(1, 20)), naytteenotto_hetki=moment,
                      teko_hetki=done, lahetys_hetki=done + timedelta(minutes=between(1, 20))),
        "places": dict(pyytava_toimipiste_koodi=unit_code(unit), pyytava_toimipiste_lyhenne=lab_abbreviation(unit),
                       pyytava_toimipiste_selite=unit.upper(),
                       naytteenotto_toimipiste_koodi=unit_code(unit), naytteenotto_toimipiste_lyhenne=lab_abbreviation(unit),
                       naytteenotto_toimipiste_selite=unit.upper(),
                       tekopaikka_toimipiste_koodi=unit_code(laboratory), tekopaikka_toimipiste_lyhenne="HUSLAB",
                       tekopaikka_toimipiste_selite=laboratory),
        "changed": done + timedelta(minutes=between(20, 60)),
    }


def add_laboratory(patient, moment, unit, after_operation=False):
    sample = lab_context(patient, moment, unit)
    tests = list(LAB_TESTS)
    if "E11.9" in patient["comorbidities"]:
        tests.append(("B -HbA1c", "Hemoglobiini A1c", "6164", "mmol/mol", 20, 42, 45, 75, 0))
    if "I48.9" in patient["comorbidities"]:
        tests.append(("P -INR", "Tromboplastiiniaika, INR", "2955", "", 0.7, 1.2, 0.9, 1.6, 1))
    for short_name, long_name, number, lab_unit, low, high, typical_low, typical_high, decimals in tests:
        if short_name == "fP -Kol-LDL" and after_operation:
            continue
        value = generator.uniform(typical_low, typical_high)
        if short_name == "P -CRP" and after_operation:
            value = generator.uniform(20, 160)
        if short_name == "B -Hb" and after_operation:
            value -= generator.uniform(5, 20)
        value = round(value, decimals) if decimals else int(round(value))
        statement = None
        if short_name == "P -K" and chance(0.03):
            statement = "Näyte lievästi hemolyyttinen, tulos voi olla virheellisesti koholla."
        specimen = short_name.split(" -")[0]
        panel = LAB_PANELS.get(short_name, (number, short_name, specimen + " -" + long_name))
        add_row("Multilab_tulos",
                henkilotunnus=patient["henkilotunnus"], tulos_id=next_id("tulos", 900000000),
                suorite_id=next_id("suorite", 30000000), potilas_ika_vuosina=age_at(patient, moment),
                tutkimus_kuntaliiton_numero=number, tutkimus_lyhenne=short_name,
                tutkimus_pitkanimi=specimen + " -" + long_name, tutkimus_eala_selite=LAB_SPECIALTY,
                paatutkimus_kuntaliiton_numero=panel[0], paatutkimus_lyhenne=panel[1], paatutkimus_pitkanimi=panel[2],
                paatutkimus_eala_selite=LAB_SPECIALTY, tulos=value, yksikko=lab_unit or None,
                viitearvot="%s-%s" % (low, high), ala_viitearvo=float(low), yla_viitearvo=float(high),
                tulos_viitearvo_ulkopuolella=not (low <= value <= high), tulos_epavarma=False,
                lausunto=statement, tutkimus_lisatietoja=False, tutkimus_mikrobituloksia=False,
                viimeinen_muutos_hetki=sample["changed"], **sample["ids"], **sample["times"], **sample["places"])
    # Urine dipstick with its sub-results in the lisatieto table
    if chance(0.4):
        result_id = next_id("tulos", 900000000)
        add_row("Multilab_tulos",
                henkilotunnus=patient["henkilotunnus"], tulos_id=result_id, suorite_id=next_id("suorite", 30000000),
                potilas_ika_vuosina=age_at(patient, moment), tutkimus_kuntaliiton_numero="1881",
                tutkimus_lyhenne="U -KemSeul", tutkimus_pitkanimi="U -Kemiallinen seulonta",
                tutkimus_eala_selite=LAB_SPECIALTY, paatutkimus_kuntaliiton_numero="1881",
                paatutkimus_lyhenne="U -KemSeul", paatutkimus_pitkanimi="U -Kemiallinen seulonta",
                paatutkimus_eala_selite=LAB_SPECIALTY, tulos="Katso lisätiedot", tulos_epavarma=False,
                tutkimus_lisatietoja=True, tutkimus_mikrobituloksia=False, viimeinen_muutos_hetki=sample["changed"],
                **sample["ids"], **sample["times"], **sample["places"])
        for number, heading in enumerate(["U -Gluk-O", "U -Prot-O", "U -Leuk-O", "U -Nitr-O", "U -Eryt-O"], start=1):
            answer = "negat"
            if heading == "U -Gluk-O" and "E11.9" in patient["comorbidities"] and chance(0.4):
                answer = "+"
            if heading == "U -Leuk-O" and chance(0.15):
                answer = pick(["+", "++"])
            add_row("Multilab_tulos_lisatieto",
                    henkilotunnus=patient["henkilotunnus"], tulos_id=result_id, lisatieto_id=number,
                    tutkimus_kuntaliiton_numero="1881", tutkimus_lyhenne="U -KemSeul",
                    tutkimus_pitkanimi="U -Kemiallinen seulonta, liuskatesti", tutkimus_eala_selite=LAB_SPECIALTY.lower(),
                    tulos=answer, tutkimus_lisatieto_otsikko=heading, tutkimus_lisatieto_teksti=None,
                    viimeinen_muutos_hetki=sample["changed"], **sample["ids"], **sample["times"])


# WHONET name, susceptibility comment, short name, long name, group, WHONET code, WHONET short
MICROBES = [
    ("Staphylococcus aureus", "Kefaleksiini = S, Kloksasilliini = S, Klindamysiini = S", "STA.AUREUS", "STAPHYLOC AUREUS", "STAPH. AUREUS", "1201", "sau"),
    ("Escherichia coli", "Ampisilliini = R, Kefuroksiimi = S, Siprofloksasiini = S", "ESC.COLI", "ESCHERICH COLI", "ENTEROBAKT.", "2301", "eco"),
    ("Proteus mirabilis", "Ampisilliini = S, Kefuroksiimi = S, Trimetopriimi = R", "PRO.MIRABI", "PROTEUS MIRABILIS", "ENTEROBAKT.", "2341", "pmi"),
    ("Pseudomonas aeruginosa", "Keftatsidiimi = S, Siprofloksasiini = S, Piperasilliini-tatsobaktaami = S", "PSE.AERUGI", "PSEUDOMON AERUGINOSA", "PSEUD. AERUG", "2501", "pae"),
    ("Enterococcus faecalis", "Ampisilliini = S, Vankomysiini = S", "ENT.FAECAL", "ENTEROCOC FAECALIS", "ENTEROKOKIT", "1401", "efa"),
    ("Streptococcus dysgalactiae", "Penisilliini = S, Klindamysiini = S", "STR.DYSGAL", "STREPTOC DYSGALACTIAE", "STREPT. BETA", "1302", "sdy"),
]


def add_culture(patient, moment, sample_type):
    """Wound/pus or urine culture with 0-2 findings."""
    if sample_type == "pus":
        number, short_name, long_name = "1950", "Pu-BaktVi1", "Pu-Bakteeriviljely, aerobinen 1"
    else:
        number, short_name, long_name = "1302", "U -BaktVi1", "U -Bakteeriviljely 1"
    sample = lab_context(patient, moment, patient["hospital"]["ward"])
    result_id = next_id("tulos", 900000000)
    findings = generator.sample(MICROBES, between(0, 2))
    common = dict(henkilotunnus=patient["henkilotunnus"], tulos_id=result_id, tutkimus_kuntaliiton_numero=number,
                  tutkimus_lyhenne=short_name, tutkimus_pitkanimi=long_name,
                  tutkimus_eala_selite="mikrobiologia, bakteriologia, viljelytutkimukset",
                  loydos_tyyppi_koodi="100", loydos_tyyppi_selite="viljelylöydös",
                  alkup_mikrobitulostaulu="m1tulos_%d" % moment.year, viimeinen_muutos_hetki=sample["changed"] + timedelta(days=2))
    if not findings:
        add_row("Multilab_tulos_mikrobi", mikrobi_tulos_id=1, tulos="negat", loydos_positiivinen=False,
                kommentti_loydoskohtainen="Ei kasvua.", **common, **sample["ids"], **sample["times"])
    for row_number, (microbe, comment, short, long, group, whonet_code, whonet_short) in enumerate(findings, start=1):
        add_row("Multilab_tulos_mikrobi", mikrobi_tulos_id=row_number, tulos="posit", maara=pick(["+", "++", "+++"]),
                loydos_positiivinen=True, kommentti_loydoskohtainen=comment, mikrobi_lyhenne=short,
                mikrobi_pitkanimi=long, mikrobi_ryhma_koodi=whonet_code[:2], mikrobi_ryhma_selite=group,
                mikrobikanta_koodi=whonet_code[:2], mikrobikanta_selite=group, mikrobi_whonet_koodi=whonet_code,
                mikrobi_whonet_lyhenne=whonet_short, mikrobi_whonet_selite=microbe,
                **common, **sample["ids"], **sample["times"])


# ---------------------------------------------------------------------------
# Patient
# ---------------------------------------------------------------------------

def make_patient(used_henkilotunnus):
    group_key = pick_weighted({key: GROUPS[key]["share"] for key in GROUPS})
    group = GROUPS[group_key]
    hospital_name = pick_weighted(group["hospital_weights"])
    hospital = HOSPITALS[hospital_name]

    # Dates and identity
    span_days = (LAST_REFERRAL_DATE - FIRST_REFERRAL_DATE).days
    referral_day = FIRST_REFERRAL_DATE + timedelta(days=between(0, span_days))
    age = max(25, min(95, int(round(generator.gauss(group["age_mean"], group["age_sd"])))))
    birth_date = referral_day - timedelta(days=age * 365 + between(10, 350))
    sex_code = "1" if chance(group["male_share"]) else "2"

    # Comorbidities
    comorbidities = [code for code, probability in group["comorbidity"].items() if chance(probability)]

    # Side and clinical numbers, fixed per patient so notes agree with each other
    side = pick(["oikea", "vasen"])
    other = "vasen" if side == "oikea" else "oikea"
    context = {
        "side_nom": SIDES[side]["nom"], "side_gen": SIDES[side]["gen"], "side_ine": SIDES[side]["ine"],
        "side_ade": SIDES[side]["ade"], "side_gen_cap": capitalise(SIDES[side]["gen"]),
        "side_nom_cap": capitalise(SIDES[side]["nom"]),
        "other_nom": SIDES[other]["nom"], "other_gen": SIDES[other]["gen"],
        "other_gen_cap": capitalise(SIDES[other]["gen"]),
        "walk_m": pick([50, 100, 150, 200, 300, 400, 500]),
        "walk_m_later": pick([400, 500, 800, 1000]),
        "abi_side": comma_text(generator.uniform(0.35, 0.75), 2),
        "abi_other": comma_text(generator.uniform(0.75, 1.10), 2),
        "abi_post": comma_text(generator.uniform(0.85, 1.05), 2),
        "ulcer_weeks": between(3, 12), "ulcer_mm": between(5, 20), "cigs": between(5, 20),
        "quit_years": between(2, 20), "toe_pressure": between(20, 60), "occl_cm": between(5, 20),
        "psv": between(250, 450), "diameter": between(42, 68), "growth": between(2, 8), "neck": between(10, 30),
        "stenosis": pick([70, 75, 80, 85, 90, 95]), "other_stenosis": pick([30, 50]),
        "symptom_days": between(2, 10), "symptom_minutes": between(5, 30),
        "ceap": between(2, 4), "vsm_mm": between(6, 11), "hours": between(3, 12),
        "systolic": between(120, 175), "diastolic": between(65, 95), "pulse": between(55, 95),
        "balloon": between(4, 6), "stent": between(5, 7), "stent_length": pick([60, 80, 100, 120, 150]),
        "graft": pick(["16 x 8", "18 x 9", "20 x 10"]), "blood": between(6, 30) * 50, "rfa_cm": between(25, 45),
        "creatinine": between(60, 140), "temperature": comma_text(generator.uniform(36.5, 38.0), 1),
        "crp": between(5, 120),
    }
    context["diameter_later"] = context["diameter"] + between(1, 4)

    # Treatment decision
    operated = chance(group["operation_share"])
    procedure_key = pick_weighted(group["procedures"]) if operated else None
    if group_key == "I71" and operated and context["diameter"] < 55:
        context["diameter"] = between(55, 68)
    if group_key == "I71" and not operated:
        context["diameter"] = between(40, 52)
        context["diameter_later"] = context["diameter"] + between(1, 3)

    asa = between(1, 2) if group_key == "I83" else between(2, 4)
    town = pick(hospital["towns"])
    sex_text = SEX_TEXT[sex_code]
    height = round(generator.gauss(176, 7) if sex_code == "1" else generator.gauss(163, 6), 2)
    weight = round(generator.gauss(84, 13) if sex_code == "1" else generator.gauss(72, 13), 3)

    # Pseudonym used in every table except MOCK_avainlista
    henkilotunnus = make_henkilotunnus(birth_date, used_henkilotunnus)
    pseudo_id = "%s_%07d" % (STUDY_NUMBER, between(1000000, 9999999))
    while pseudo_id in PSEUDO_IDS.values():
        pseudo_id = "%s_%07d" % (STUDY_NUMBER, between(1000000, 9999999))
    PSEUDO_IDS[henkilotunnus] = pseudo_id

    return {
        "henkilotunnus": henkilotunnus,
        "pseudo_id": pseudo_id, "multilab_id": next_id("multilab", 3000000), "bcb_id": next_id("bcb", 10000),
        "sex_text": sex_text, "height": height, "weight": weight, "contacts": {},
        "group_key": group_key, "group": group, "hospital_name": hospital_name, "hospital": hospital,
        "style": hospital["style"], "referral_day": referral_day, "age": age, "birth_date": birth_date,
        "sex_code": sex_code, "comorbidities": comorbidities, "side": side, "context": context,
        "operated": operated, "procedure_key": procedure_key, "asa": asa, "town": town,
        "note_contacts": {}, "diagnosed_contacts": set(),
    }


def age_at(patient, moment):
    return int((moment - patient["birth_date"]).days // 365.25)


# ---------------------------------------------------------------------------
# Contacts (care episodes) and notes
# ---------------------------------------------------------------------------

def new_contact(patient, kind, unit, start, end, visit_type="first"):
    """One care episode (shjakso). kind = Käynti, Puhelu or Sisäänkirjausjakso."""
    contact = {"shjakso_id": next_id("shjakso", 50000000), "ohjakso_id": next_id("ohjakso", 80000000),
               "kayntitili_id": next_id("kayntitili", 60000000), "hoiko_id": next_id("hoiko", 61000000),
               "kind": kind, "unit": unit, "start": start, "end": end, "visit_type": VISIT_TYPES[visit_type]}
    patient["contacts"][contact["shjakso_id"]] = contact
    return contact


def add_note(patient, contact, tab, unit, specialty, moment, text):
    patient["note_contacts"].setdefault(contact["shjakso_id"], moment)  # For per-episode diagnosis rows
    updated = moment + timedelta(minutes=between(0, 90)) if chance(0.6) else moment + timedelta(days=between(1, 3), minutes=between(0, 600))
    role = pick(ROLE_BY_TAB.get(tab, PHYSICIAN_ROLES))
    header = NOTE_HEADER.format(role=role, name=staff_member(patient["hospital_name"], role),
                                moment=moment.strftime("%d.%m.%Y %H:%M"))
    visit_code, visit_text = contact["visit_type"]
    add_row("Apotti_potilaskertomus",
            henkilotunnus=patient["henkilotunnus"], shjakso_id=contact["shjakso_id"],
            kontaktityyppi_koodi=CONTACT_TYPE_CODES[contact["kind"]], kontaktityyppi_selite=contact["kind"],
            kayntityyppi_koodi=visit_code, kayntityyppi_selite=visit_text,
            toimipiste_koodi=unit_code(unit, 8), toimipiste_selite=unit,
            toimipiste_eala_koodi=SPECIALTY_CODE if specialty == SPECIALTY_TEXT else "22",
            toimipiste_eala_selite=specialty,
            shjakso_alku_hetki=contact["start"], shjakso_loppu_hetki=contact["end"],
            merkinta_id=next_id("merkinta", 90000000), merkinta_valilehti_koodi=NOTE_TAB_CODES[tab],
            merkinta_valilehti_selite=tab, merkinta_luonti_hetki=moment, merkinta_paivitys_hetki=updated,
            merkinta_teksti=header + "\n" + text)


def history_text(patient, style):
    names = [COMORBIDITIES[code][1] for code in patient["comorbidities"]]
    if not names:
        return "Ei merkittäviä perussairauksia."
    if style == "B":
        return ", ".join(names) + "."
    return "\n".join("- " + name for name in names) if style == "A" else "\n".join(names)


def outpatient_note(patient, moment, first_visit, operative_plan, medicines):
    bank = BANKS[patient["group_key"]]
    context = patient["context"]
    if first_visit:
        sections = [
            ("reason", pick(bank["reason"]).format(**context)),
            ("history", history_text(patient, patient["style"])),
            ("medication", medicine_list_text(medicines)),
            ("anamnesis", join_some(bank["anamnesis"], 2, 4, context)),
            ("status", join_some(bank["status"], 2, 3, context)),
            ("imaging", join_some(bank["imaging"], 1, 2, context)),
            ("plan", plan_text(patient, operative_plan)),
        ]
    else:
        key = "control_operative" if patient["operated"] else "control_conservative"
        sections = [
            ("reason", "Kontrollikäynti"),
            ("anamnesis", join_some(bank[key], 1, 3, context)),
        ]
        if not patient["operated"]:
            sections.append(("status", join_some(bank["status"], 1, 2, context)))
        sections += [
            ("plan", pick(["Kontrolli vuoden kuluttua.", "Jatkoseuranta terveyskeskuksessa, ei säännöllistä kontrollia verisuonikirurgialla.",
                           "Seuranta päättyy, uusi lähete tarvittaessa.", "Kontrolli puolen vuoden kuluttua kuvantamisen kera."])),
        ]
    return render_note(patient["style"], sections, moment)


PLAN_BY_PROCEDURE = {
    "pta": "Suunnitellaan {side_gen} AFS-alueen PTA ja tarvittaessa stentti angiosalissa.",
    "bypass": "Pitkä okkluusio, ei sovellu endovaskulaariseen hoitoon. Suunnitellaan femoropopliteaalinen ohitus laskimosiirteellä, laskimokartoitus pyydetty.",
    "amputation": "Kuolio etenevä eikä revaskularisaatiomahdollisuutta ole. Suunnitellaan {side_gen} säären amputaatiota, asiasta keskusteltu potilaan ja omaisen kanssa.",
    "evar": "Läpimitta ylittää leikkausrajan. Anatomia soveltuu stenttigraftille, suunnitellaan EVAR.",
    "open_aaa": "Läpimitta ylittää leikkausrajan. Kaula lyhyt ja kulmautunut, joten suositellaan avointa korjausta Y-proteesilla.",
    "cea": "Oireinen yli 70 % ahtauma, suunnitellaan {side_gen} puolen karotisendarterektomia kahden viikon sisällä oireesta.",
    "rfa": "Oireinen laskimovajaatoiminta. Suunnitellaan VSM:n radiotaajuusablaatio ja kohjujen poisto päiväkirurgisesti.",
    "thrombectomy": "Päivystyksellinen trombembolektomia, hepariini-infuusio aloitettu.",
}

# Extra plan sentences that never contradict the chosen procedure
PLAN_EXTRAS = ["Ohjattu tupakoinnin lopettamisesta.", "Asia käsitelty verisuonimeetingissä.",
               "Toimenpideaika lähetetään kirjeitse.", "Antitromboottinen lääkitys jatkuu."]


def plan_text(patient, operative_plan):
    bank = BANKS[patient["group_key"]]
    context = patient["context"]
    if not operative_plan:
        return join_some(bank["plan_conservative"], 1, 2, context)
    text = PLAN_BY_PROCEDURE[patient["procedure_key"]].format(**context)
    if chance(0.5):
        text += " " + pick(PLAN_EXTRAS)
    return text


def nurse_note(patient, moment):
    context = patient["context"]
    pain = between(0, 6)
    if patient["style"] == "B":
        text = "Vointi hyvä. Kipu NRS %d, annettu oksikodonia 5 mg. RR %d/%d, p %d, SpO2 %d %%. Haavasidos kuiva. Liikkuu rollaattorilla." % (
            pain, context["systolic"] + between(-15, 15), context["diastolic"] + between(-8, 8), context["pulse"] + between(-10, 10), between(92, 99))
        return abbreviate(text)
    lines = [
        "Kipu: NRS %d, %s." % (pain, pick(["annettu oksikodonia 5 mg tarvittaessa", "parasetamoli riittänyt", "kivut hallinnassa"])),
        "Aktiviteetti: %s." % pick(["Liikkuu rollaattorin kanssa itsenäisesti", "Tarvitsee yhden hoitajan avun siirtymisissä", "Istunut tuolissa aterioiden ajan"]),
        "Erittäminen: %s." % pick(["Virtsaa omatoimisesti", "Virtsakatetri poistettu, virtsaa omatoimisesti", "Ulostanut"]),
        "Kudoseheys: %s." % pick(["Haavasidos kuiva", "Haavasidos vaihdettu, haava siisti", "Punktiokohta siisti"]),
        "Elintoiminnot: RR %d/%d, syke %d, SpO2 %d %%." % (
            context["systolic"] + between(-15, 15), context["diastolic"] + between(-8, 8), context["pulse"] + between(-10, 10), between(92, 99)),
    ]
    count = between(3, 5)
    return "\n".join(lines[:count])


def daily_note(patient, moment, day_number, last_day):
    bank = BANKS[patient["group_key"]]
    context = dict(patient["context"])
    context["crp"] = between(10, 150) if day_number <= 2 else between(5, 60)
    sections = [
        ("day", str(day_number)),
        ("condition", join_some(DAILY_GENERAL, 2, 3, context)),
        ("status", join_some(bank["daily"], 1, 2, context)),
        ("plan", "Kotiutus tänään." if last_day else pick(DAILY_PLAN)),
    ]
    return render_note(patient["style"], sections, moment, footer=False)


def operation_note(patient, moment, anaesthesia):
    procedure = PROCEDURES[patient["procedure_key"]]
    context = patient["context"]
    sections = [
        ("procedure", "%s, %s puoli" % (procedure["text"], context["side_nom"]) if patient["procedure_key"] not in ("evar", "open_aaa") else procedure["text"]),
        ("anaesthesia", anaesthesia),
        ("indication", pick(BANKS[patient["group_key"]]["reason"]).format(**context)),
        ("description", OPERATION_DESCRIPTIONS[patient["procedure_key"]].format(**context)),
        ("instructions", "Kompressiosidos 2 vrk, sen jälkeen tukisukka 2 viikkoa. Kotiin samana päivänä." if patient["procedure_key"] == "rfa"
         else pick(["Tavanomainen postoperatiivinen seuranta osastolla.", "Antitromboottinen lääkitys jatkuu.",
                    "Haavakontrolli ja ompeleiden poisto 10-14 vrk kuluttua."])),
    ]
    return render_note(patient["style"], sections, moment, footer=False)


def discharge_note(patient, moment, start, end, medicines, follow_up):
    procedure = PROCEDURES[patient["procedure_key"]]
    sections = [
        ("summary", "Potilas oli osastohoidossa %s-%s, jolloin tehtiin %s." % (short_date(start), short_date(end), lower_first(procedure["text"]))),
        ("course", pick(["Toipuminen oli komplikaatioton.", "Toisena päivänä lievää kuumeilua, joka korjaantui ilman antibioottia.",
                         "Haavassa lievää punoitusta, aloitettu kefaleksiini.", "Hemoglobiini laski leikkauksen jälkeen, ei verensiirtoja."])),
        ("medication", medicine_list_text(medicines + ["paracetamol"])),
        ("instructions", "Jatkohoitopaikka: %s. Ompeleet poistetaan terveyskeskuksessa %d päivän kuluttua. Kontrolli verisuonikirurgian poliklinikalla %s." % (
            follow_up, between(10, 14), pick(["6 viikon kuluttua", "3 kuukauden kuluttua", "puhelimitse 4 viikon kuluttua"]))),
    ]
    return render_note(patient["style"], sections, moment)


def consultation_note(patient, moment, anaesthesia):
    sections = [
        ("reason", "Preoperatiivinen anestesia-arvio"),
        ("history", history_text(patient, patient["style"])),
        ("status", "ASA %d. %s" % (patient["asa"], pick(["EKG:ssä sinusrytmi.", "EKG:ssä eteisvärinä, kammiovaste tasainen.", "Sydän ja keuhkot auskultoiden normaalit."]))),
        ("plan", "Sopii %s. %s" % (illative(anaesthesia),
                                   pick(["Antikoagulaatio tauotetaan kaksi vuorokautta ennen toimenpidettä.", "ASA jatkuu tauotta.", "Ei erityistä."]))),
    ]
    return render_note(patient["style"], sections, moment, footer=False)


def illative(anaesthesia):
    """Yleisanestesia -> yleisanestesiaan, Spinaalipuudutus -> spinaalipuudutukseen."""
    word = lower_first(anaesthesia)
    if word.endswith("us"):
        return word[:-2] + "ukseen"
    return word + "an"


def phone_note(patient, moment):
    text = pick(BANKS[patient["group_key"]]["phone"])
    return render_note(patient["style"], [("phone", text)], moment)


# ---------------------------------------------------------------------------
# Imaging
# ---------------------------------------------------------------------------

IMAGING = {
    "I70": [("Alaraajavaltimoiden TT-angiografia", "ct"), ("Alaraajavaltimoiden doppler-ultraäänitutkimus", "us")],
    "I71": [("Vatsa-aortan TT-angiografia", "ct"), ("Vatsa-aortan ultraäänitutkimus", "us")],
    "I65": [("Kaulavaltimoiden doppler-ultraäänitutkimus", "us"), ("Kaulavaltimoiden TT-angiografia", "ct")],
    "I83": [("Alaraajan laskimoiden ultraäänitutkimus", "us")],
    "I74": [("Alaraajavaltimoiden TT-angiografia", "ct")],
}

FINDINGS = {
    ("I70", "ct"): ("Vatsa-aortta normaalikaliiperinen, seinämässä kalkkeutumia. Iliakavaltimot aukeat. {side_gen_cap} AFS:n keskiosassa noin {occl_cm} cm pitkä okkluusio, distaalinen täyttyminen polvitaipeen tasolta kollateraalien kautta. Säären valtimoista a. tibialis anterior ja a. fibularis aukeat, a. tibialis posterior tukossa. {other_gen_cap} puolella AFS:ssä lievä ahtauma.",
                    "{side_gen_cap} AFS:n noin {occl_cm} cm okkluusio. Vastapuolella ei merkittävää ahtaumaa."),
    ("I70", "us"): ("{side_gen_cap} AFS:n distaaliosassa merkittävä ahtauma, maksimivirtausnopeus {psv} cm/s. Distaalisesti monofaasinen virtauskäyrä. Iliakoissa trifaasinen virtaus.",
                    "{side_gen_cap} AFS:n distaaliosan merkittävä ahtauma."),
    ("I71", "ct"): ("Infrarenaalinen vatsa-aortan aneurysma, maksimiläpimitta {diameter} mm. Proksimaalinen kaula {neck} mm, kulmautuminen lievä. Seinämätrombia. Iliakavaltimot kalkkeutuneet. Ei merkkejä repeämästä.",
                    "Infrarenaalinen AAA {diameter} mm."),
    ("I71", "us"): ("Vatsa-aortan suurin poikkimitta infrarenaalisesti {diameter} mm. Iliakavaltimot normaalikaliiperiset.",
                    "Vatsa-aortan aneurysma {diameter} mm."),
    ("I65", "us"): ("{side_gen_cap} ACI:n tyvessä heterogeeninen plakki, virtausnopeus vastaa noin {stenosis} % ahtaumaa. {other_gen_cap} ACI:ssa alle {other_stenosis} % ahtauma. Vertebralikset antegradiset.",
                    "{side_gen_cap} ACI:n noin {stenosis} % ahtauma."),
    ("I65", "ct"): ("Aortan kaari ja sen haarat aukeat. {side_gen_cap} ACI:n tyvessä kalkkeutunut plakki, NASCET-kriteerein noin {stenosis} % ahtauma. Willisin rengas täydellinen.",
                    "{side_gen_cap} ACI:n merkittävä ahtauma."),
    ("I83", "us"): ("{side_gen_cap} VSM:n refluksi safenofemoraaliliitoksesta polven alapuolelle, läpimitta reiden keskiosassa {vsm_mm} mm. VSP:ssä ei refluksia. Syvät laskimot aukeat ja kompressoituvat, ei trombia.",
                    "{side_gen_cap} VSM:n insuffisienssi. Ei syvän laskimon tukosta."),
    ("I74", "ct"): ("{side_gen_cap} a. femoralis communiksen ja proksimaalisen AFS:n täyttymisvaje, sopii embolukseen. Distaalinen täyttyminen niukka. Vastapuolen valtimot aukeat.",
                    "{side_gen_cap} AFC:n embolus."),
}

IMAGING_CODES = {
    "Alaraajavaltimoiden TT-angiografia": "NN1BT", "Alaraajavaltimoiden doppler-ultraäänitutkimus": "NN1UD",
    "Vatsa-aortan TT-angiografia": "PD1BT", "Vatsa-aortan ultraäänitutkimus": "PD1UA",
    "Kaulavaltimoiden doppler-ultraäänitutkimus": "PA1UD", "Kaulavaltimoiden TT-angiografia": "PA1BT",
    "Alaraajan laskimoiden ultraäänitutkimus": "PH1UD",
}

REQUESTS = {
    "I70": "Katkokävely {side_ade} puolella, ABI {abi_side}. Pyydän valtimoiden kuvantamisen revaskularisaation suunnittelua varten.",
    "I71": "Tunnettu vatsa-aortan aneurysma. Läpimitan seuranta, onko kasvanut?",
    "I65": "TIA-oire, kaulavaltimoahtaumaepäily {side_ade} puolella. Ahtauman aste?",
    "I83": "Suonikohjut {side_ade} puolella. Refluksin kartoitus toimenpiteen suunnittelua varten.",
    "I74": "Äkillinen alaraajaiskemia {side_ade} puolella. Embolus?",
}


def add_imaging(patient, moment, study, kind, ordering_contact, done_contact, urgent):
    hospital = patient["hospital"]
    context = patient["context"]
    order_id = next_id("maarays", 600000000)
    parent_order = next_id("maarays", 600000000) if chance(0.3) else None
    accession = next_id("ac", 1000000000)
    priority = ("1", "(P) Päivystys") if urgent else pick([("6", "(N) Kiireetön"), ("2", "(K) Kiireellinen")])
    saved = moment - timedelta(days=between(1, 30)) if not urgent else moment - timedelta(hours=between(1, 3))
    request = REQUESTS[patient["group_key"]].format(**context)
    if patient["style"] == "B":
        request = abbreviate(request)
    elif patient["style"] == "C":
        request = "Kysymys: " + request
    # Real requests start with the priority and the time the order was saved
    request = "%s, %s %s klo %s %s" % (priority[1], WEEKDAY_SHORT[saved.weekday()],
                                       "%d.%d.%s" % (saved.day, saved.month, saved.strftime("%y")),
                                       saved.strftime("%H:%M"), request)
    site = hospital["radiology"]
    device_name = "%s %s %s" % ("SIE", "TT1" if kind == "ct" else "UA2", patient["hospital_name"][:3].upper())
    add_row("Apotti_kuvantaminen_tutkimus",
            henkilotunnus=patient["henkilotunnus"], maarays_id=order_id, ylamaarays_id=parent_order,
            luotu_shjakso_id=ordering_contact["shjakso_id"], tehty_shjakso_id=done_contact["shjakso_id"],
            ac_numero=accession, potilas_ika_vuosina=age_at(patient, moment), toimenpide_hetki=moment,
            toimenpide_koodi=IMAGING_CODES[study], toimenpide_selite=study,
            toimipiste_koodi=hospital["radiology_code"], toimipiste_selite=site,
            lahete_tallennus_hetki=saved, ilmoittautumis_hetki=moment - timedelta(minutes=between(5, 40)),
            lahettaja_toimipiste_koodi=unit_code(hospital["clinic"], 7, "A"),
            lahettaja_toimipiste_selite=hospital["clinic"], prioriteetti_koodi=priority[0], prioriteetti_selite=priority[1],
            liikkuminen_avustus=chance(0.25), eksponointi_lkm=between(1, 3) if kind == "ct" else None,
            kuvantamislaite_id=int(unit_code(device_name, 6)), kuvantamislaite_inventaario_id="L" + unit_code(device_name, 7),
            kuvantamislaite_selite=device_name, kuvantamislaite_sijainti_selite="Röntgen, " + SOTE_NAMES[patient["hospital_name"]],
            pyynto_teksti=request)
    findings, conclusion = FINDINGS[(patient["group_key"], kind)]
    comparison = "Ei aiempia vertailukuvia." if chance(0.6) else "Vertailu %s tutkimukseen." % short_date(moment - timedelta(days=between(180, 700)))
    report = "%s\n\nKliiniset tiedot: %s\n\nVertailu: %s\n\nLöydökset:\n%s\n\nJohtopäätös:\n%s" % (
        study.upper(), REQUESTS[patient["group_key"]].format(**context), comparison,
        findings.format(**context), conclusion.format(**context))
    add_row("Apotti_kuvantaminen_lausunto",
            ac_numero=accession, henkilotunnus=patient["henkilotunnus"], maarays_id=order_id, ylamaarays_id=parent_order,
            shjakso_id=done_contact["shjakso_id"], lausunto_hetki=moment + timedelta(hours=between(1, 48)),
            lausuja_ammatti_selite="radiologi", lausunto_teksti=report)


# ---------------------------------------------------------------------------
# One patient's whole pathway
# ---------------------------------------------------------------------------

SPECIALTY_TEXT = "Verisuonikirurgia"
SPECIALTY_CODE = "20V"
SPECIALTY_LABEL = "20V Verisuonikirurgia"


def add_visit_row(patient, contact, visit_type, moment, unit, booking=None, day_surgery=False):
    group = patient["group"]
    code, text = KAYNTI_TYPES[visit_type]
    if booking is None:
        booking = ("PUH 15min", "Puhelinaika, 15 min") if visit_type == "Soitto" else ("VOK 30min", "Vastaanottokäynti, 30 min")
    emergency = patient["group_key"] == "I74" and contact["visit_type"] == VISIT_TYPES["first"]
    add_row("Apotti_kaynti",
            henkilotunnus=patient["henkilotunnus"], shjakso_id=contact["shjakso_id"], ohjakso_id=contact["ohjakso_id"],
            ohjakso_jarn=1, kayntitili_id=contact["kayntitili_id"], hoiko_id=contact["hoiko_id"],
            potilas_ika_vuosina=age_at(patient, moment), kayntityyppi_koodi=code, kayntityyppi_selite=text,
            varaustyyppi_koodi=booking[0], varaustyyppi_selite=booking[1], paivakirurgia=day_surgery,
            alku_hetki=moment, loppu_hetki=contact["end"], toimipiste_koodi=unit_code(unit, 8, "A"),
            toimipiste_selite=unit, potilas_eala_koodi=SPECIALTY_CODE, potilas_eala_selite=SPECIALTY_LABEL,
            paadiagnoosi_koodi=group["code"], paadiagnoosi_selite=group["text"],
            sivudiagnoosi_lista=LIST_SEPARATOR.join(patient["comorbidities"]) or None,
            tulotapa_koodi="2" if emergency else "1", tulotapa_selite="Päivystys" if emergency else "Ajanvaraus",
            mista_tuli_koodi="01", mista_tuli_selite="Koti, ilman säännöllisiä palveluja",
            tulosyy_koodi_lista=group["code"][:3], tulosyy_selite_lista=group["text"],
            lahettaja_koodi=unit_code(patient["referrer_unit"], 10), lahettaja_selite=patient["referrer_unit"],
            jatkohoito_koodi="01", jatkohoito_selite="Koti ilman säännöllisiä palveluja")


def add_procedure_row(patient, contact, moment, unit, visit_type, text, asa_code=None):
    clinic = patient["hospital"]["clinic"]
    code, visit_text = KAYNTI_TYPES[visit_type]
    add_row("Apotti_toimenpide",
            henkilotunnus=patient["henkilotunnus"], shjakso_id=contact["shjakso_id"] if chance(0.9) else None,
            tuotepaatos_id=next_id("tuotepaatos", 70000000), hoitokontakti_id=next_id("hoitokontakti", 20000000),
            suorite_id=next_id("suorite", 30000000), toimenpidekokonaisuus_id=next_id("kokonaisuus", 10000000),
            potilas_ika_vuosina=age_at(patient, moment), toimenpide_hetki=moment,
            potilas_eala_koodi=SPECIALTY_CODE, potilas_eala_selite=SPECIALTY_TEXT,
            tilaava_toimipiste_koodi=unit_code(clinic, 8), tilaava_toimipiste_selite=clinic,
            toteuttava_toimipiste_koodi=unit_code(unit), toteuttava_toimipiste_selite=unit,
            kayntityyppi_koodi=code, kayntityyppi_selite=visit_text,
            potilas_sukupuoli_koodi=patient["sex_code"], potilas_sukupuoli_selite=patient["sex_text"],
            potilas_kotikunta_koodi=MUNICIPALITY_CODES[patient["town"]], potilas_kotikunta_selite=patient["town"],
            toimenpide_koodi=OUTPATIENT_PROCEDURE_CODES[text], toimenpide_selite=text,
            paatoimenpide=True, uusinta_toimenpide=False, asa_luokka_koodi=asa_code,
            suoritelaji_koodi="10", suoritelaji_selite="Muu toimenpidesuorite",
            paivitys_hetki=moment + timedelta(hours=between(1, 72)))


def add_referral(patient):
    group = patient["group"]
    hospital = patient["hospital"]
    arrived = at_time(patient["referral_day"], 8, 15)
    urgent = patient["group_key"] == "I74"
    old_name, new_name, health_centres = REFERRERS[patient["town"]]
    organisation = new_name if arrived >= WELLBEING_AREAS_START else old_name
    if patient["group_key"] == "I65" and chance(0.7):
        referrer_specialty, referrer_unit, organisation = "77 Neurologia", "Neurologian päivystys, Meilahden sairaala", "HUS"
    elif urgent:
        referrer_specialty, referrer_unit = "98 Yleislääketiede", "Yhteispäivystys, " + SOTE_NAMES[patient["hospital_name"]]
        organisation = "HUS"
    else:
        referrer_specialty, referrer_unit = "98 Yleislääketiede", pick(health_centres) + ", " + organisation
    patient["referrer_unit"] = referrer_unit
    returned = patient["group_key"] == "I83" and not patient["operated"] and chance(0.5)
    handled = arrived + timedelta(days=0 if urgent else between(1, 10), hours=between(0, 5))
    if urgent:
        urgency = ("1", "Päivystys")
    else:
        urgency = pick([("2", "1-7 päivää"), ("3", "8-30 päivää"), ("4", "Kiireetön"), ("4", "Kiireetön")])
    state = ("3", "Palautettu") if returned else pick([("1", "Hyväksytty"), ("2", "Suljettu")])
    doctor = staff_member(organisation, "Lääkäri")
    hus = organisation == "HUS"
    clinic = hospital["clinic"]
    sote = SOTE_NAMES[patient["hospital_name"]]
    referral = add_row("Apotti_lahete",
            henkilotunnus=patient["henkilotunnus"], lahete_id=next_id("lahete", 7000000),
            lahete_cressida_id=next_id("cressida", 3000000), hoiko_id=next_id("hoiko", 61000000),
            lahete_saapumis_pvm=arrived, kasittely_hetki=handled,
            lahete_hyvaksytty_ensimmainen_kerta_hetki=None if returned else handled,
            palautus_hetki=handled if returned else None,
            hoito_arvioitu_alku_hetki=None if returned else handled + timedelta(days=between(7, 60)),
            hoitopaatos_pvm=None if returned else handled,
            potilas_eala_koodi=SPECIALTY_CODE, potilas_eala_selite=SPECIALTY_LABEL,
            lahettaja_eala_koodi=referrer_specialty[:2], lahettaja_eala_selite=referrer_specialty,
            lahettaja_toimipiste_koodi=unit_code(referrer_unit), lahettaja_toimipiste_oid_koodi=oid(referrer_unit),
            lahettaja_toimipiste_selite=referrer_unit, lahettaja_toimipiste_topi_koodi=unit_code(referrer_unit, 5),
            lahettaja_toimipiste_tulosalue="77 NEUROKESKUS TULOSALUE" if hus and "Neuro" in referrer_unit else None,
            lahettaja_koodi=unit_code(organisation, 8), lahettaja_oid_koodi=oid(organisation),
            lahettaja_selite=organisation, lahettaja_ytunnus=unit_code(organisation + "y", 7),
            lahettaja_topi_koodi=unit_code(organisation, 5),
            lahettaja_tyyppi_koodi="1", lahettaja_tyyppi_selite="Julkinen",
            toimipiste_koodi=unit_code(clinic), toimipiste_oid_koodi=oid(clinic), toimipiste_selite=clinic,
            sote_toimipiste_koodi=unit_code(sote, 5), sote_toimipiste_oid_koodi=oid(sote), sote_toimipiste_selite=sote,
            lahete_tyyppi_koodi="1", lahete_tyyppi_selite="Lähete erikoissairaanhoitoon",
            tila_koodi=state[0], tila_selite=state[1], peruttu=False,
            lahete_suljettu_syy_koodi="1" if state[1] == "Suljettu" else None,
            lahete_suljettu_syy_selite="Hoidettu" if state[1] == "Suljettu" else None,
            hoitotakuu_hoiko_koodi=None if urgent else "1001", hoitotakuu_hoiko_selite=None if urgent else "Hoitotakuu",
            lahettaja_henkilo_koodi="L" + unit_code(doctor, 7),
            lahettaja_henkilo_hus_koodi="HUS" + unit_code(doctor, 8) if hus else None,
            lahettaja_henkilo_nimi=doctor, lahettaja_henkilo_nimike="Lääkäri",
            lahete_kiireellisyysluokka_koodi=urgency[0], lahete_kiireellisyysluokka_selite=urgency[1],
            lahete_paadiagnoosi_koodi=group["code"], lahete_paadiagnoosi_selite=group["text"],
            lahete_sivudiagnoosit_lista_koodi=LIST_SEPARATOR.join(patient["comorbidities"]) or None,
            lahete_sivudiagnoosit_lista_selite=LIST_SEPARATOR.join(COMORBIDITIES[code][0] for code in patient["comorbidities"]) or None,
            lahete_suunta_koodi="1", lahete_suunta_selite="Saapuva",
            lahete_tulotapa_koodi="1", lahete_tulotapa_selite="ESH",
            palautus_syy_koodi="2" if returned else ("1" if chance(0.3) else None),
            palautus_syy_selite="Ei erikoissairaanhoidon kriteerejä" if returned else None,
            luotu_hetki=arrived, paivitys_hetki=handled + timedelta(days=between(0, 5)))
    patient["referral_row"] = referral
    return arrived, returned


def add_diagnoses(patient, moment, contact, include_comorbidities=True):
    """Main diagnosis (plus comorbidities at the first visit) recorded on one care episode."""
    group = patient["group"]
    codes = [(group["code"], group["text"], True, False)]
    if include_comorbidities:
        codes += [(code, COMORBIDITIES[code][0], False, True) for code in patient["comorbidities"]]
    shjakso_id = contact["shjakso_id"] if contact else None
    patient["diagnosed_contacts"].add(shjakso_id)
    decision_id = next_id("tuotepaatos", 70000000)
    entity_id = next_id("diagnoosikokonaisuus", 72000000)
    for order, (code, text, main, chronic) in enumerate(codes, start=1):
        start = moment if main else moment - timedelta(days=between(100, 3000))
        add_row("Apotti_diagnoosi",
                henkilotunnus=patient["henkilotunnus"], shjakso_id=shjakso_id, tuotepaatos_id=decision_id,
                diagnoosi_kokonaisuus=entity_id, tuote_diagnoosi_jarjestys_numero=order,
                potilas_ika_vuosina=age_at(patient, moment), ilmoitettu_alku_hetki=start,
                kontakti_alku_hetki=contact["start"] if contact else None,
                kontakti_loppu_hetki=contact["end"] if contact else None,
                kontakti_toimipiste_koodi=unit_code(contact["unit"]) if contact else None,
                kontakti_toimipiste_selite=contact["unit"] if contact else None,
                kontakti_kayntityyppi_koodi="%02d" % int(contact["visit_type"][0]) if contact else None,
                kontakti_kayntityyppi_selite=contact["visit_type"][1] if contact else None,
                potilas_sukupuoli_koodi=patient["sex_code"], potilas_sukupuoli_selite=patient["sex_text"],
                diagnoosi_koodi=code, diagnoosi_selite=text, paadiagnoosi=main, pitkaaikaisdiagnoosi=chronic,
                paivitys_hetki=moment + timedelta(days=between(0, 30)))


def add_body_measurements(patient, moment):
    for repeat in range(between(1, 3)):
        when = moment - timedelta(days=between(0, 400))
        weight = round(patient["weight"] + generator.uniform(-3, 3), 3)
        add_row("Asiakas_BMI",
                henkilotunnus=patient["henkilotunnus"], sukupuoli=patient["sex_text"],
                ika_mittaushetkella=age_at(patient, when), pituus=patient["height"], paino=weight,
                bmi=round(weight / (patient["height"] / 100) ** 2, 2), mittaus_pvm=when,
                lahdejarjestelma="apotti hoitotyö")
    for repeat in range(between(2, 5)):
        add_row("Asiakas_verenpaine",
                henkilotunnus=patient["henkilotunnus"], lahdejarjestelma_mittaus_selite="VERENPAINE: VP",
                systolinen_verenpaine=patient["context"]["systolic"] + between(-15, 15),
                diastolinen_verenpaine=patient["context"]["diastolic"] + between(-8, 8),
                mittaus_hetki=at_time(moment - timedelta(days=between(0, 500)), 8, 16),
                lahdejarjestelma="apotti_seurantalomake")


BCB_TREATMENT_CLASS = "com.bcbmedical.vascular.treatment.VascT"
BCB_VISIT_CLASS = "com.bcbmedical.vascular.treatment.VascV"


def add_bcb(patient, operation_time, preop_time, control_time, diagnosis_code, procedure_code, minutes):
    """Vascular quality registry rows for an operated patient."""
    treatment_id = next_id("bcb_treatment", 500000)
    patient["bcb_treatment"] = treatment_id
    add_row("BCB_verisuoni_treatment",
            treatment_id=treatment_id, patient_id=patient["bcb_id"], henkilotunnus=patient["henkilotunnus"],
            version=between(1, 6), actual_operation_date=operation_time, asa_class=patient["asa"],
            date_created=preop_time - timedelta(days=between(1, 20)), finished=True,
            last_updated=control_time + timedelta(days=between(0, 30)),
            notes=pick([None, None, "Komplikaatioton", "Haavainfektio, hoidettu antibiootilla", "Reoperaatio vuodon vuoksi", "Siirteen tukos 3 kk"]),
            owner_hospital_id=1, priority=pick([1, 2, 3]), cancelled=False)
    TABLES["BCB_verisuoni_treatment"][-1]["class"] = BCB_TREATMENT_CLASS  # "class" is a Python keyword
    endovascular = PROCEDURES[patient["procedure_key"]]["endovascular"]
    visits = [("preoperative", preop_time), ("operative", operation_time), ("follow_up", control_time)]
    if endovascular:
        visits.insert(1, ("radiological", preop_time + timedelta(days=between(1, 10))))
    for phase, moment in visits:
        visit_id = next_id("bcb_visit", 800000)
        operative = phase == "operative"
        cut = moment + timedelta(minutes=between(20, 45))
        closing = cut + timedelta(minutes=minutes)
        row = add_row("BCB_verisuoni_visit",
                visit_id=visit_id, treatment_id=treatment_id, henkilotunnus=patient["henkilotunnus"],
                patient_id=patient["bcb_id"], version=between(1, 12), asa_class=patient["asa"], cancelled=False,
                date_created=moment - timedelta(days=between(0, 10)), date_visit_finished=moment + timedelta(hours=between(1, 6)),
                date_visited=moment, hospital_id=1, last_updated=moment + timedelta(days=between(0, 5)),
                main_diagnosis_id=diagnosis_code, main_procedure_id=procedure_code if operative else None,
                operating_room_start_time=moment if operative else None,
                operating_room_end_time=closing + timedelta(minutes=between(10, 30)) if operative else None,
                phase_id=phase, priority=pick([1, 2, 3]),
                procedure_start_time=cut if operative else None, procedure_end_time=closing if operative else None,
                ward_id="HUS-" + unit_code(patient["hospital"]["ward"]) if operative else None,
                cut_time=cut if operative else None, wound_closing_time=closing if operative else None,
                care_event_key=next_id("care_event", 900000), care_event_type=1,
                dosedap=round(generator.uniform(1000, 60000), 4) if operative and endovascular else None,
                unitdap="uGy*m2" if operative and endovascular else None,
                radiological_procedure_start_time=cut if operative and endovascular else None,
                radiological_procedure_end_time=closing if operative and endovascular else None)
        row["class"] = BCB_VISIT_CLASS
        if operative:
            patient["bcb_operative_visit"] = visit_id
        add_row("BCB_verisuoni_visit_diagnoses",
                visit_id=visit_id, henkilotunnus=patient["henkilotunnus"], patient_id=patient["bcb_id"], diagnosis_id=diagnosis_code)
        if operative:
            add_row("BCB_verisuoni_visit_procedures",
                    visit_id=visit_id, henkilotunnus=patient["henkilotunnus"], patient_id=patient["bcb_id"], procedure_id=procedure_code)
        # Lower limb questionnaires for limb ischaemia patients
        if patient["group_key"] in ("I70", "I74") and phase in ("preoperative", "follow_up"):
            template = "Preop alaraajakysely" if phase == "preoperative" else "Postop alaraajakysely"
            template_word = "preopquest" if phase == "preoperative" else "postopques"
            better = phase == "follow_up"
            form_id = next_id("bcb_form", 950000)
            questions = [
                ("500 metrin kävely", ["ei_vaikeuksia", "vaikeuksia"] if better else ["ei_lainkaan", "vaikeuksia"],
                 "ei_lainkaan^Ei lainkaan,vaikeuksia^Vaikeuksia,ei_vaikeuksia^Ei vaikeuksia"),
                ("Portaiden nousu", ["ei_vaikeuksia", "vaikeuksia"] if better else ["vaikeuksia", "ei_lainkaan"],
                 "ei_lainkaan^Ei lainkaan,vaikeuksia^Vaikeuksia,ei_vaikeuksia^Ei vaikeuksia"),
                ("Kipu levossa", ["ei"] if better else ["kylla", "ei"], "kylla^Kyllä,ei^Ei"),
                ("Haava jalassa", ["ei"] if better else ["kylla", "ei"], "kylla^Kyllä,ei^Ei"),
                ("Tupakointi", ["tupakoi", "lopettanut", "ei_koskaan"], "tupakoi^Tupakoi,lopettanut^Lopettanut,ei_koskaan^Ei koskaan"),
            ]
            for position, (question, answers, options) in enumerate(questions):
                answer = pick(answers)
                add_row("BCB_verisuoni_form_data",
                        visit_id=visit_id, patient_id=patient["bcb_id"], henkilotunnus=patient["henkilotunnus"],
                        treatment_id=treatment_id, form_id=form_id, client_id="hus", template_code="lowlimb_FI",
                        template_name=template, version=1, date_created=moment, last_updated=moment + timedelta(days=between(0, 5)),
                        qs_pos=position, qg_pos=0, level=0, qs_code="lowlimb_%s_set" % template_word,
                        qg_code="lowlimb_%s_g1" % template_word, question_code="lowlimb_%s_q%d" % (template_word, position + 1),
                        question_name=question, string_answer=answer, list_answer=answer, options=options)


def add_pathology(patient, moment):
    """Specimen from carotid endarterectomy or amputation (Myplus tables)."""
    sample_id = next_id("nayte", 20000000)
    answer_id = next_id("vastaus", 40000000)
    general_id = next_id("yleinen_nayte", 710000000)
    pathology_id = next_id("patologia_nayte", 45000000)
    arrived = moment + timedelta(hours=between(2, 24))
    answered = moment + timedelta(days=between(3, 14))
    context = patient["context"]
    hospital = patient["hospital"]
    pathology_unit = "HUS DIAGNOSTIIKKAKESKUS PATOLOGIA, MEILAHTI"
    if patient["procedure_key"] == "cea":
        statement = "Makroskooppisesti: Endarterektomianäyte, pituus %d mm, kalkkeutunut. Mikroskooppisesti: Ateroskleroottinen plakki, jossa kalkkeutumia, kolesterolikiteitä ja vanhaa vuotoa. Ei malignia kasvua." % between(15, 35)
        diagnosis, m_snomed, organ, t_snomed = "Ateroskleroosi", "M52000", "A. carotis", "T45300"
        form, form_type = "Valtimonäytelomake", "histologialomake"
        answers = [("Näytteen pituus", str(between(15, 35)), "mm", "length"), ("Kalkkeutuminen", "kyllä", None, None)]
    else:
        statement = "Makroskooppisesti: %s säären amputaatio, iho distaalisesti nekroottinen. Mikroskooppisesti: Kuolio ja valtimoissa vaikea ateroskleroosi. Resektiopinnan kudos vitaalia." % capitalise(context["side_gen"])
        diagnosis, m_snomed, organ, t_snomed = "Kuolio", "M54000", "Alaraaja", "Y98000"
        form, form_type = "Amputaationäytelomake", "histologialomake"
        answers = [("Resektiopinnan kudos", "vitaali", None, None), ("Näytteen paino", str(between(1800, 3200)), "g", "tissuesampleweight"),
                   ("Osteomyeliitti", pick(["ei", "ei", "kyllä"]), None, None)]
    ids = dict(henkilotunnus=patient["henkilotunnus"], nayte_id=sample_id, vastaus_id=answer_id,
               myplus_yleinen_nayte_id=general_id, patologia_nayte_id=pathology_id)
    add_row("Myplus_naytetieto",
            suorite_id=next_id("suorite", 30000000), potilas_ika_vuosina=age_at(patient, moment),
            pyynto_hetki=moment - timedelta(hours=between(1, 4)), naytteenotto_hetki=moment,
            nayte_saapumis_hetki=arrived, nayte_vastaus_hetki=answered, nayte_tyyppi="Leikkauspreparaatti",
            nayte_paakategoria="Histologia", tutkimus_kuntaliiton_numero="10530", tutkimus_lyhenne="Ts-PAD-Hist",
            tutkimus_pitkanimi="Ts-PAD-Histologia", tutkimus_eala_selite="Patologia", vastaus_jarjestys_numero=1,
            pyytava_toimipiste_koodi=unit_code(hospital["theatre"]), pyytava_toimipiste_lyhenne=lab_abbreviation(hospital["theatre"]),
            pyytava_toimipiste_selite=hospital["theatre"].upper(),
            naytteenotto_toimipiste_koodi=unit_code(hospital["theatre"], 7, "A"),
            naytteenotto_toimipiste_lyhenne=lab_abbreviation(hospital["theatre"]),
            naytteenotto_toimipiste_nimi=hospital["theatre"].upper(),
            tekopaikka_toimipiste_koodi=unit_code(pathology_unit), tekopaikka_toimipiste_lyhenne="HUSPATOL",
            tekopaikka_toimipiste_nimi=pathology_unit, viimeinen_muutos_hetki=answered, lausunto=statement, **ids)
    add_row("Myplus_diagnoosi",
            diagnoosi_id=next_id("myplus_diagnoosi", 60000000), patologia_rivi_numero=1, m_snomed=m_snomed,
            diagnoosi=diagnosis, diagnoosi_takaliite=pick([", sopiva löydös", None, None]), t_snomed=t_snomed,
            elin=organ, elin_takaliite="#1", viimeinen_muutos_hetki=answered, **ids)
    form_id = next_id("vastauslomake", 50000000)
    for order, (name, value, unit, detail) in enumerate(answers, start=1):
        add_row("Myplus_lausuntolomake",
                vastauslomake_id=form_id, vastauslomake_pohja_id=int(unit_code(form, 6)), vastauslomake_nimi=form,
                vastauslomake_tyyppi=form_type, vastauslomake_jarjestys_numero=order, vastaus_nimi=name,
                vastaus_arvo=value, vastaus_tarkenne=detail, vastaus_yksikko=unit,
                nayte_viimeisin_vastaus_hetki=answered, viimeinen_muutos_hetki=answered, **ids)


def build_pathway(patient):
    hospital = patient["hospital"]
    style = patient["style"]
    group_key = patient["group_key"]
    context = patient["context"]
    urgent = group_key == "I74"

    add_row("MOCK_avainlista", henkilotunnus=patient["henkilotunnus"], pseudo_id=patient["pseudo_id"])

    arrived, returned = add_referral(patient)
    add_body_measurements(patient, arrived)
    medicines = home_medicines(patient)

    # Returned referrals (cosmetic varicose veins): no visits at all
    if returned:
        add_diagnoses(patient, arrived, None)  # No care episode yet
        return

    # First visit (emergency patients go straight in)
    first_visit_time = at_time(arrived + timedelta(days=0 if urgent else between(14, 60)), 8, 15)
    first_contact = new_contact(patient, "Käynti", hospital["clinic"], first_visit_time, first_visit_time + timedelta(minutes=between(20, 45)))
    patient["referral_row"]["shjakso_id"] = first_contact["shjakso_id"]  # The referral opens the first episode
    patient["referral_row"]["kayntitili_id"] = first_contact["kayntitili_id"]
    add_visit_row(patient, first_contact, "Käynti", first_visit_time, hospital["clinic"])
    add_diagnoses(patient, first_visit_time, first_contact)
    for key in medicines:
        add_medicine(patient, key, at_time(first_visit_time - timedelta(days=between(30, 2000)), 8, 16), None, first_contact["shjakso_id"], hospital["clinic"], None)
    add_laboratory(patient, first_visit_time - timedelta(days=between(0, 7), hours=between(1, 3)), hospital["laboratory"])
    if group_key == "I70":
        add_procedure_row(patient, first_contact, first_visit_time, hospital["clinic"], "Käynti", "Nilkka-olkavarsipainesuhteen mittaus")
        if chance(0.25):
            add_culture(patient, first_visit_time, "pus")

    # Imaging before the visit (same day for emergencies)
    studies = IMAGING[group_key]
    number_of_studies = 1 if len(studies) == 1 else between(1, 2)
    for study, kind in studies[:number_of_studies]:
        imaging_time = first_visit_time - timedelta(hours=between(1, 4)) if urgent else at_time(first_visit_time - timedelta(days=between(3, 30)), 8, 16)
        imaging_contact = new_contact(patient, "Käynti", hospital["radiology"], imaging_time, imaging_time + timedelta(minutes=30), "imaging")
        add_imaging(patient, imaging_time, study, kind, first_contact, imaging_contact, urgent)

    add_note(patient, first_contact, "Poliklinikkakäynti", hospital["clinic"], SPECIALTY_TEXT, first_visit_time + timedelta(minutes=between(15, 60)),
             outpatient_note(patient, first_visit_time, True, patient["operated"], medicines))

    if not patient["operated"]:
        # Phone call and a control visit
        call_time = at_time(first_visit_time + timedelta(days=between(7, 40)), 9, 15)
        call_contact = new_contact(patient, "Puhelu", hospital["clinic"], call_time, call_time + timedelta(minutes=10), "phone")
        add_visit_row(patient, call_contact, "Soitto", call_time, hospital["clinic"])
        add_note(patient, call_contact, "Puhelinkontakti", hospital["clinic"], SPECIALTY_TEXT, call_time, phone_note(patient, call_time))
        control_time = at_time(first_visit_time + timedelta(days=between(150, 400)), 8, 15)
        control_contact = new_contact(patient, "Käynti", hospital["clinic"], control_time, control_time + timedelta(minutes=30), "control")
        add_visit_row(patient, control_contact, "Käynti", control_time, hospital["clinic"])
        add_note(patient, control_contact, "Poliklinikkakäynti", hospital["clinic"], SPECIALTY_TEXT, control_time,
                 outpatient_note(patient, control_time, False, False, medicines))
        if chance(0.4) and group_key in ("I71", "I65"):
            study, kind = [item for item in studies if item[1] == "us"][0]
            follow_contact = new_contact(patient, "Käynti", hospital["radiology"], control_time - timedelta(days=7), control_time - timedelta(days=7), "imaging")
            add_imaging(patient, control_time - timedelta(days=between(3, 14)), study, kind, control_contact, follow_contact, False)
        return

    # Operation
    procedure = PROCEDURES[patient["procedure_key"]]
    operation_day = first_visit_time if urgent else first_visit_time + timedelta(days=between(14, 120))
    room_time = at_time(operation_day, 8, 14) if not urgent else first_visit_time + timedelta(hours=between(2, 5))
    ward_days = between(*procedure["ward_days"])
    anaesthesia = pick(procedure["anaesthesia"])
    if procedure["day_surgery"]:
        contact = new_contact(patient, "Käynti", hospital["theatre"], room_time - timedelta(hours=2), room_time + timedelta(hours=5), "theatre")
    else:
        admission = room_time - timedelta(hours=between(2, 16))
        discharge_time = at_time(room_time + timedelta(days=ward_days), 10, 15)
        contact = new_contact(patient, "Sisäänkirjausjakso", hospital["ward"], admission, discharge_time, "ward")

    booked_minutes = 30 * between(2, 8)
    booking = ("LEI %dmin" % booked_minutes, "Leikkaustoimenpide, %d min" % booked_minutes)
    add_visit_row(patient, contact, "Käynti", room_time, hospital["theatre"], booking, procedure["day_surgery"])

    operation_id = next_id("operaatio", 3000000)
    urgency = pick([("110", "LPI"), ("120", "LPII")]) if urgent else pick([("410", "Vihreä"), ("410", "Vihreä"), ("420", "Ruskea")])
    minutes = between(*procedure["minutes"])
    side_label = SIDES[patient["side"]]["label"]
    sided = patient["procedure_key"] not in ("evar", "open_aaa")
    side_code = SIDE_CODES[side_label] if sided else None
    side_text = "%s puoli" % side_label if sided else None
    extra_codes = ([side_code] if sided else []) + (["XRA10"] if procedure["endovascular"] else [])
    extra_texts = ([side_text] if sided else []) + (["Läpivalaisu"] if procedure["endovascular"] else [])
    procedure_type = "endovaskulaarinen" if procedure["endovascular"] else "kirurginen"
    group = patient["group"]
    postop_code, postop_text = (group["code"], group["text"])
    if patient["procedure_key"] == "amputation":
        postop_code, postop_text = "I70.2", "Raajojen valtimoiden ateroskleroosi, kuolio"
    caring_unit = hospital["theatre"] if procedure["day_surgery"] else hospital["ward"]
    next_unit = hospital["icu"] if patient["procedure_key"] == "open_aaa" else caring_unit
    incision = room_time + timedelta(minutes=between(20, 45))
    closure = incision + timedelta(minutes=minutes)
    add_row("Apotti_leikkaus_operaatio",
            henkilotunnus=patient["henkilotunnus"], operaatio_id=operation_id, shjakso_id=contact["shjakso_id"],
            potilas_ika_vuosina=age_at(patient, room_time), vo_hetki=room_time - timedelta(minutes=between(30, 120)),
            operaatio_pvm=room_time, potilas_saliin_hetki=room_time,
            potilas_salista_hetki=closure + timedelta(minutes=between(10, 30)), viilto_hetki=incision, sulku_hetki=closure,
            potilas_eala_koodi=SPECIALTY_CODE, potilas_eala_selite=SPECIALTY_TEXT,
            leikkaus_kiireellisyysluokka_koodi=urgency[0], leikkaus_kiireellisyysluokka_selite=urgency[1],
            paatoimenpide_koodi=procedure["code"], paatoimenpide_selite=procedure["text"], paatoimenpide_tyyppi=procedure_type,
            paatoimenpide_lisakoodit_lista=LIST_SEPARATOR.join(extra_codes) or None,
            paatoimenpide_lisakoodit_selite=LIST_SEPARATOR.join(extra_texts) or None,
            paatoimenpide_puolisuus_koodi=side_code, paatoimenpide_puolisuus_selite=side_text,
            tulotapa_koodi="P" if urgent else "K", tulotapa_selite="Päivystys" if urgent else "Kotoa",
            hoitava_toimipiste_koodi=unit_code(caring_unit), hoitava_toimipiste_apotti_lyhenne=apotti_abbreviation(caring_unit),
            hoitava_toimipiste_selite=caring_unit,
            leikkaava_toimipiste_koodi=unit_code(hospital["theatre"]), leikkaava_toimipiste_selite=hospital["theatre"],
            leikkaussali=THEATRE_ROOM_PREFIX[patient["hospital_name"]] + "%02d" % between(1, 12),
            jatkohoito_toimipiste_koodi=unit_code(next_unit), jatkohoito_toimipiste_apotti_lyhenne=apotti_abbreviation(next_unit),
            jatkohoito_toimipiste_selite=next_unit, ensisijainen_anestesiamuoto=anaesthesia.lower(),
            asa_luokka_koodi="ASA %d" % patient["asa"], asa_luokka_selite=ASA_TEXTS[patient["asa"]],
            puhtausluokka_koodi="10", puhtausluokka_selite="Puhdas",
            preop_diagnoosi_koodi=group["code"], preop_diagnoosi_selite=group["text"],
            postop_diagnoosi_koodi=postop_code, postop_diagnoosi_selite=postop_text)
    items = [(procedure["code"], procedure["text"], True, procedure_type),
             (ANAESTHESIA_CODES[anaesthesia], anaesthesia, False, "anestesia")]
    if procedure["endovascular"]:
        items.append(("XRA10", "Läpivalaisu", False, "radiologinen"))
    for code, item_text, main, item_type in items:
        add_row("Apotti_leikkaus_toimenpide",
                henkilotunnus=patient["henkilotunnus"], operaatio_id=operation_id, shjakso_id=contact["shjakso_id"],
                operaatio_pvm=room_time, paatoimenpide=main, toimenpide_koodi=code, toimenpide_selite=item_text,
                toimenpide_tyyppi=item_type,
                toimenpide_lisakoodit_lista=LIST_SEPARATOR.join(extra_codes) if main and extra_codes else None,
                toimenpide_lisakoodit_selite=LIST_SEPARATOR.join(extra_texts) if main and extra_texts else None,
                toimenpide_puolisuus_koodi=side_code if main else None, toimenpide_puolisuus_selite=side_text if main else None)

    # Pre-operative work-up
    if not urgent:
        preop_time = at_time(room_time - timedelta(days=between(3, 14)), 8, 14)
        preop_contact = new_contact(patient, "Käynti", hospital["theatre"], preop_time, preop_time + timedelta(minutes=30), "theatre")
        add_visit_row(patient, preop_contact, "Käynti", preop_time, hospital["theatre"])
        if patient["asa"] >= 3 or chance(0.3):
            add_note(patient, preop_contact, "Konsultaatio", hospital["theatre"], "Anestesiologia", preop_time + timedelta(minutes=30),
                     consultation_note(patient, preop_time, anaesthesia))
        add_procedure_row(patient, preop_contact, preop_time, hospital["theatre"], "Käynti", "EKG", "ASA %d" % patient["asa"])
        if patient["asa"] >= 3:
            add_procedure_row(patient, preop_contact, preop_time, hospital["radiology"], "Käynti", "Thoraxin röntgen")
        add_laboratory(patient, preop_time - timedelta(hours=between(1, 3)), hospital["laboratory"])
    else:
        preop_time = first_visit_time

    end_of_operation = room_time + timedelta(minutes=minutes)
    add_note(patient, contact, "Leikkauskertomus", hospital["theatre"], SPECIALTY_TEXT, end_of_operation + timedelta(minutes=between(10, 90)),
             operation_note(patient, room_time, anaesthesia))
    antibiotic_end = room_time + timedelta(hours=16)
    prescription_id = add_medicine(patient, "cefuroxime", room_time - timedelta(minutes=30), antibiotic_end, contact["shjakso_id"], hospital["theatre"], "Hoito päättynyt")
    add_administrations(patient, "cefuroxime", prescription_id, room_time - timedelta(minutes=30), antibiotic_end, contact["shjakso_id"], hospital["ward"])

    # Ward stay
    if not procedure["day_surgery"]:
        follow_up = pick(["Koti ilman säännöllisiä palveluja", "Koti ilman säännöllisiä palveluja", "Koti, säännöllinen kotihoito",
                          "Terveyskeskuksen vuodeosasto"])
        first_unit_start = contact["start"]
        units = [(hospital["ward"], first_unit_start, contact["end"])]
        if patient["procedure_key"] == "open_aaa":
            icu_end = end_of_operation + timedelta(hours=between(18, 40))
            units = [(hospital["icu"], end_of_operation, icu_end), (hospital["ward"], icu_end, contact["end"])]
        side_codes = LIST_SEPARATOR.join(patient["comorbidities"]) or None
        ward_ids = [contact["ohjakso_id"]] + [next_id("ohjakso", 80000000) for unit in units[1:]]
        for number, (unit, unit_start, unit_end) in enumerate(units):
            last = number == len(units) - 1
            add_row("Apotti_osastohoito",
                    henkilotunnus=patient["henkilotunnus"], shjakso_id=contact["shjakso_id"],
                    ohjakso_id=ward_ids[number], ohjakso_jarn=number + 1,
                    jatko_ohjakso_id=None if last else ward_ids[number + 1], kayntitili_id=contact["kayntitili_id"],
                    potilas_ika_vuosina=age_at(patient, unit_start), hoiko_id=contact["hoiko_id"],
                    kontakti_vaihe="osastohoito", potilas_eala_koodi=SPECIALTY_CODE, potilas_eala_selite=SPECIALTY_LABEL,
                    ohjakso_toimipiste_koodi=unit_code(unit), ohjakso_toimipiste_selite=unit,
                    ohjakso_tulokirjaus_selite="Sisäänkirjaus" if number == 0 else "Siirto",
                    ohjakso_lahtokirjaus_selite="Kotiutus" if last else "Siirto osastolle",
                    ohjakso_alku_hetki=unit_start, ohjakso_loppu_hetki=unit_end,
                    shjakso_tulosyy_koodi_lista=group["code"][:3], shjakso_tulosyy_selite_lista=group["text"],
                    paadiagnoosi_koodi=postop_code, paadiagnoosi_selite=postop_text, sivudiagnoosi_lista=side_codes,
                    muut_hoitoon_liittyvat_diagnoosit_lista=pick([None, None, "Z95.8", "T81.4", "D62"]),
                    shjakso_tulotapa_koodi="2" if urgent else "1", shjakso_tulotapa_selite="Päivystys" if urgent else "Ajanvaraus",
                    kayntitili_tulotapa_koodi="2" if urgent else "1", kayntitili_tulotapa_selite="Päivystys" if urgent else "Ajanvaraus",
                    shjakso_jatkohoito_toimipiste_selite="Vuodeosasto, " + REFERRERS[patient["town"]][1] if "vuodeosasto" in follow_up else None,
                    shjakso_jatkohoito_koodi="03" if "vuodeosasto" in follow_up else "01",
                    shjakso_jatkohoito_selite=follow_up)

        number_of_days = max(1, (contact["end"].date() - room_time.date()).days)
        for day_number in range(1, number_of_days + 1):
            day = room_time + timedelta(days=day_number)
            day_id = next_id("hoitopaiva", 1000000)
            add_note(patient, contact, "Päivittäismerkintä", hospital["ward"], SPECIALTY_TEXT, at_time(day, 8, 11),
                     daily_note(patient, day, day_number, day_number == number_of_days))
            if chance(0.8):
                add_note(patient, contact, "Hoitotyön merkintä", hospital["ward"], SPECIALTY_TEXT, at_time(day, 13, 21), nurse_note(patient, day))
            measurements = [
                ("Systolinen verenpaine(mmHg)", "R HUS ELINTOIMINNOT SYSTOLINEN (VP)", context["systolic"] + between(-20, 15)),
                ("Diastolinen verenpaine(mmHg)", "R HUS ELINTOIMINNOT DIASTOLINEN (VP)", context["diastolic"] + between(-10, 10)),
                ("Syke(krt/min)", "R HUS ELINTOIMINNOT PULSSI (SYKE)", context["pulse"] + between(-10, 20)),
                ("Lämpö(C)", "R HUS ELINTOIMINNOT LÄMPÖ (TEMP)", round(generator.uniform(36.3, 38.2), 1)),
                ("Happisaturaatio(%)", "R HUS ELINTOIMINNOT SATURAATIO (SPO2)", between(91, 99)),
                ("Kipu NRS(0-10)", "R HUS KIPU NRS (KIPU)", between(0, 7)),
            ]
            if group_key in ("I70", "I74") and day_number == 1:
                for label in ("ABI oikea", "ABI vasen"):
                    operated_side = SIDES[patient["side"]]["label"].lower() in label
                    value = round(generator.uniform(0.85, 1.05) if operated_side else generator.uniform(0.75, 1.1), 2)
                    measurements.append((label, "R HUS VERISUONI %s (ABI)" % label.upper(), value))
            for row_number, (label, system_label, value) in enumerate(measurements, start=1):
                measured = at_time(day, 6, 22)
                add_row("Apotti_seurantalomake",
                        henkilotunnus=patient["henkilotunnus"], hoitopaiva_id=day_id, hoitopaiva_rivi_id=row_number,
                        shjakso_id=contact["shjakso_id"], toimipiste_koodi=unit_code(hospital["ward"], 8),
                        toimipiste_selite=hospital["ward"], kontakti_kirjaus_id=next_id("kontakti_kirjaus", 300000000),
                        mittaus_hetki=measured, kirjaus_hetki=measured + timedelta(minutes=between(0, 45)),
                        arvo=float(value), arvo_tietotyyppi_koodi="2", arvo_tietotyyppi_selite="Numeerinen arvo",
                        mittaus_jarjestelma_id=int(unit_code(system_label, 8)), mittaus_jarjestelma_selite=system_label,
                        mittaus_selite=label, mittaus_lomakepohja_id=1,
                        mittaus_lomakepohja_jarjestelma_selite="HUS ELINTOIMINNOT", mittaus_lomakepohja_selite="Vitaalit",
                        kirjaus_henkilo_ammatti_selite="sairaanhoitaja", kuvaaja=True)
            if day_number == 1:
                add_laboratory(patient, at_time(day, 6, 8), hospital["ward"], after_operation=True)
                ward_medicines = [("paracetamol", 3), ("oxycodone", 3)]
                if "I48.9" not in patient["comorbidities"]:
                    ward_medicines.append(("enoxaparin", 8))
                for key, hours_after in ward_medicines:
                    start = room_time + timedelta(hours=hours_after)
                    prescription_id = add_medicine(patient, key, start, contact["end"], contact["shjakso_id"], hospital["ward"], "Uloskirjaus")
                    add_administrations(patient, key, prescription_id, start, contact["end"], contact["shjakso_id"], hospital["ward"])
        if chance(0.12):
            add_culture(patient, at_time(room_time + timedelta(days=2), 8, 12), pick(["pus", "urine"]))
        add_note(patient, contact, "Loppuarvio", hospital["ward"], SPECIALTY_TEXT, contact["end"] - timedelta(minutes=between(30, 180)),
                 discharge_note(patient, contact["end"], contact["start"], contact["end"], medicines, follow_up))
    else:
        add_note(patient, contact, "Päivittäismerkintä", hospital["theatre"], SPECIALTY_TEXT, room_time + timedelta(hours=3),
                 daily_note(patient, room_time, 0 + 1, True))

    if patient["procedure_key"] in ("cea", "amputation"):
        add_pathology(patient, room_time + timedelta(minutes=minutes // 2))

    # Control after the operation
    control_time = at_time(room_time + timedelta(days=between(30, 90)), 8, 15)
    if chance(0.5):
        control_contact = new_contact(patient, "Puhelu", hospital["clinic"], control_time, control_time + timedelta(minutes=10), "phone")
        add_visit_row(patient, control_contact, "Soitto", control_time, hospital["clinic"])
        add_note(patient, control_contact, "Puhelinkontakti", hospital["clinic"], SPECIALTY_TEXT, control_time, phone_note(patient, control_time))
    else:
        control_contact = new_contact(patient, "Käynti", hospital["clinic"], control_time, control_time + timedelta(minutes=30), "control")
        add_visit_row(patient, control_contact, "Käynti", control_time, hospital["clinic"])
        add_note(patient, control_contact, "Poliklinikkakäynti", hospital["clinic"], SPECIALTY_TEXT, control_time,
                 outpatient_note(patient, control_time, False, True, medicines))

    # Registry (codes are stored directly, as in the export)
    add_bcb(patient, room_time, preop_time, control_time, patient["group"]["code"], procedure["code"], minutes)


# ---------------------------------------------------------------------------
# Writing the files
# ---------------------------------------------------------------------------

def hashed(column, value):
    """Integer ID -> hex hash. The same ID gets the same hash in every column of its family."""
    family = ID_FAMILY.get(column, column)
    return hashlib.sha256(("%s:%s" % (family, value)).encode("utf-8")).hexdigest()[:HASH_LENGTH]


def format_value(table, column, value):
    """One cell, written the way the real export writes it."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return format_moment(column, value)
    if column == "henkilotunnus" and table != "MOCK_avainlista":
        return PSEUDO_IDS[value]
    if column in HASHED_ID_COLUMNS:
        return hashed(column, value)
    return value


def write_tables(output_folder):
    output_folder.mkdir(parents=True, exist_ok=True)
    for table, rows in TABLES.items():
        formatted_rows = [{column: format_value(table, column, value) for column, value in row.items()} for row in rows]
        frame = pd.DataFrame(formatted_rows, columns=COLUMNS[table], dtype=object)
        frame.to_csv(output_folder / (table + ".csv"), index=False, sep=CSV_SEPARATOR, encoding="utf-8")
        print("%-32s %6d rows" % (table, len(frame)))


def main():
    parser = argparse.ArgumentParser(description="Synthetic HUS Acamedic vascular surgery tables")
    parser.add_argument("--patients", type=int, default=NUMBER_OF_PATIENTS)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT_FOLDER)
    arguments = parser.parse_args()

    generator.seed(arguments.seed)
    used_henkilotunnus = set()
    for number in range(arguments.patients):
        patient = make_patient(used_henkilotunnus)
        build_pathway(patient)
        # Main diagnosis on every other episode that has notes, so notes join to diagnoses on shjakso_id
        for shjakso_id, moment in patient["note_contacts"].items():
            if shjakso_id not in patient["diagnosed_contacts"]:
                add_diagnoses(patient, moment, patient["contacts"][shjakso_id], include_comorbidities=False)
        add_row("Kohortti", henkilotunnus=patient["henkilotunnus"], Apotti_kohortti=True,
                visit_id=patient.get("bcb_operative_visit"), treatment_id=patient.get("bcb_treatment"),
                BCB_kohortti="bcb_treatment" in patient)
    write_tables(arguments.out)
    print("Wrote %d patients to %s" % (arguments.patients, arguments.out))


if __name__ == "__main__":
    main()
