# Synthetic dataset

Two synthetic topsoil datasets for examples and training, made from LUCAS 2015 (built 2026-11-04, 2000 + 300 samples since 2026-11-09).
**The data are local only** (gitignored: excel files with lab values, samples and landscape classes, the spectra
JSON, `data/`, `project_synthetic/data/` and `models/`): they are derived from LUCAS 2015, whose ESDAC licence does
not allow passing them on (permission is being asked). Code, process files, utility excels and notebooks (outputs
stripped on commit by nbstripout, see `.gitattributes`) are tracked. Rebuild the data from your own
LUCAS 2015 download with `prepare/make_synthetic_dataset.py`. User docs: `xspatula_lucas_docs/_synthetic/` (navigation entry "Synthetic tutorial").

| Set | Samples | Campaign | Sampling log | Sample names |
|---|---|---|---|---|
| calibration (model formulation) | 2000 | synthetic calibration | synthetic calibration 2025 | `cal0001@0-20` … |
| validation (independent) | 300 | synthetic validation | synthetic validation 2026 | `val0001@0-20` … |

Database `synthetic`, dataset `synthetic soil spectral library` (alias `synthetic`). All project schemes log in as
the initial user created by `setup_db` (`.netrc` id `ini_user_synthetic`, stratum 5). Optional: dummy organisation
`synthetic soil lab` and user `dummy.user` (`user_management/register_users.ipynb`).

## How the samples are made

- Each sample mixes 3 LUCAS 2015 points with the same land cover family, land use family and BIOGEO16
  region, at most 50 km apart. Families come from the utility tables (e.g. `b31` sunflower → `b10`).
- Random weights per sample (Dirichlet, α = 2), the same for spectra, lab values and coordinates.
- Spectra: two scans per point averaged, mixed as absorbance (log10 1/R), 10 nm bin means
  400–2500 nm (211 bands), stored as diffuse reflectance.
- Lab: OC (`c-org`), N (`n-tot`), EC (`ec`) weighted means; pH(H2O) mixed as H⁺; clay/silt/sand weighted
  and rescaled to 100. Missing if any source misses it (texture: ~23% missing).
- Land cover / land use: the full code if all 3 agree, otherwise the family code.
- Strata allocated in proportion to size, at least 1 per stratum. Validation is a stratified 300 of the
  2300; **no LUCAS point is used in both sets**.
- Rebuild: `python prepare/make_synthetic_dataset.py` (seed fixed; spectra cached in `prepare/cache/`),
  then `python prepare/make_project_files.py`. Sources and weights per sample: `prepare/output/composite_sources.csv`.
- Flat tables for pandas/excel: `data/synthetic_calibration.csv`, `data/synthetic_validation.csv`.

## Run (in order)

The code reads the database name from `src/postgres/environment/*.env`, and `setup_db` rewrites those
files for the database it sets up. One checkout = one database at a time; `setup/switch_db.py` swaps it.
Credentials come from `~/.netrc` (superuser, the database roles, `ini_user_synthetic`); no passwords in scheme files.
The scheme files are in `../setup/zzz/` (relative to this folder); the notebooks in `setup/` refer to them as `./zzz/...`.

0. **Rebuild only** – `setup/delete_db.ipynb` with `scheme_file = './zzz/scheme_local_delete_synthetic.json'`:
   drops the database `synthetic` and deletes the env files (roles used by other databases are kept).
   Delete `project_synthetic/data/` and `project_synthetic/models/` too.
1. **Create the database** – `setup/setup_db.ipynb`, with
   `scheme_file = './zzz/scheme_local_setup_synthetic.json'`, answer `y`, then the audit cell (optional).
   The env files now point at `synthetic`.
2. **Processes** – `setup/setup_processes.ipynb`, with `scheme_file = './zzz/scheme_local_use_synthetic.json'`.
3. **Extra user (optional)** – `user_management/register_users.ipynb`.
4. **Data** – `import_data/insert_synthetic_data.ipynb` (utilities, metadata, samples, observation logs, lab,
   landscape, spectrometer, spectra).
5. **ML example** – `project_synthetic/` notebooks 1–8 (below).
6. **Back to LUCAS** – `python setup/switch_db.py lucas` (no argument = show current).

To regenerate the dataset: `python prepare/make_synthetic_dataset.py` → `python prepare/make_project_files.py`
→ `python prepare/make_ml_project.py` (the last two overwrite the notebooks they write, and their outputs).

## Files

| Folder | Content | Process |
|---|---|---|
| `import_data/utility/` | Copy of the lucas utility excel + provision `foss xds 10nm` | `insert_tabular_data` jobs |
| `import_data/dataset_metadata/` | data source, person, dataset, 2 campaigns, 2 sampling logs | `insert_tabular_data` |
| `import_data/sample/` | geolocations and samples per set | `manage_geolocation`, `manage_geolocated_profile_sample` |
| `import_data/observation_log/` | 8 observation logs (lab, spectra, landscape, BIOGEO16 × 2) | `manage_observation_log` |
| `import_data/lab/` | lab values per set | `manage_observation` |
| `import_data/landscape/` | land cover, land use, BIOGEO16 per set | `manage_land_*_observation`, `manage_biogeo16_observation` |
| `import_data/spectra/` | spectrometer + one JSON per sample, pilot lists, job files | `manage_spectrometer`, `manage_observation` |
| `user_management/` | dummy organisation and user | `manage_organisation`, `manage_user` |
| `../setup/zzz/scheme_local_*_synthetic.json` | setup / use / delete schemes for the database `synthetic` (`.netrc` ids, no passwords) | |

## Worked ML example (`project_synthetic/`)

Run after the data are inserted (step 4 above), notebooks in order (scheme `scheme_synthetic.json`):

| Notebook | Does | Output |
|---|---|---|
| `1_compile_dataset.ipynb` | `compile_dataset_from_db` per set: 7 indicators + absorbance 400–2500 nm/10 nm + land cover/use (family rank), BIOGEO16; inspect; plot indicators and spectra | `data/compiled/synthetic_calibration_10nm/`, `.../synthetic_validation_10nm/` |
| `2_ml_preprocess.ipynb` | calibration only: isolation-forest outliers (c-org, n-tot, ec) → SNV → meancentring. **Interactive**: outlier fraction (example 0.025), indicators (`all`), save SNV `y`, save meancentring `y` | `synthetic_calibration_10nm.olif.snv.mc` |
| `3_ml_model.ipynb` | `regression_modeling`: c-org, n-tot, ph-water, clay × plsr, svr, randfor, cubist; test size 0.3; transformation `standard` (log c-org, n-tot, ec) | `models/synthetic_calibration_10nm.olif.snv.mc_tt/*.joblib` |
| `4_ml_predict.ipynb` | `predict_independent` of all 16 models on the unprocessed validation set (independent metrics); `register_model` c-org PLSR as `synthetic_c-org_plsr`; delete the intermediate dataframes `.olif`, `.olif.snv` (`delete_dataframes`, answer `y`; the raw set and `.olif.snv.mc` are kept for 5–8); predict by registered name; `retire_model` (disabled) | `data/predictions/...` |
| `5…8_ml_model_predict_<covariate>.ipynb` | Same chain with one nominal covariate (biogeo16 4 groups, land cover 3, land use 2, USDA texture major group 4; rest excluded with `class_grouping` `"other": "exclude"`); predicts validation with both model sets and compares on the same samples, overall and per group | `models/..._cv-<covariate>_tt/`, `data/predictions/synthetic_validation_10nm_<covariate>/` |

Notebooks 5–8 and their process files (`process/covariate_<name>/`) are written by
`project_synthetic/make_covariate_notebooks.py`.

The model and prediction paths in the process files are written from the naming rules; if you change
the preprocessing chain, edit `CHAIN` in `prepare/make_ml_project.py` and rerun it.

A registered model needs its `.joblib` + `.manifest.json` in `models/` (the registry stores the absolute path and
sha256, not the file): deleting `data/` is safe, deleting `models/` or moving the repository breaks it.
