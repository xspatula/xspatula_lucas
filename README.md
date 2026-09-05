# xspatula_lucas

Python package for seeding a PostgreSQL database with the published LUCAS soil sampling data.

**Documentation**: [xspatula.github.io/xspatula_lucas_docs](https://xspatula.github.io/xspatula_lucas_docs/)

---

## What is this?

`xspatula_lucas` builds a PostgreSQL database for the [LUCAS](https://esdac.jrc.ec.europa.eu/projects/lucas)
(Land Use/Cover Area frame Survey) soil sampling campaigns using the Xspatula framework. All
execution logic lives in JSON files — not in code. You define schemes, jobs, pilots, and processes
in JSON; a Jupyter notebook calls the framework; the framework reads the JSON and runs the
pipeline.

The database stores soil sampling and geolocation records, lab-measured soil properties, spectral
data (FOSS XDS RCA), and community/user management. It is intended as a public, reproducible
example of loading a real soil dataset with the Xspatula framework.

---

## Quick start

### 1. Create the Anaconda environment

```bash
conda env create --file anaconda/xspatula_ai4sh_py_3.12.yml
```

> The environment and kernel are still named `xspatula_ai4sh_py_3.12` — inherited from the parent
> `xspatula_ai4sh` package this repo was excerpted from and not yet renamed. Same for the example
> scheme files in the next step.

### 2. Edit the scheme file

Copy and edit one of the example scheme files in `setup/zzz/`:

| File | Purpose |
|---|---|
| `scheme_ai4sh_local_setup.json` | Create a new database |
| `scheme_ai4sh_local_delete.json` | Delete a database |
| `scheme_ai4sh_local_use.json` | Use an existing database |

Set the host, port, database name, and superuser credentials (or point to a `.netrc` entry).

### 3. Run the setup notebook

Open `setup/setup_db.ipynb` in VS Code or Jupyter, select the `xspatula_ai4sh_py_3.12` kernel,
point to your scheme file, and run all cells.

To delete the database, use `setup/delete_db.ipynb` instead.

### 4. Load the LUCAS 2009 campaign

1. Register at https://esdac.jrc.ec.europa.eu/projects/lucas and download `LUCAS.SOIL_corr.csv`.
2. Run `lucas/prepare_lucas_data/lucas_2009_to_xspatula.py` against that CSV. It generates the
   JSON job files and pilot `.txt` files under `lucas/import_data/LUCAS_2009/`.
3. Open the notebooks in `lucas/import_data/` — `insert_utility.ipynb`,
   `insert_lucas_dataset_meta.ipynb`, `load_LUCAS_2009.ipynb` (in that order) — and run them
   against the generated job files to insert the campaign into the database. See
   [xspatula_lucas_docs](https://xspatula.github.io/xspatula_lucas_docs/lucas_2009/) for the full
   walkthrough, including one notebook cell to skip.

---

## Repository structure

```
xspatula_lucas/
├── src/
│   ├── ai4sh/                 # Process/ML/chemometrics logic, name inherited from xspatula_ai4sh
│   ├── lib/                   # Core framework library
│   │   ├── initiate.py        # Database and session initialisation
│   │   ├── login.py           # User authentication against the DB
│   │   ├── pilot.py           # Pilot file execution engine
│   │   ├── structure.py       # Schema and table structure management
│   │   └── version.py
│   ├── postgres/              # PostgreSQL connection and query helpers
│   │   ├── pg_session.py      # psycopg2 connection management
│   │   ├── pg_common.py       # Generic SQL helpers
│   │   ├── pg_processes.py    # Process table management
│   │   └── environment/       # Per-role .env credential files
│   └── utils/                 # Shared utilities
│       ├── json_read_write.py
│       ├── code_log.py
│       ├── datumtid.py
│       ├── pretty_print.py
│       ├── struct.py
│       └── update_dict.py
├── setup/
│   ├── setup_db.ipynb          # Notebook: create database
│   ├── delete_db.ipynb         # Notebook: delete database
│   ├── setup_processes.ipynb   # Notebook: register processes
│   ├── src_setup/               # Setup-specific Python source
│   │   └── lib_setup/           # DB setup, process management, privilege control
│   └── zzz/                     # Example scheme, job, pilot and process files
│       ├── scheme_ai4sh_local_setup.json
│       ├── scheme_ai4sh_local_delete.json
│       ├── scheme_ai4sh_local_use.json
│       └── lucas/                # Job, pilot and process files for DB setup
├── lucas/
│   ├── scheme_lucas.json         # Scheme file for the LUCAS campaign import
│   ├── prepare_lucas_data/
│   │   └── lucas_2009_to_xspatula.py  # CSV → xspatula JSON/pilot files
│   ├── import_data/
│   │   ├── LUCAS_2009/            # Generated job/pilot files for the 2009 campaign
│   │   ├── dataset_meta/          # Campaign/dataset metadata job files
│   │   ├── utility/                # Utility-schema job files
│   │   ├── load_LUCAS_2009.ipynb             # Notebook: insert the 2009 campaign
│   │   ├── insert_lucas_dataset_meta.ipynb  # Notebook: insert dataset metadata
│   │   └── insert_utility.ipynb             # Notebook: insert utility records
│   └── user_management/           # Organisation/user setup for this project
└── anaconda/
    └── xspatula_ai4sh_py_3.12.yml  # Conda environment definition
```

---

## How it works

Every run follows a four-level hierarchy of JSON files:

```
scheme file  →  job file  →  pilot file  →  process file(s)
```

**Scheme file** — defines the database connection, superuser credentials, PostgreSQL users, and a pointer to the job file.

**Job file** — defines which pilot file (or process files) to run and where to find them.

**Pilot file** — a plain-text list of process files; lines starting with `#` are comments and are ignored, making it easy to toggle steps on/off.

**Process file** — a JSON array of operations, each with a `process_id` and `parameters`. Example:

```json
{
  "process": [
    {
      "process_id": "create_schema",
      "parameters": { "schema": "observation" }
    }
  ]
}
```

---

## Security model

Credentials are kept out of code using two mechanisms:

- **`.netrc`** — store PostgreSQL login credentials in `~/.netrc` and reference them by a machine code in the scheme file.
- **`.env` files** — generated automatically during setup; one per user category, stored in `src/postgres/environment/`. Used at runtime to open the database with the correct privileges.

Eight built-in PostgreSQL user roles are created during setup:

| Role | Purpose |
|---|---|
| `community_admin` | Manage users and organisations |
| `login_evaluation` | Validate login attempts (minimal rights) |
| `user_cat_0` – `user_cat_5` | Data access, most restricted (0) to most permissive (5) |

---

## Database schemas

A freshly seeded LUCAS database contains:

| Schema | Key tables |
|---|---|
| `utility` | Territory codes and shared lookup tables |
| `community` | `organisation`, `user`, `user_categories`, `user_media`, `user_activity` |
| `process` | `root_process`, `process`, `process_parameter`, parameter constraints and defaults |
| `observation` | Sample-level lab and spectral observations for the LUCAS campaigns |
| `observation_utility` | Lookup tables: indicators, units, methods, apparatus, spectroscopy, storage, and more |
| `landscape` | Landscape observations and utility |

---

## Documentation

Full documentation at **[xspatula.github.io/xspatula_lucas_docs](https://xspatula.github.io/xspatula_lucas_docs/)**:

- Framework architecture, database setup, and process setup — shared with the rest of the
  Xspatula family, documented at [xspatula.github.io/xspatula_core_docs](https://xspatula.github.io/xspatula_core_docs/)
- LUCAS-specific dataset metadata, sample, and spectra handling, plus the full LUCAS 2009
  download → prepare → insert walkthrough — documented in this repo's own manual

---

## Licenses

- **Code**: [MIT License](LICENSE)
- **Data**: [Creative Commons Attribution (CC-BY)](https://creativecommons.org/licenses/by/4.0/)
