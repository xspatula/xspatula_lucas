"""Translate the LUCAS 2009 soil sampling campaign into xspatula JSON import files.

Creates the xspatula hierarchical strrucute of a pilot (txt) file and JSON command
files required for inserting the LUCAS 2009 dataset in the database.

Input files must all be placed directly under `CSV_PATH`, using their names as
downloaded from https://esdac.jrc.ec.europa.eu/projects/lucas (after registration):

    LUCAS.SOIL_corr.csv                  - main 2009 campaign (with spectra)
    PTotal2009.dbf                       - total phosphorus, joined onto existing records
    SoilAttr_ICELAND.dbf                 - complement, Iceland
    SoilAttr_LUCAS_2009_CYP_MLT.dbf      - complement, Cyprus/Malta
    SoilAttr_LUCAS_2012_BG_RO.dbf        - complement, Bulgaria/Romania

Each file is only read if its `INCLUDE_*` flag below is True. `RECORDS` caps how
many rows are imported from *each* enabled file independently (0 = all rows).

None of the SoilAttr_*.dbf complement files carry SURV_DATE/date, so rows sourced
from them omit `sampled_at`/`observed_at` from the generated JSON (both are optional
parameters) and use the placeholder "00000000" in place of a date in filenames.

PTotal2009.dbf carries no coordinates/sample metadata of its own - when enabled, its
PTotal value is merged (by POINT_ID, as `@p-tot`) into the lab observation JSON that
is otherwise generated for that point from the other enabled sources; it never creates
geolocation/sample/observation records by itself.

process_landscape / process_biogeo: LC1/LU1 (land cover/use) and BIOGEO16 (one of 8
EU biogeographic regions, from LUCAS-Master-Grid.csv, joined by POINT_ID) are only
generated for LUCAS.SOIL_corr.csv-sourced records - the SoilAttr_*.dbf complements
carry neither column, so those points are silently skipped by these two process
groups. LC1/LU1 use `manage_land_cover_observation`/`manage_land_use_observation`
(there is no `manage_landscape` process in the schema), keyed by a genus lookup
resolved by name-or-alias - the lower-cased LC1/LU1 code (e.g. "a11", "u111") is
passed directly. A handful of 2009 LC1 codes (LANDCOVER_SKIP_CODES below) have no
match anywhere in the land_cover order/family/genus hierarchy yet and are skipped
and reported; LU1 is fully covered. Unlike LC1/LU1 (which get each record's real
survey date), BIOGEO16 uses a fixed "2020-05-01" (the grid's own vintage) and the
shared "biogeo16_eu_2020"/"biogeo16" observation_log - identical to the one the
2015 script generates, since it's the same global dataset, not campaign-specific.
`manage_observation_log` has no `in-situ` parameter and `manage_land_cover_observation`/
`manage_land_use_observation` have no `observation_log_id__observation_log_name`/
`provision_id__provision_name` parameter, and `manage_landscape` (used for biogeo)
doesn't exist at all - these are generated anyway, in anticipation of a planned
schema update, matching lucas_2015_to_xspatula.py.

IMPORTANT - nitrogen (N) unit normalisation to weight percent (w%):
- LUCAS.SOIL_corr.csv: already w%, no conversion.
- SoilAttr_LUCAS_2012_BG_RO.dbf: mg/100g -> divide by 1000.
- SoilAttr_ICELAND.dbf: mg/kg -> divide by 10000.
- SoilAttr_LUCAS_2009_CYP_MLT.dbf: already w%, no conversion.

To run this script:
- set the INCLUDE_* flags below for the files to process,
- set the number of RECORDS to test with (0 = all records),
- execute it with Python 3,
- ensure the input files are located directly under `CSV_PATH`.
- The output will be generated under the directory specified by `OUTPUT_ROOT`.

To directly put the output data in the prepared structure, set the `OUTPUT_ROOT` to:
`../LUCAS_2009`.
"""

import sys
import csv
import json
import os
from datetime import datetime

import numpy as np


CSV_PATH = "/Users/thomasgumbricht/GitHub_xspatula/LUCAS_TO_JSON/2009"
OUTPUT_ROOT = "../import_data/LUCAS_2009"
RECORDS = 0  # max rows to import from each enabled file; 0 = all rows

MAIN_CSV_FILENAME = "LUCAS.SOIL_corr.csv"
PTOTAL_FILENAME = "PTotal2009.dbf"
ICELAND_FILENAME = "SoilAttr_ICELAND.dbf"
CYP_MLT_FILENAME = "SoilAttr_LUCAS_2009_CYP_MLT.dbf"
BG_RO_FILENAME = "SoilAttr_LUCAS_2012_BG_RO.dbf"

# BIOGEO16 grid lives under the 2015 input root - it's a single EU-wide dataset
# shared across campaigns, not year-specific.
MASTER_GRID_ROOT = "/Users/thomasgumbricht/GitHub_xspatula/LUCAS_TO_JSON/2015"
MASTER_GRID_FILENAME = "LUCAS-Master-Grid.csv"

INCLUDE_MAIN_2009 = True
INCLUDE_PTOTAL = True
INCLUDE_ICELAND = True
INCLUDE_CYP_MLT = True
INCLUDE_BG_RO = True

CONTACT_NAME = "inherit"
CONTACT_EMAIL = "inherit"
CAMPAIGN_NAME = "lucas_eu_2009"
LAB_PROVISION = "lucas-wetlab-2009"
SPECTRA_PROVISION = "foss xds rca"
LANDSCAPE_PROVISION = "landscape"
BIOGEO_CAMPAIGN_NAME = "biogeo16_eu_2020"
BIOGEO_PROVISION = "biogeo16"
LAB_OBSERVATION_LOG_NAME = f"{CAMPAIGN_NAME}@{LAB_PROVISION}"
SPECTRA_OBSERVATION_LOG_NAME = f"{CAMPAIGN_NAME}@{SPECTRA_PROVISION}"
LANDSCAPE_OBSERVATION_LOG_NAME = f"{CAMPAIGN_NAME}@{LANDSCAPE_PROVISION}"
BIOGEO_OBSERVATION_LOG_NAME = f"{BIOGEO_CAMPAIGN_NAME}@{BIOGEO_PROVISION}"
SPECTROMETER_PROVISION_ID = "foss-xds-rca"
SPECTROMETER_SERIAL = "lucas 2009"

BIOGEO_OBSERVED_AT = "2020-05-01"  # fixed date, literal text, not a full timestamp
BIOGEO_DATE_TOKEN = "20200501"     # same date, filename-safe (no dashes)
BIOGEO_MISSING_VALUES = {"", "NA", "Outside"}

# LC1 codes (lowercased) present in the 2009 data that have no match at any level
# (order/family/genus) of the land_cover hierarchy yet. LU1 is fully covered.
LANDCOVER_SKIP_CODES = {"f00", "g10", "g20", "h21"}

MONTH_ABBR = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}

# field name (in the dbf, after stripping whitespace) for each canonical record
# key. ICELAND's " Long" field also normalises to "Long" once stripped, so it
# shares a map with CYP_MLT. BG_RO's dbf uses upper-case field names throughout.
COMPLEMENT_FIELD_MAP_LOWER = {
    "POINT_ID": "POINT_ID",
    "iso.country": "NUTS_0",
    "GPS_LONG": "Long",
    "GPS_LAT": "Lat",
    "coarse": "coarse",
    "clay": "clay",
    "silt": "silt",
    "sand": "sand",
    "pH.in.CaCl2": "pHinCaCl2",
    "pH.in.H2O": "pHinH2O",
    "OC": "OC",
    "CaCO3": "CaCO3",
    "N": "N",
    "P": "P",
    "K": "K",
    "CEC": "CEC",
}

COMPLEMENT_FIELD_MAP_BG_RO = {
    "POINT_ID": "POINT_ID",
    "iso.country": "NUTS_0",
    "GPS_LONG": "LONG",
    "GPS_LAT": "LAT",
    "coarse": "COARSE",
    "clay": "CLAY",
    "silt": "SILT",
    "sand": "SAND",
    "pH.in.CaCl2": "PHINCACL2",
    "pH.in.H2O": "PHINH2O",
    "OC": "OC",
    "CaCO3": "CACO3",
    "N": "N",
    "P": "P",
    "K": "K",
    "CEC": "CEC",
}

if OUTPUT_ROOT.startswith(".."):
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    OUTPUT_ROOT = os.path.join(SCRIPT_DIR, OUTPUT_ROOT)

# ---------------------------------------------------------------------------
# generic helpers
# ---------------------------------------------------------------------------

def write_process_json(path, process_name, parameters):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {"process": [{"process": process_name, "parameters": parameters}]}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def write_job_json(path, job_folder, process_sub_folder, pilot_file):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {
        "process": {
            "job_folder": job_folder,
            "process_sub_folder": process_sub_folder,
            "pilot_file": pilot_file,
        }
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def write_pilot_txt(dir_path, category, filenames):
    os.makedirs(dir_path, exist_ok=True)
    header = (
        "############################################\n"
        f"##### XSPATULA ADD {category} #####\n"
        "############################################\n"
    )
    with open(os.path.join(dir_path, f"xspatula_add_{category.lower()}_pilot.txt"), "w", encoding="utf-8") as f:
        f.write(header)
        for name in filenames:
            f.write(name + "\n")


def to_float(value):
    """Parse a CSV string or a native dbf number (int/float/Decimal) into a float."""
    if isinstance(value, str):
        return float(value.strip().replace(",", "."))
    return float(value)


def try_float(value):
    """Return the float value, or None if missing/unparseable (e.g. 'NA', '<5')."""
    if value is None or value == "":
        return None
    try:
        return to_float(value)
    except (TypeError, ValueError):
        return None


def clean_dbf(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return value


def surv_date_to_yyyymmdd(value):
    day = int(value[0:2])
    month = MONTH_ABBR[value[2:5].upper()]
    year = int(value[5:9])
    return f"{year:04d}{month:02d}{day:02d}"


def date_to_iso8601(value):
    return value.strip().replace(" ", "T") + "+00:00"


def date_to_yyyymmdd(value):
    dt = datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S")
    return dt.strftime("%Y%m%d")


# ---------------------------------------------------------------------------
# step 1 - static sampling_log
# ---------------------------------------------------------------------------

def step1_sampling_log():
    lab_dir = os.path.join(OUTPUT_ROOT, "process_lab")

    sampling_log_params = {
        "campaign_id__campaign_name": CAMPAIGN_NAME,
        "name": CAMPAIGN_NAME,
        "contact_name": CONTACT_NAME,
        "contact_email": CONTACT_EMAIL,
        "abstract": "Sampling log for lucas eu 2009",
    }
    sampling_log_filename = f"{CAMPAIGN_NAME}_sampling_log.json"

    sampling_log_dir = os.path.join(lab_dir, "sampling_log")
    write_process_json(
        os.path.join(sampling_log_dir, "manage_process", sampling_log_filename),
        "manage_sampling_log",
        sampling_log_params,
    )
    write_pilot_txt(sampling_log_dir, "SAMPLING_LOG", [sampling_log_filename])

# ---------------------------------------------------------------------------
# step 2 - static observation log
# ---------------------------------------------------------------------------

def step2_observation_log():
    lab_dir = os.path.join(OUTPUT_ROOT, "process_lab", "observation_log")
    spectra_dir = os.path.join(OUTPUT_ROOT, "process_spectra", "observation_log")
    landscape_dir = os.path.join(OUTPUT_ROOT, "process_landscape", "observation_log")
    biogeo_dir = os.path.join(OUTPUT_ROOT, "process_biogeo", "observation_log")

    lab_params = {
        "sampling_log_id__sampling_log_name": CAMPAIGN_NAME,
        "provision_id__provision_name": LAB_PROVISION,
        "name": LAB_OBSERVATION_LOG_NAME,
        "contact_name": CONTACT_NAME,
        "contact_email": CONTACT_EMAIL,
        "preparation_id__preparation_name": "ds2",
        "preservation_id__preservation_name": "ds2",
        "storage_id__storage_name": "amb",
        "laboratory": 1,
    }
    lab_filename = f"{LAB_OBSERVATION_LOG_NAME}_observation_log.json"
    write_process_json(
        os.path.join(lab_dir, "manage_process", lab_filename),
        "manage_observation_log",
        lab_params,
    )
    write_pilot_txt(lab_dir, "OBSERVATION_LOG", [lab_filename])

    spectra_params = {
        "sampling_log_id__sampling_log_name": CAMPAIGN_NAME,
        "provision_id__provision_name": SPECTRA_PROVISION,
        "name": SPECTRA_OBSERVATION_LOG_NAME,
        "contact_name": CONTACT_NAME,
        "contact_email": CONTACT_EMAIL,
        "preparation_id__preparation_name": "ds2",
        "preservation_id__preservation_name": "ds2",
        "storage_id__storage_name": "amb",
        "laboratory": 1,
    }
    spectra_filename = f"{SPECTRA_OBSERVATION_LOG_NAME}_observation_log.json"
    write_process_json(
        os.path.join(spectra_dir, "manage_process", spectra_filename),
        "manage_observation_log",
        spectra_params,
    )
    write_pilot_txt(spectra_dir, "OBSERVATION_LOG", [spectra_filename])

    landscape_params = {
        "sampling_log_id__sampling_log_name": CAMPAIGN_NAME,
        "provision_id__provision_name": LANDSCAPE_PROVISION,
        "name": LANDSCAPE_OBSERVATION_LOG_NAME,
        "contact_name": CONTACT_NAME,
        "contact_email": CONTACT_EMAIL,
        "in-situ": 1,  # NOTE: not yet a manage_observation_log parameter, pending schema update
    }
    landscape_filename = f"{LANDSCAPE_OBSERVATION_LOG_NAME}_observation_log.json"
    write_process_json(
        os.path.join(landscape_dir, "manage_process", landscape_filename),
        "manage_observation_log",
        landscape_params,
    )
    write_pilot_txt(landscape_dir, "OBSERVATION_LOG", [landscape_filename])

    biogeo_params = {
        "sampling_log_id__sampling_log_name": BIOGEO_CAMPAIGN_NAME,
        "provision_id__provision_name": BIOGEO_PROVISION,
        "name": BIOGEO_OBSERVATION_LOG_NAME,
        "contact_name": CONTACT_NAME,
        "contact_email": CONTACT_EMAIL,
        "satellite": 1,
    }
    biogeo_filename = f"{BIOGEO_OBSERVATION_LOG_NAME}_observation_log.json"
    write_process_json(
        os.path.join(biogeo_dir, "manage_process", biogeo_filename),
        "manage_observation_log",
        biogeo_params,
    )
    write_pilot_txt(biogeo_dir, "OBSERVATION_LOG", [biogeo_filename])


# ---------------------------------------------------------------------------
# step 3 - spectrometer
# ---------------------------------------------------------------------------

def read_spc_columns(header):
    """Return [(column_index, wavelength_float), ...] for every spc.* column, in file order."""
    result = []
    for i, name in enumerate(header):
        if name.startswith("spc."):
            wavelength = float(name[len("spc."):])
            result.append((i, wavelength))
    return result


def step3_spectrometer(spc_columns):
    spectrometer_dir = os.path.join(OUTPUT_ROOT, "process_spectra", "spectrometer")
    wavelength_array = [w for _, w in spc_columns]
    params = {
        "provision_id__provision_name": SPECTRA_PROVISION,
        "wavelength_array": wavelength_array,
        "wavelength_unit_id__wavelength_unit_name": "nm",
        "provision_serial_nr_id__provision_serial_nr_name": SPECTROMETER_SERIAL,
    }
    filename = f"{SPECTROMETER_PROVISION_ID}_{SPECTROMETER_SERIAL}_spectrometer.json"
    write_process_json(
        os.path.join(spectrometer_dir, "manage_process", filename),
        "manage_spectrometer",
        params,
    )
    write_pilot_txt(spectrometer_dir, "SPECTROMETER", [filename])


# ---------------------------------------------------------------------------
# step 4 - geolocation
# ---------------------------------------------------------------------------

def geolocation_name(iso_country, point_id):
    return f"{iso_country.strip().lower()}_lucas@{point_id.strip()}"


def step4_geolocation(records):
    geolocation_dir = os.path.join(OUTPUT_ROOT, "process_lab", "geolocation")
    filenames = []
    seen = set()
    for record in records:
        point_id = record["POINT_ID"]
        iso_country = record["iso.country"]
        name = geolocation_name(iso_country, point_id)
        if name in seen:
            continue
        seen.add(name)
        params = {
            "name": name,
            "x_coordinate": record["GPS_LONG"],
            "y_coordinate": record["GPS_LAT"],
        }
        filename = f"{name}_geolocation.json"
        write_process_json(
            os.path.join(geolocation_dir, "manage_process", filename),
            "manage_geolocation",
            params,
        )
        filenames.append(filename)
    write_pilot_txt(geolocation_dir, "GEOLOCATION", filenames)


# ---------------------------------------------------------------------------
# step 5 - sample
# ---------------------------------------------------------------------------

def sample_name(point_id):
    return f"{point_id.strip()}@0-20"


def step5_sample(records):
    sample_dir = os.path.join(OUTPUT_ROOT, "process_lab", "sample")
    filenames = []
    seen = set()
    for record in records:
        point_id = record["POINT_ID"]
        if point_id in seen:
            continue
        seen.add(point_id)
        iso_country = record["iso.country"]
        params = {
            "sampling_log_id__sampling_log_name": CAMPAIGN_NAME,
            "tag": point_id.strip(),
            "name": sample_name(point_id),
        }
        surv_date = record.get("SURV_DATE")
        if surv_date:
            params["sampled_at"] = surv_date_to_yyyymmdd(surv_date)
        params.update({
            "species_id__species_name": "soil",
            "geolocation_id__geolocation_name": geolocation_name(iso_country, point_id),
            "profile_min": 0,
            "profile_max": 20,
            "juxtaposition_id__juxtaposition_name": "uniform",
            "proximity_id__proximity_name": "general",
            "composition_id__composition_name": "composite",
        })
        filename = f"{CAMPAIGN_NAME}_{point_id.strip()}_0_20_sample.json"
        write_process_json(
            os.path.join(sample_dir, "manage_process", filename),
            "manage_geolocated_profile_sample",
            params,
        )
        filenames.append(filename)
    write_pilot_txt(sample_dir, "SAMPLE", filenames)


# ---------------------------------------------------------------------------
# step 6 - process_lab/observation
# ---------------------------------------------------------------------------

MISSING_DATE_TOKEN = "00000000"


def observation_filename(observation_log_name, point_id, obs_date_yyyymmdd):
    return (
        f"{observation_log_name}_{sample_name(point_id)}_a_0_none_"
        f"{obs_date_yyyymmdd}_observation.json"
    )


LAB_INDICATOR_COLUMNS = [
    ("coarse", "@cf"),
    ("clay", "@clay"),
    ("silt", "@silt"),
    ("sand", "@sand"),
    ("pH.in.CaCl2", "@ph-cacl2"),
    ("pH.in.H2O", "@ph-h2o"),
    ("OC", "@c-org"),
    ("CaCO3", "@caco3"),
    ("N", "@n-tot"),
    ("P", "@p-ext"),
    ("K", "@k-ext"),
    ("CEC", "@cec"),
    ("PTotal", "@p-tot"),
]


def step6_lab_observation(records):
    observation_dir = os.path.join(OUTPUT_ROOT, "process_lab", "observation")
    filenames = []
    for record in records:
        point_id = record["POINT_ID"]
        date_value = record.get("date")
        params = {
            "observation_log_id__observation_log_name": LAB_OBSERVATION_LOG_NAME,
            "sample_id__sample_name": sample_name(point_id),
            "provision_id__provision_name": LAB_PROVISION,
            "subsample": "a",
            "replicate": 0,
        }
        if date_value:
            params["observed_at"] = date_to_iso8601(date_value)
        for column, indicator_key in LAB_INDICATOR_COLUMNS:
            value = record.get(column)
            if value is not None:
                params[indicator_key] = value
        if not any(k.startswith("@") for k in params):
            continue
        obs_date_yyyymmdd = date_to_yyyymmdd(date_value) if date_value else MISSING_DATE_TOKEN
        filename = observation_filename(LAB_OBSERVATION_LOG_NAME, point_id, obs_date_yyyymmdd)
        write_process_json(
            os.path.join(observation_dir, "manage_process", filename),
            "manage_observation",
            params,
        )
        filenames.append(filename)
    write_pilot_txt(observation_dir, "OBSERVATION", filenames)


# ---------------------------------------------------------------------------
# step 7 - process_spectra/observation
# ---------------------------------------------------------------------------

def step7_spectra_observation(rows, idx, spc_columns):
    observation_dir = os.path.join(OUTPUT_ROOT, "process_spectra", "observation")
    filenames = []
    for row in rows:
        point_id = row[idx["POINT_ID"]]
        date_value = row[idx["date"]]
        params = {
            "observation_log_id__observation_log_name": SPECTRA_OBSERVATION_LOG_NAME,
            "sample_id__sample_name": sample_name(point_id),
            "provision_id__provision_name": SPECTRA_PROVISION,
            "subsample": "a",
            "replicate": 0,
            "observed_at": date_to_iso8601(date_value),
            "provision_serial_nr_id__provision_serial_nr_name": SPECTROMETER_SERIAL,
            "@diffuse reflectance": (1 / np.exp(np.array(
                [to_float(row[i]) for i, _ in spc_columns]))).tolist(),
        }
        filename = observation_filename(SPECTRA_OBSERVATION_LOG_NAME, point_id, date_to_yyyymmdd(date_value))
        write_process_json(
            os.path.join(observation_dir, "manage_process", filename),
            "manage_observation",
            params,
        )
        filenames.append(filename)
    write_pilot_txt(observation_dir, "OBSERVATION", filenames)


# ---------------------------------------------------------------------------
# step 8 - process_landscape/land_cover
# ---------------------------------------------------------------------------

def step8_land_cover(main_records):
    land_cover_dir = os.path.join(OUTPUT_ROOT, "process_landscape", "land_cover")
    filenames = []
    skipped = {}
    for record in main_records:
        code = record.get("LC1")
        if not code:
            continue
        if code in LANDCOVER_SKIP_CODES:
            skipped[code] = skipped.get(code, 0) + 1
            continue
        point_id = record["POINT_ID"]
        iso_country = record["iso.country"]
        date_value = record.get("date")
        params = {
            "sampling_log_id__sampling_log_name": CAMPAIGN_NAME,
            "observation_log_id__observation_log_name": LANDSCAPE_OBSERVATION_LOG_NAME,
            "geolocation_id__geolocation_name": geolocation_name(iso_country, point_id),
            "provision_id__provision_name": LANDSCAPE_PROVISION,
            "landcover_genus_id__landcover_genus_name": code,
        }
        if date_value:
            params["observed_at"] = date_to_iso8601(date_value)
        filename = f"{CAMPAIGN_NAME}_{point_id}_land_cover.json"
        write_process_json(
            os.path.join(land_cover_dir, "manage_process", filename),
            "manage_land_cover_observation",
            params,
        )
        filenames.append(filename)
    write_pilot_txt(land_cover_dir, "LAND_COVER", filenames)
    if skipped:
        print("  Skipped LC1 codes not yet in the land_cover order/family/genus hierarchy"
              " (add to land_cover_genus.xlsx and re-run its insert_process):")
        for code, count in sorted(skipped.items()):
            print(f"    {code.upper()}: {count} record(s)")


# ---------------------------------------------------------------------------
# step 9 - process_landscape/land_use
# ---------------------------------------------------------------------------

def step9_land_use(main_records):
    land_use_dir = os.path.join(OUTPUT_ROOT, "process_landscape", "land_use")
    filenames = []
    for record in main_records:
        code = record.get("LU1")
        if not code:
            continue
        point_id = record["POINT_ID"]
        iso_country = record["iso.country"]
        date_value = record.get("date")
        params = {
            "sampling_log_id__sampling_log_name": CAMPAIGN_NAME,
            "observation_log_id__observation_log_name": LANDSCAPE_OBSERVATION_LOG_NAME,
            "geolocation_id__geolocation_name": geolocation_name(iso_country, point_id),
            "provision_id__provision_name": LANDSCAPE_PROVISION,
            "landuse_genus_id__landuse_genus_name": code,
        }
        if date_value:
            params["observed_at"] = date_to_iso8601(date_value)
        filename = f"{CAMPAIGN_NAME}_{point_id}_land_use.json"
        write_process_json(
            os.path.join(land_use_dir, "manage_process", filename),
            "manage_land_use_observation",
            params,
        )
        filenames.append(filename)
    write_pilot_txt(land_use_dir, "LAND_USE", filenames)


# ---------------------------------------------------------------------------
# step 10 - process_biogeo/observation
# ---------------------------------------------------------------------------

def step10_biogeo_observation(main_records):
    observation_dir = os.path.join(OUTPUT_ROOT, "process_biogeo", "observation")
    filenames = []
    for record in main_records:
        value = record.get("BIOGEO16")
        if value is None:
            continue
        point_id = record["POINT_ID"]
        params = {
            "observation_log_id__observation_log_name": BIOGEO_OBSERVATION_LOG_NAME,
            "sample_id__sample_name": sample_name(point_id),
            "provision_id__provision_name": BIOGEO_PROVISION,
            "observed_at": BIOGEO_OBSERVED_AT,
            "@biogeo16": value,
        }
        filename = observation_filename(BIOGEO_OBSERVATION_LOG_NAME, point_id, BIOGEO_DATE_TOKEN)
        write_process_json(
            os.path.join(observation_dir, "manage_process", filename),
            "manage_landscape",
            params,
        )
        filenames.append(filename)
    write_pilot_txt(observation_dir, "OBSERVATION", filenames)


# ---------------------------------------------------------------------------
# step11 - top-level job_LUCAS_2009_*.json files
# ---------------------------------------------------------------------------

# (job suffix, dir relative to OUTPUT_ROOT, pilot file name)
JOB_FILE_SPECS = [
    ("geolocation", "process_lab/geolocation", "xspatula_add_geolocation_pilot.txt"),
    ("observation_lab", "process_lab/observation", "xspatula_add_observation_pilot.txt"),
    ("observation_log_lab", "process_lab/observation_log", "xspatula_add_observation_log_pilot.txt"),
    ("observation_log_spectra", "process_spectra/observation_log", "xspatula_add_observation_log_pilot.txt"),
    ("observation_spectra", "process_spectra/observation", "xspatula_add_observation_pilot.txt"),
    ("sample", "process_lab/sample", "xspatula_add_sample_pilot.txt"),
    ("sampling_log", "process_lab/sampling_log", "xspatula_add_sampling_log_pilot.txt"),
    ("spectrometer", "process_spectra/spectrometer", "xspatula_add_spectrometer_pilot.txt"),
    ("observation_log_landscape", "process_landscape/observation_log", "xspatula_add_observation_log_pilot.txt"),
    ("land_cover", "process_landscape/land_cover", "xspatula_add_land_cover_pilot.txt"),
    ("land_use", "process_landscape/land_use", "xspatula_add_land_use_pilot.txt"),
    ("observation_log_biogeo", "process_biogeo/observation_log", "xspatula_add_observation_log_pilot.txt"),
    ("observation_biogeo", "process_biogeo/observation", "xspatula_add_observation_pilot.txt"),
]


def step11_job_files():
    for suffix, sub_path, pilot_file in JOB_FILE_SPECS:
        job_folder = f"import_data/LUCAS_2009/{sub_path}"
        filename = f"job_LUCAS_2009_{suffix}.json"
        write_job_json(
            os.path.join(OUTPUT_ROOT, filename),
            job_folder,
            "manage_process",
            pilot_file,
        )


# ---------------------------------------------------------------------------
# record loading - normalises every enabled source into a common record shape
# ---------------------------------------------------------------------------

def load_main_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)
    idx = {name: i for i, name in enumerate(header)}
    return header, idx, rows


def main_csv_records(rows, idx, limit=0):
    records = []
    for row in rows:
        record = {
            "POINT_ID": row[idx["POINT_ID"]],
            "iso.country": row[idx["iso.country"]],
            "SURV_DATE": row[idx["SURV_DATE"]],
            "date": row[idx["date"]],
            "GPS_LONG": to_float(row[idx["GPS_LONG"]]),
            "GPS_LAT": to_float(row[idx["GPS_LAT"]]),
            "LC1": row[idx["LC1"]].strip().lower(),
            "LU1": row[idx["LU1"]].strip().lower(),
        }
        for column, _ in LAB_INDICATOR_COLUMNS:
            if column == "PTotal":
                continue
            record[column] = try_float(row[idx[column]])
        records.append(record)
        if limit and len(records) >= limit:
            break
    return records


def load_dbf_records(path, field_map, n_divisor=None, limit=0):
    from dbfread import DBF

    records = []
    for rec in DBF(path, load=False, encoding="latin1"):
        rec = {k.strip(): v for k, v in rec.items()}
        record = {
            "POINT_ID": str(clean_dbf(rec.get(field_map["POINT_ID"]))).strip(),
            "iso.country": clean_dbf(rec.get(field_map["iso.country"])),
            "GPS_LONG": to_float(rec.get(field_map["GPS_LONG"])),
            "GPS_LAT": to_float(rec.get(field_map["GPS_LAT"])),
        }
        for key in ("coarse", "clay", "silt", "sand", "pH.in.CaCl2", "pH.in.H2O", "OC", "CaCO3", "P", "K", "CEC"):
            record[key] = try_float(rec.get(field_map[key]))
        n_value = try_float(rec.get(field_map["N"]))
        if n_value is not None and n_divisor:
            n_value = n_value / n_divisor
        record["N"] = n_value
        records.append(record)
        if limit and len(records) >= limit:
            break
    return records


def load_ptotal(path, limit=0):
    from dbfread import DBF

    ptotal = {}
    count = 0
    for rec in DBF(path, load=False, encoding="latin1"):
        rec = {k.strip(): v for k, v in rec.items()}
        point_id = str(clean_dbf(rec.get("POINT_ID"))).strip()
        ptotal[point_id] = try_float(rec.get("PTotal"))
        count += 1
        if limit and count >= limit:
            break
    return ptotal


def load_biogeo(path):
    biogeo = {}
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        header = next(reader)
        idx = {name: i for i, name in enumerate(header)}
        pid_i = idx["POINT_ID"]
        bg_i = idx["BIOGEO16"]
        for row in reader:
            value = row[bg_i].strip()
            if value in BIOGEO_MISSING_VALUES:
                continue
            biogeo[row[pid_i].strip()] = value
    return biogeo


def load_all_records():
    """Assemble the normalised record list (steps 4-6) and, if enabled, the main
    CSV header/rows/spc_columns (steps 3 & 7). `main_records` (steps 8-10) is the
    LUCAS.SOIL_corr.csv-only subset of `all_records`, since the SoilAttr_*.dbf
    complements carry neither LC1/LU1 nor a usable POINT_ID scope for BIOGEO16.
    Raises on missing/unreadable files."""
    header = idx = rows = None
    spc_columns = []
    all_records = []
    main_records = []

    if INCLUDE_MAIN_2009:
        main_path = os.path.join(CSV_PATH, MAIN_CSV_FILENAME)
        header, idx, rows = load_main_csv(main_path)
        spc_columns = read_spc_columns(header)
        record_rows = rows if RECORDS == 0 else rows[:RECORDS]
        main_records = main_csv_records(record_rows, idx, limit=RECORDS)
        all_records.extend(main_records)

        biogeo = load_biogeo(os.path.join(MASTER_GRID_ROOT, MASTER_GRID_FILENAME))
        n_no_biogeo = 0
        for record in main_records:
            value = biogeo.get(record["POINT_ID"])
            record["BIOGEO16"] = value
            if value is None:
                n_no_biogeo += 1
        if n_no_biogeo:
            print(f"  NOTE: {n_no_biogeo} record(s) have no BIOGEO16 match in {MASTER_GRID_FILENAME}")

    if INCLUDE_ICELAND:
        path = os.path.join(CSV_PATH, ICELAND_FILENAME)
        all_records.extend(load_dbf_records(path, COMPLEMENT_FIELD_MAP_LOWER, n_divisor=10000, limit=RECORDS))

    if INCLUDE_CYP_MLT:
        path = os.path.join(CSV_PATH, CYP_MLT_FILENAME)
        all_records.extend(load_dbf_records(path, COMPLEMENT_FIELD_MAP_LOWER, n_divisor=None, limit=RECORDS))

    if INCLUDE_BG_RO:
        path = os.path.join(CSV_PATH, BG_RO_FILENAME)
        all_records.extend(load_dbf_records(path, COMPLEMENT_FIELD_MAP_BG_RO, n_divisor=1000, limit=RECORDS))

    if INCLUDE_PTOTAL:
        path = os.path.join(CSV_PATH, PTOTAL_FILENAME)
        ptotal = load_ptotal(path, limit=RECORDS)
        for record in all_records:
            value = ptotal.get(record["POINT_ID"])
            if value is not None:
                record["PTotal"] = value

    record_rows_for_spectra = rows if RECORDS == 0 else (rows[:RECORDS] if rows is not None else None)
    return header, idx, record_rows_for_spectra, spc_columns, all_records, main_records


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    try:
        _header, idx, record_rows, spc_columns, all_records, main_records = load_all_records()
    except FileNotFoundError as e:
        print(f"ERROR: input file not found: {e.filename}")
        print("DONE with errors: nothing was generated.")
        print(f"Output root: {os.path.abspath(OUTPUT_ROOT)}")
        sys.exit(1)
    except OSError as e:
        print(f"ERROR: could not read an input file: {e}")
        print("DONE with errors: nothing was generated.")
        print(f"Output root: {os.path.abspath(OUTPUT_ROOT)}")
        sys.exit(1)

    steps = [
        ("step1 - campaign & sampling_log", step1_sampling_log, ()),
        ("step2 - observation_log", step2_observation_log, ()),
        ("step4 - geolocation", step4_geolocation, (all_records,)),
        ("step5 - sample", step5_sample, (all_records,)),
        ("step6 - process_lab/observation", step6_lab_observation, (all_records,)),
        ("step8 - process_landscape/land_cover", step8_land_cover, (main_records,)),
        ("step9 - process_landscape/land_use", step9_land_use, (main_records,)),
        ("step10 - process_biogeo/observation", step10_biogeo_observation, (main_records,)),
        ("step11 - job_LUCAS_2009_*.json files", step11_job_files, ()),
    ]
    if INCLUDE_MAIN_2009:
        steps.insert(2, ("step3 - spectrometer", step3_spectrometer, (spc_columns,)))
        steps.insert(6, ("step7 - process_spectra/observation", step7_spectra_observation, (record_rows, idx, spc_columns)))

    failures = []
    for label, func, args in steps:
        try:
            func(*args)
            print(f"OK: {label}")
        except Exception as e:
            failures.append(label)
            print(f"FAILED: {label} - {type(e).__name__}: {e}")

    if failures:
        print(f"DONE with errors: {len(failures)} of {len(steps)} step(s) failed: {', '.join(failures)}")
        print(f"Output root: {os.path.abspath(OUTPUT_ROOT)}")
        sys.exit(1)
    else:
        print("DONE: all steps completed successfully.")
        print(f"Output root: {os.path.abspath(OUTPUT_ROOT)}")


if __name__ == "__main__":
    main()
