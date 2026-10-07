"""Translate the LUCAS 2015 soil sampling campaign into xspatula JSON import files.

Creates the xspatula hierarchical structure of pilot (txt) files and JSON command
files required for inserting the LUCAS 2015 dataset in the database: process_lab
and process_spectra (mirroring lucas_2009_to_xspatula.py), plus a new
process_landscape (land cover / land use, see below).

Input files must all be placed directly under `CSV_PATH`:

    LUCAS_Topsoil_2015_20200323.csv   - main lab/site campaign (copy of the plain
                                         csv also downloadable as part of the
                                         LUCAS2015_topsoildata_20200323 package)
    LUCAS_Topsoil_2015_20200323.dbf   - Point_ID -> Long/Lat lookup (the plain csv
                                         itself carries no coordinates)
    spectra/spectra_*.csv             - one file per country, as downloaded

`RECORDS` caps how many rows are read from the main csv (0 = all). Spectra are then
read only from the per-country files for whichever countries actually turn up among
those (RECORDS-capped) rows - not every country file in alphabetical order - since
the main csv's row order has nothing to do with the alphabetical country-file order;
for a small RECORDS test run, reading files alphabetically can burn through the
whole sample on a country that was never actually selected, silently producing zero
spectra observations. Country-scoping also makes a full RECORDS=0 run faster, since
each spectra row's point_id is checked against the loaded records *before* parsing
its 4200 band values, not after.

None of the 2015 input files carry any date/timestamp column (unlike 2009). The
LUCAS 2015 field campaign ran May-October 2015, so a representative date
(`MISSING_DATE_TOKEN` = "20150801", roughly the survey midpoint) is used as
`observed_at`/`sampled_at` throughout - lab, spectra and landscape observations
alike - and in place of a per-record date in filenames.

Every point has exactly one row in the main csv but (almost always) two spectral
scans in the country spectra files; the two scans become two separate spectra
observations distinguished by `subsample`: "a", "b" (and "c", "d", ... in the
rare case of more than two scans for the same point).

Coordinates: revisited points reuse the exact same POINT_ID between the 2009 and
2015 campaigns, and geolocation_name uses the same unqualified format as 2009
("{iso}_lucas@{point_id}") - intentionally, so a revisited point resolves to the
exact same geolocation row in both campaigns (same physical location, one entity),
rather than creating a duplicate. Sample names are likewise unqualified
("{point_id}@0-20"); `observation.sample.name` is only unique per sampling_log, so
2009 and 2015 samples for the same point never collide even though the name string
is identical.

Indicators: 2015 has no CEC (unlike 2009) but does have EC (electrical
conductivity, not present in 2009) - mapped to the already-staged `@ec`
indicator. Elevation is site metadata, not a lab indicator, and is not used.
There is no PTotal data for the 2015 campaign.

Texture backfill: a revisited point (Revisited_point == "Yes") sometimes has no
coarse/clay/sand/silt recorded in 2015 at all, since texture wasn't re-measured for
every revisit. backfill_texture_from_2009() fills any such gap from the matching
LUCAS.SOIL_corr.csv (2009) record for the same POINT_ID, replacing the old
stand-alone fill_2015_from_2009.py trial script - streamed (never loading the
~4200 spectral columns or building a DataFrame of the 808MB file), and only reads
2009 at all if some loaded 2015 record actually needs it.

process_landscape/observation_log holds a single shared landscape observation_log
(provision "landscape"), and every land_cover/land_use record references it via
`observation_log_id__observation_log_name` (plus `provision_id__provision_name`).

process_biogeo:
BIOGEO16 (one of 8 EU biogeographic regions, e.g. "Mediterranean", "Boreal") is
joined from LUCAS-Master-Grid.csv by POINT_ID, onto whichever 2015 points already
have a lab/coordinate record; points with no match (or a literal "NA"/"Outside"
value in the grid) are skipped and counted in a summary note. 
BIOGEO16 belongs to its own registered campaign
("biogeo16", an EEA compilation, begun 2016-03-31 - see
lucas/import_data/dataset_meta/excel/campaign.xlsx and
lucas/import_data/utility/observation/excel/provision.xlsx's "compilation" row), not
to the LUCAS 2015 campaign, so it gets its own sampling_log (step1b) - identical in
both this script and lucas_2009_to_xspatula.py, since it's the same global dataset -
and every biogeo observation_log/observation points at that sampling_log/campaign
and the "compilation" provision, not "lucas_eu_2015". The observed date is fixed at
the campaign's own vintage (2016-03-31) for every record, as literal text (not
padded to a timestamp).

To run this script:
- set the number of RECORDS to test with (0 = all records),
- execute it with Python 3,
- ensure the input files are located directly under `CSV_PATH`.
- The output will be generated under the directory specified by `OUTPUT_ROOT`.

To directly put the output data in the prepared structure, set the `OUTPUT_ROOT` to:
`../LUCAS_2015`.
"""

import sys
import csv
import json
import os

import numpy as np


CSV_PATH = "/Users/thomasgumbricht/GitHub_xspatula/LUCAS_TO_JSON/2015"
OUTPUT_ROOT = "../import_data/LUCAS_2015"
RECORDS = 200  # max rows from the main csv, and max spectra scans in total; 0 = all

MAIN_CSV_FILENAME = "LUCAS_Topsoil_2015_20200323.csv"
COORDS_DBF_FILENAME = "LUCAS_Topsoil_2015_20200323.dbf"
SPECTRA_SUBDIR = "spectra"
MASTER_GRID_FILENAME = "LUCAS-Master-Grid.csv"

# For revisited points missing coarse/clay/sand/silt in the 2015 file - see
# backfill_texture_from_2009() - texture is backfilled from the matching 2009
# record. Lives under the 2009 input root, a sibling of CSV_PATH.
LUCAS_2009_ROOT = "/Users/thomasgumbricht/GitHub_xspatula/LUCAS_TO_JSON/2009"
LUCAS_2009_MAIN_CSV_FILENAME = "LUCAS.SOIL_corr.csv"
TEXTURE_COLUMNS = ("coarse", "clay", "sand", "silt")

CONTACT_NAME = "inherit"
CONTACT_EMAIL = "inherit"
CAMPAIGN_NAME = "lucas_eu_2015"
LAB_PROVISION = "lucas-wetlab-2015"
SPECTRA_PROVISION = "foss xds rca"  # same instrument as 2009, different serial
LANDSCAPE_PROVISION = "human interpretation"
BIOGEO_CAMPAIGN_NAME = "biogeo16"
BIOGEO_PROVISION = "compilation"
LAB_OBSERVATION_LOG_NAME = f"{CAMPAIGN_NAME}@{LAB_PROVISION}"
SPECTRA_OBSERVATION_LOG_NAME = f"{CAMPAIGN_NAME}@{SPECTRA_PROVISION}"
LANDSCAPE_OBSERVATION_LOG_NAME = f"{CAMPAIGN_NAME}@{LANDSCAPE_PROVISION}"
BIOGEO_OBSERVATION_LOG_NAME = f"{BIOGEO_CAMPAIGN_NAME}@{BIOGEO_PROVISION}"
SPECTROMETER_PROVISION_ID = "foss-xds-rca"
SPECTROMETER_SERIAL = "lucas 2015"
WAVELENGTH_UNIT = "nm"

BIOGEO_OBSERVED_AT = "2016-03-31"  # fixed date, literal text per CLAUDE.md, not a full timestamp
BIOGEO_DATE_TOKEN = "20160331"     # same date, filename-safe (no dashes)
BIOGEO_MISSING_VALUES = {"", "NA", "Outside"}

# LUCAS 2015 fieldwork ran May-October 2015; no per-point date is available, so
# this representative date (survey midpoint) stands in for observed_at/sampled_at
# everywhere, and for the date segment of generated filenames.
MISSING_DATE_TOKEN = "20150801"
DEFAULT_OBSERVED_AT = "2015-08-01T00:00:00+00:00"

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
    """Parse a CSV string (possibly comma-decimal) or a native dbf number into a float."""
    if isinstance(value, str):
        return float(value.strip().replace(",", "."))
    return float(value)


def try_float(value):
    """Return the float value, or None if missing/unparseable."""
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
        "abstract": "Sampling log for lucas eu 2015",
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
# step 1b - static sampling_log for the biogeo16 campaign
# ---------------------------------------------------------------------------

def step1b_biogeo_sampling_log():
    biogeo_dir = os.path.join(OUTPUT_ROOT, "process_biogeo", "sampling_log")

    sampling_log_params = {
        "campaign_id__campaign_name": BIOGEO_CAMPAIGN_NAME,
        "name": BIOGEO_CAMPAIGN_NAME,
        "contact_name": CONTACT_NAME,
        "contact_email": CONTACT_EMAIL,
        "abstract": "Sampling log for the EEA biogeo16 European biogeographical regions dataset",
    }
    sampling_log_filename = f"{BIOGEO_CAMPAIGN_NAME}_sampling_log.json"

    write_process_json(
        os.path.join(biogeo_dir, "manage_process", sampling_log_filename),
        "manage_sampling_log",
        sampling_log_params,
    )
    write_pilot_txt(biogeo_dir, "SAMPLING_LOG", [sampling_log_filename])


# ---------------------------------------------------------------------------
# step 2 - static observation log
# ---------------------------------------------------------------------------

def step2_observation_log():
    lab_dir = os.path.join(OUTPUT_ROOT, "process_lab", "observation_log")
    spectra_dir = os.path.join(OUTPUT_ROOT, "process_spectra", "observation_log")
    landscape_dir = os.path.join(OUTPUT_ROOT, "process_landscape", "observation_log")

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
        "field": 1, 
    }
    landscape_filename = f"{LANDSCAPE_OBSERVATION_LOG_NAME}_observation_log.json"
    write_process_json(
        os.path.join(landscape_dir, "manage_process", landscape_filename),
        "manage_observation_log",
        landscape_params,
    )
    write_pilot_txt(landscape_dir, "OBSERVATION_LOG", [landscape_filename])


# ---------------------------------------------------------------------------
# step 3 - spectrometer
# ---------------------------------------------------------------------------

def step3_spectrometer(band_wavelengths):
    spectrometer_dir = os.path.join(OUTPUT_ROOT, "process_spectra", "spectrometer")
    params = {
        "provision_id__provision_name": SPECTRA_PROVISION,
        "wavelength_array": band_wavelengths,
        "wavelength_unit_id__wavelength_unit_name": WAVELENGTH_UNIT,
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
            "tag": point_id,
            "name": sample_name(point_id),
            "sampled_at": MISSING_DATE_TOKEN,
            "species_id__species_name": "soil",
            "geolocation_id__geolocation_name": geolocation_name(iso_country, point_id),
            "profile_min": 0,
            "profile_max": 20,
            #"juxtaposition_id__juxtaposition_name": "uniform",
            "proximity_id__proximity_name": "general",
            "composition_id__composition_name": "composite",
        }
        filename = f"{CAMPAIGN_NAME}_{point_id}_0_20_sample.json"
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

def observation_filename(observation_log_name, point_id, subsample, replicate, obs_date_yyyymmdd):
    return (
        f"{observation_log_name}_{sample_name(point_id)}_{subsample}_{replicate}_none_"
        f"{obs_date_yyyymmdd}_observation.json"
    )


LAB_INDICATOR_COLUMNS = [
    ("coarse", "@cf"),
    ("clay", "@clay"),
    ("sand", "@sand"),
    ("silt", "@silt"),
    ("pH(CaCl2)", "@ph-cacl2"),
    ("pH(H2O)", "@ph-h2o"),
    ("OC", "@c-org"),
    ("CaCO3", "@caco3"),
    ("N", "@n-tot"),
    ("P", "@p-ext"),
    ("K", "@k-ext"),
    ("EC", "@ec"),
]


def step6_lab_observation(records):
    observation_dir = os.path.join(OUTPUT_ROOT, "process_lab", "observation")
    filenames = []
    for record in records:
        point_id = record["POINT_ID"]
        params = {
            "observation_log_id__observation_log_name": LAB_OBSERVATION_LOG_NAME,
            "sample_id__sample_name": sample_name(point_id),
            "provision_id__provision_name": LAB_PROVISION,
            "subsample": "a",
            "replicate": 0,
            "observed_at": DEFAULT_OBSERVED_AT,
        }
        for column, indicator_key in LAB_INDICATOR_COLUMNS:
            value = record.get(column)
            if value is not None:
                params[indicator_key] = value
        if not any(k.startswith("@") for k in params):
            continue
        filename = observation_filename(LAB_OBSERVATION_LOG_NAME, point_id, "a", 0, MISSING_DATE_TOKEN)
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

def step7_spectra_observation(spectra_entries):
    observation_dir = os.path.join(OUTPUT_ROOT, "process_spectra", "observation")
    filenames = []
    for point_id, subsample, values in spectra_entries:
        params = {
            "observation_log_id__observation_log_name": SPECTRA_OBSERVATION_LOG_NAME,
            "sample_id__sample_name": sample_name(point_id),
            "provision_id__provision_name": SPECTRA_PROVISION,
            "subsample": subsample,
            "replicate": 0,
            "observed_at": DEFAULT_OBSERVED_AT,
            "provision_serial_nr_id__provision_serial_nr_name": SPECTROMETER_SERIAL,
            "@diffuse reflectance": (1 / np.exp(np.array(values))).tolist(),
        }
        filename = observation_filename(SPECTRA_OBSERVATION_LOG_NAME, point_id, subsample, 0, MISSING_DATE_TOKEN)
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

def step8_land_cover(records):
    land_cover_dir = os.path.join(OUTPUT_ROOT, "process_landscape", "land_cover")
    filenames = []
    for record in records:
        code = record.get("LC1")
        if not code:
            continue
        point_id = record["POINT_ID"]
        iso_country = record["iso.country"]
        params = {
            #"sampling_log_id__sampling_log_name": CAMPAIGN_NAME,
            "observation_log_id__observation_log_name": LANDSCAPE_OBSERVATION_LOG_NAME,
            "geolocation_id__geolocation_name": geolocation_name(iso_country, point_id),
            #"provision_id__provision_name": LANDSCAPE_PROVISION,
            "landcover_genus_id__landcover_genus_name": code,
            "observed_at": DEFAULT_OBSERVED_AT,
        }
        filename = f"{CAMPAIGN_NAME}_{point_id}_land_cover.json"
        write_process_json(
            os.path.join(land_cover_dir, "manage_process", filename),
            "manage_land_cover_observation",
            params,
        )
        filenames.append(filename)
    write_pilot_txt(land_cover_dir, "LAND_COVER", filenames)


# ---------------------------------------------------------------------------
# step 9 - process_landscape/land_use
# ---------------------------------------------------------------------------

def step9_land_use(records):
    land_use_dir = os.path.join(OUTPUT_ROOT, "process_landscape", "land_use")
    filenames = []
    for record in records:
        code = record.get("LU1")
        if not code:
            continue
        point_id = record["POINT_ID"]
        iso_country = record["iso.country"]
        params = {
            #"sampling_log_id__sampling_log_name": CAMPAIGN_NAME,
            "observation_log_id__observation_log_name": LANDSCAPE_OBSERVATION_LOG_NAME,
            "geolocation_id__geolocation_name": geolocation_name(iso_country, point_id),
            #"provision_id__provision_name": LANDSCAPE_PROVISION,
            "landuse_genus_id__landuse_genus_name": code,
            "observed_at": DEFAULT_OBSERVED_AT,
        }
        filename = f"{CAMPAIGN_NAME}_{point_id}_land_use.json"
        write_process_json(
            os.path.join(land_use_dir, "manage_process", filename),
            "manage_land_use_observation",
            params,
        )
        filenames.append(filename)
    write_pilot_txt(land_use_dir, "LAND_USE", filenames)


# ---------------------------------------------------------------------------
# step 10 - process_biogeo/observation_log
# ---------------------------------------------------------------------------

def step10_biogeo_observation_log():
    biogeo_dir = os.path.join(OUTPUT_ROOT, "process_biogeo", "observation_log")
    params = {
        "sampling_log_id__sampling_log_name": BIOGEO_CAMPAIGN_NAME,
        "provision_id__provision_name": BIOGEO_PROVISION,
        "name": BIOGEO_OBSERVATION_LOG_NAME,
        "contact_name": CONTACT_NAME,
        "contact_email": CONTACT_EMAIL,
        "auxiliary": 1,
    }
    filename = f"{BIOGEO_OBSERVATION_LOG_NAME}_observation_log.json"
    write_process_json(
        os.path.join(biogeo_dir, "manage_process", filename),
        "manage_observation_log",
        params,
    )
    write_pilot_txt(biogeo_dir, "OBSERVATION_LOG", [filename])


# ---------------------------------------------------------------------------
# step 11 - process_biogeo/observation
# ---------------------------------------------------------------------------

def step11_biogeo_observation(records):
    observation_dir = os.path.join(OUTPUT_ROOT, "process_biogeo", "observation")
    filenames = []
    for record in records:
        value = record.get("BIOGEO16")
        if value is None:
            continue
        point_id = record["POINT_ID"]
        params = {
            "observation_log_id__observation_log_name": BIOGEO_OBSERVATION_LOG_NAME,
            "geolocation_id__geolocation_name": geolocation_name(record["iso.country"], point_id),
            "observed_at": BIOGEO_OBSERVED_AT,
            "biogeo16_id__biogeo16_name": value.lower(),
        }
        filename = observation_filename(BIOGEO_OBSERVATION_LOG_NAME, point_id, "a", 0, BIOGEO_DATE_TOKEN)
        write_process_json(
            os.path.join(observation_dir, "manage_process", filename),
            "manage_biogeo16_observation",
            params,
        )
        filenames.append(filename)
    write_pilot_txt(observation_dir, "OBSERVATION", filenames)


# ---------------------------------------------------------------------------
# step 12 - top-level job_LUCAS_2015_*.json files
# ---------------------------------------------------------------------------

# (job suffix, dir relative to OUTPUT_ROOT, pilot file name)
JOB_FILE_SPECS = [
    ("geolocation", "process_lab/geolocation", "xspatula_add_geolocation_pilot.txt"),
    ("observation_lab", "process_lab/observation", "xspatula_add_observation_pilot.txt"),
    ("observation_log_lab", "process_lab/observation_log", "xspatula_add_observation_log_pilot.txt"),
    ("observation_log_spectra", "process_spectra/observation_log", "xspatula_add_observation_log_pilot.txt"),
    ("observation_spectra", "process_spectra/observation", "xspatula_add_observation_pilot.txt"),
    ("observation_log_landscape", "process_landscape/observation_log", "xspatula_add_observation_log_pilot.txt"),
    ("sample", "process_lab/sample", "xspatula_add_sample_pilot.txt"),
    ("sampling_log", "process_lab/sampling_log", "xspatula_add_sampling_log_pilot.txt"),
    ("spectrometer", "process_spectra/spectrometer", "xspatula_add_spectrometer_pilot.txt"),
    ("land_cover", "process_landscape/land_cover", "xspatula_add_land_cover_pilot.txt"),
    ("land_use", "process_landscape/land_use", "xspatula_add_land_use_pilot.txt"),
    ("observation_log_biogeo", "process_biogeo/observation_log", "xspatula_add_observation_log_pilot.txt"),
    ("observation_biogeo", "process_biogeo/observation", "xspatula_add_observation_pilot.txt"),
    ("sampling_log_biogeo", "process_biogeo/sampling_log", "xspatula_add_sampling_log_pilot.txt"),
]


def step12_job_files():
    for suffix, sub_path, pilot_file in JOB_FILE_SPECS:
        job_folder = f"import_data/LUCAS_2015/{sub_path}"
        filename = f"job_LUCAS_2015_{suffix}.json"
        write_job_json(
            os.path.join(OUTPUT_ROOT, filename),
            job_folder,
            "manage_process",
            pilot_file,
        )


# ---------------------------------------------------------------------------
# record loading
# ---------------------------------------------------------------------------

def load_main_csv(path):
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)
    idx = {name: i for i, name in enumerate(header)}
    return header, idx, rows


def load_coords(path):
    from dbfread import DBF

    coords = {}
    for rec in DBF(path, load=False, encoding="latin1"):
        rec = {k.strip(): v for k, v in rec.items()}
        point_id = str(clean_dbf(rec.get("Point_ID"))).strip()
        long_ = try_float(rec.get("Long"))
        lat_ = try_float(rec.get("Lat"))
        if long_ is not None and lat_ is not None:
            coords[point_id] = (long_, lat_)
    return coords


def main_csv_records(rows, idx, coords, limit=0):
    records = []
    n_no_coords = 0
    revisited_i = idx["Revisited_point"]
    for row in rows:
        point_id = row[idx["Point_ID"]].strip()
        coord = coords.get(point_id)
        if coord is None:
            n_no_coords += 1
            continue
        record = {
            "POINT_ID": point_id,
            "iso.country": row[idx["NUTS_0"]],
            "GPS_LONG": coord[0],
            "GPS_LAT": coord[1],
            "LC1": row[idx["LC1"]].strip().lower(),
            "LU1": row[idx["LU1"]].strip().lower(),
            "REVISITED": row[revisited_i].strip().lower() == "yes",
        }
        for column, _ in LAB_INDICATOR_COLUMNS:
            record[column] = try_float(row[idx[column]])
        records.append(record)
        if limit and len(records) >= limit:
            break
    if n_no_coords:
        print(f"  NOTE: {n_no_coords} row(s) skipped (no coordinate match in {COORDS_DBF_FILENAME})")
    return records


def backfill_texture_from_2009(records, path):
    """For revisited points (Revisited_point == "Yes") missing coarse/clay/sand/silt
    in the 2015 data, fill the gap(s) from the matching LUCAS.SOIL_corr.csv (2009)
    record for the same POINT_ID - a revisited point's texture was often only
    measured once. Only reads the 2009 file - streamed, texture columns only, never
    its ~4200 spectral columns - if at least one record actually needs it, and stops
    as soon as every needed POINT_ID has been found (not necessarily the whole
    808MB file). Modifies `records` in place.
    """
    needed = {}
    for record in records:
        if not record.get("REVISITED"):
            continue
        missing = [col for col in TEXTURE_COLUMNS if record.get(col) is None]
        if missing:
            needed[record["POINT_ID"]] = missing

    if not needed:
        return

    remaining = set(needed)
    texture_2009 = {}

    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        header = next(reader)
        idx = {name: i for i, name in enumerate(header)}
        pid_i = idx["POINT_ID"]
        col_i = {col: idx[col] for col in TEXTURE_COLUMNS}

        for row in reader:
            point_id = row[pid_i].strip()
            if point_id not in remaining:
                continue
            texture_2009[point_id] = {col: try_float(row[i]) for col, i in col_i.items()}
            remaining.discard(point_id)
            if not remaining:
                break

    n_filled_points = 0
    n_filled_values = 0
    for record in records:
        point_id = record["POINT_ID"]
        if point_id not in needed:
            continue
        source = texture_2009.get(point_id)
        if not source:
            continue
        filled_any = False
        for col in needed[point_id]:
            value = source.get(col)
            if value is not None:
                record[col] = value
                n_filled_values += 1
                filled_any = True
        if filled_any:
            n_filled_points += 1

    print(f"  NOTE: backfilled {n_filled_values} texture value(s) for {n_filled_points} of "
          f"{len(needed)} revisited point(s) missing coarse/clay/sand/silt, from "
          f"{os.path.basename(path)} (2009)")


def spectra_paths_for_countries(spectra_dir, countries):
    """Existing per-country spectra file paths for the given ISO country codes (the
    literal on-disk naming is "spectra_ {code} .csv", spaces included), plus any
    codes with no matching file (reported by the caller, not fatal)."""
    paths = []
    missing = []
    for code in sorted(countries):
        path = os.path.join(spectra_dir, f"spectra_ {code} .csv")
        if os.path.exists(path):
            paths.append(path)
        else:
            missing.append(code)
    return paths, missing


def load_spectra(spectra_dir, wanted_point_ids, countries, limit=0):
    """Read spectra scans only from the per-country files for `countries` - the
    countries actually present among the already-loaded, RECORDS-capped lab
    records - instead of every country file in alphabetical order. The main csv's
    row order has nothing to do with the alphabetical country-file order, so for a
    small RECORDS test run, reading files alphabetically can burn the whole `limit`
    on a country that was never actually sampled, dropping every scan. Scoping to
    the relevant countries (and skipping non-matching point_ids before parsing
    their 4200 band values, not after) also makes a full RECORDS=0 run faster.
    """
    paths, missing = spectra_paths_for_countries(spectra_dir, countries)
    if missing:
        print(f"  NOTE: no spectra file found for {len(missing)} country code(s): {', '.join(missing)}")

    band_wavelengths = None
    entries = []
    scan_counts = {}
    n_skipped = 0

    for path in paths:
        with open(path, newline="", encoding="utf-8", errors="replace") as f:
            reader = csv.reader(f)
            header = next(reader)
            pid_i = header.index("PointID")
            first_band_idx = header.index("400")
            this_bands = [float(h) for h in header[first_band_idx:]]
            if band_wavelengths is None:
                band_wavelengths = this_bands
            elif this_bands != band_wavelengths:
                raise ValueError(f"Band columns in {path} do not match previously seen bands")

            for row in reader:
                point_id = row[pid_i].strip()
                if point_id not in wanted_point_ids:
                    n_skipped += 1
                    continue
                n = scan_counts.get(point_id, 0)
                scan_counts[point_id] = n + 1
                subsample = chr(ord("a") + n)
                values = [float(v) for v in row[first_band_idx:]]
                entries.append((point_id, subsample, values))
                if limit and len(entries) >= limit:
                    if n_skipped:
                        print(f"  NOTE: {n_skipped} spectra scan(s) skipped (point not in the loaded lab/coordinate records)")
                    return band_wavelengths, entries

    if n_skipped:
        print(f"  NOTE: {n_skipped} spectra scan(s) skipped (point not in the loaded lab/coordinate records)")
    return band_wavelengths, entries


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
    _header, idx, rows = load_main_csv(os.path.join(CSV_PATH, MAIN_CSV_FILENAME))
    coords = load_coords(os.path.join(CSV_PATH, COORDS_DBF_FILENAME))
    records = main_csv_records(rows, idx, coords, limit=RECORDS)

    backfill_texture_from_2009(records, os.path.join(LUCAS_2009_ROOT, LUCAS_2009_MAIN_CSV_FILENAME))

    biogeo = load_biogeo(os.path.join(CSV_PATH, MASTER_GRID_FILENAME))
    n_no_biogeo = 0
    for record in records:
        value = biogeo.get(record["POINT_ID"])
        record["BIOGEO16"] = value
        if value is None:
            n_no_biogeo += 1
    if n_no_biogeo:
        print(f"  NOTE: {n_no_biogeo} record(s) have no BIOGEO16 match in {MASTER_GRID_FILENAME}")

    valid_point_ids = {r["POINT_ID"] for r in records}
    wanted_countries = {r["iso.country"].strip().upper() for r in records if r.get("iso.country")}

    band_wavelengths, spectra_entries = load_spectra(
        os.path.join(CSV_PATH, SPECTRA_SUBDIR), valid_point_ids, wanted_countries, limit=RECORDS)

    return records, band_wavelengths, spectra_entries


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    try:
        records, band_wavelengths, spectra_entries = load_all_records()
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
        ("step1b - process_biogeo/sampling_log", step1b_biogeo_sampling_log, ()),
        ("step2 - observation_log", step2_observation_log, ()),
        ("step3 - spectrometer", step3_spectrometer, (band_wavelengths,)),
        ("step4 - geolocation", step4_geolocation, (records,)),
        ("step5 - sample", step5_sample, (records,)),
        ("step6 - process_lab/observation", step6_lab_observation, (records,)),
        ("step7 - process_spectra/observation", step7_spectra_observation, (spectra_entries,)),
        ("step8 - process_landscape/land_cover", step8_land_cover, (records,)),
        ("step9 - process_landscape/land_use", step9_land_use, (records,)),
        ("step10 - process_biogeo/observation_log", step10_biogeo_observation_log, ()),
        ("step11 - process_biogeo/observation", step11_biogeo_observation, (records,)),
        ("step12 - job_LUCAS_2015_*.json files", step12_job_files, ()),
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
