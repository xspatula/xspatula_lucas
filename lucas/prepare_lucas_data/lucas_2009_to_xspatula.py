"""Translate the LUCAS 2009 soil sampling campaign into xspatula JSON import files.

Creates the xspatula hierarchical strrucute of a pilot (txt) file and JSON command 
files required for inserting the LUCAS 2009 dataset in the database. Input file must be the 
`LUCAS.SOIL_corr.csv` that can be downloaded from https://esdac.jrc.ec.europa.eu/projects/lucas 
after registration.

To run this script: 
- set the number of LUCAS 2009 RECORDS to test with (0 = all records),
- execute it with Python 3, 
- ensure that the input CSV file is located at the path specified by `CSV_PATH`. 
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



CSV_PATH = "/Users/thomasgumbricht/GitHub_xspatula/LUCAS_TO_JSON/2009/LUCAS.SOIL_corr.csv"
OUTPUT_ROOT = "../import_data/LUCAS_2009"
RECORDS = 25  # number of CSV rows to process in steps 4-7; 0 = all rows

CONTACT_NAME = "inherit"
CONTACT_EMAIL = "inherit"
CAMPAIGN_NAME = "lucas_eu_2009"
LAB_PROVISION = "lucas-wetlab-2009"
SPECTRA_PROVISION = "foss xds rca"
LAB_OBSERVATION_LOG_NAME = f"{CAMPAIGN_NAME}@{LAB_PROVISION}"
SPECTRA_OBSERVATION_LOG_NAME = f"{CAMPAIGN_NAME}@{SPECTRA_PROVISION}"
SPECTROMETER_PROVISION_ID = "foss-xds-rca"
SPECTROMETER_SERIAL = "lucas 2009"

MONTH_ABBR = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
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
    return float(value.strip().replace(",", "."))


def try_float(value):
    """Return the float value, or None if missing/unparseable (e.g. 'NA')."""
    try:
        return to_float(value)
    except ValueError:
        return None


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
        "wavelength_unit_id__wavelength_unit_name": "um",
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


def step4_geolocation(rows, idx):
    geolocation_dir = os.path.join(OUTPUT_ROOT, "process_lab", "geolocation")
    filenames = []
    seen = set()
    for row in rows:
        point_id = row[idx["POINT_ID"]]
        iso_country = row[idx["iso.country"]]
        name = geolocation_name(iso_country, point_id)
        if name in seen:
            continue
        seen.add(name)
        params = {
            "name": name,
            "x_coordinate": to_float(row[idx["GPS_LONG"]]),
            "y_coordinate": to_float(row[idx["GPS_LAT"]]),
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


def step5_sample(rows, idx):
    sample_dir = os.path.join(OUTPUT_ROOT, "process_lab", "sample")
    filenames = []
    seen = set()
    for row in rows:
        point_id = row[idx["POINT_ID"]]
        if point_id in seen:
            continue
        seen.add(point_id)
        iso_country = row[idx["iso.country"]]
        params = {
            "sampling_log_id__sampling_log_name": CAMPAIGN_NAME,
            "tag": point_id.strip(),
            "name": sample_name(point_id),
            "sampled_at": surv_date_to_yyyymmdd(row[idx["SURV_DATE"]]),
            "species_id__species_name": "soil",
            "geolocation_id__geolocation_name": geolocation_name(iso_country, point_id),
            "profile_min": 0,
            "profile_max": 20,
            "juxtaposition_id__juxtaposition_name": "uniform",
            "proximity_id__proximity_name": "general",
            "composition_id__composition_name": "composite",
        }
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
]


def step6_lab_observation(rows, idx):
    observation_dir = os.path.join(OUTPUT_ROOT, "process_lab", "observation")
    filenames = []
    for row in rows:
        point_id = row[idx["POINT_ID"]]
        date_value = row[idx["date"]]
        params = {
            "observation_log_id__observation_log_name": LAB_OBSERVATION_LOG_NAME,
            "sample_id__sample_name": sample_name(point_id),
            "provision_id__provision_name": LAB_PROVISION,
            "subsample": "a",
            "replicate": 0,
            "observed_at": date_to_iso8601(date_value),
        }
        for column, indicator_key in LAB_INDICATOR_COLUMNS:
            value = try_float(row[idx[column]])
            if value is not None:
                params[indicator_key] = value
        if not any(k.startswith("@") for k in params):
            continue
        filename = observation_filename(LAB_OBSERVATION_LOG_NAME, point_id, date_to_yyyymmdd(date_value))
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
# main
# ---------------------------------------------------------------------------

def load_csv():
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)
    idx = {name: i for i, name in enumerate(header)}
    return header, idx, rows


def main():
    try:
        header, idx, rows = load_csv()
    except FileNotFoundError:
        print(f"ERROR: input file not found: {CSV_PATH}")
        print("DONE with errors: nothing was generated.")
        print(f"Output root: {os.path.abspath(OUTPUT_ROOT)}")
        sys.exit(1)
    except OSError as e:
        print(f"ERROR: could not read input file {CSV_PATH}: {e}")
        print("DONE with errors: nothing was generated.")
        print(f"Output root: {os.path.abspath(OUTPUT_ROOT)}")
        sys.exit(1)

    spc_columns = read_spc_columns(header)
    record_rows = rows if RECORDS == 0 else rows[:RECORDS]

    steps = [
        ("step1 - campaign & sampling_log", step1_sampling_log, ()),
        ("step2 - observation_log", step2_observation_log, ()),
        ("step3 - spectrometer", step3_spectrometer, (spc_columns,)),
        ("step4 - geolocation", step4_geolocation, (record_rows, idx)),
        ("step5 - sample", step5_sample, (record_rows, idx)),
        ("step6 - process_lab/observation", step6_lab_observation, (record_rows, idx)),
        ("step7 - process_spectra/observation", step7_spectra_observation, (record_rows, idx, spc_columns)),
    ]

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