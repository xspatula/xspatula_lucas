"""Write the synthetic project's scheme files, user management files and notebooks.

Run once after make_synthetic_dataset.py (it does not touch the data files):

    python make_project_files.py
"""

import json
import os

from make_synthetic_dataset import N_CAL, N_VAL

import openpyxl

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

DUMMY_USER = 'dummy.user'
DUMMY_PASSWORD = 'change-me'   # placeholder: the user sets a real one in the notebook before running


def write_json(rel, payload):
    fpn = os.path.join(ROOT, rel)
    os.makedirs(os.path.dirname(fpn), exist_ok=True)
    with open(fpn, 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2)


def write_xlsx(rel, header, rows):
    fpn = os.path.join(ROOT, rel)
    os.makedirs(os.path.dirname(fpn), exist_ok=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(header)
    for r in rows:
        ws.append(r)
    wb.save(fpn)


# Login from ~/.netrc (machine <id> login <user> password <secret>), never a password in the scheme file
NETRC_ID = 'ini_user_synthetic'


def scheme(user_netrc_id, verbose=1):
    return {'project_path': '../synthetic_dataset',
            'user_project': {'user_netrc_id': user_netrc_id},
            'process': [{'execute': True, 'verbose': verbose, 'overwrite': False, 'delete': False}]}


# ---------------------------------------------------------------------------
# notebooks
# ---------------------------------------------------------------------------

def md(text):
    return {'cell_type': 'markdown', 'metadata': {}, 'source': text.strip('\n').splitlines(keepends=True)}


def code(text):
    return {'cell_type': 'code', 'execution_count': None, 'metadata': {}, 'outputs': [],
            'source': text.strip('\n').splitlines(keepends=True)}


def run_cell(kind, rel_path):
    var = 'job_file' if kind == 'job' else 'process_file'
    return code('''
%s = '%s'

structured_process_D, scheme_params_D = Initiate_process(notebook_path, scheme_file, %s)

if structured_process_D is not None:

    Run_process(structured_process_D, scheme_params_D)
''' % (var, rel_path, var))


HEAD = '''
# Standard library imports
from os import path, getcwd

import sys

notebook_path = getcwd()

# Root of the xspatula_lucas repository (two levels up)
module_path = path.abspath(path.join('../..'))

if module_path not in sys.path:

    sys.path.append(module_path)

from src.lib import Initiate_process

from src.ai4sh import Run_process
'''


def notebook(cells):
    return {'cells': cells, 'metadata': {'kernelspec': {'display_name': 'Python 3', 'language': 'python',
                                                        'name': 'python3'},
                                         'language_info': {'name': 'python'}},
            'nbformat': 4, 'nbformat_minor': 5}


def register_users_notebook():
    cells = [
        md('''
# Synthetic dataset - register the dummy organisation and user

Optional: the project schemes log in as the initial user (`.netrc` id `ini_user_synthetic`, created by
`setup_db`), so the data import and notebooks 1-8 do not need this user. It shows how to add an
organisation and a user to one database.

Runs as the initial user (scheme `../scheme_synthetic.json`). Creates organisation **synthetic soil lab**
and user **%s** (stratum 5) **without e-mail** (the lucas notebook e-mails a random password; a dummy address
cannot receive it). Cell 4 stores only a bcrypt hash of `dummy_password`: change it before running. To work as
this user, add `machine dummy_synthetic login %s password <your password>` to `~/.netrc` and set
`"user_netrc_id": "dummy_synthetic"` in `../scheme_synthetic.json`.

The env files must point at the database `synthetic` (`setup_db` does that; check with
`python setup/switch_db.py`).
''' % (DUMMY_USER, DUMMY_USER)),
        code(HEAD + '''
from src.utils.json_read_write import Read_json, Dump_json

from src.community import Hash_password
'''),
        code("scheme_file = '../scheme_synthetic.json'"),
        md('## 1. General utility (territories) - needed by organisation and user'),
        run_cell('job', 'import_data/utility/job_insert_general_utility.json'),
        md('## 2. Organisation'),
        run_cell('process', 'user_management/organisation/insert_organisation.json'),
        md('## 3. User: translate excel to JSON'),
        run_cell('process', 'user_management/user/translate_user.json'),
        md('## 4. Set the dummy password (bcrypt hash, no e-mail)'),
        code('''
manage_user_FPN = path.join(notebook_path, 'user/manage_process/manage_user.json')

dummy_password = '%s'

user_D = Read_json(manage_user_FPN)

for block_D in user_D['process']:

    block_D['parameters']['password'] = Hash_password(dummy_password)

Dump_json(manage_user_FPN, user_D)

print([b['parameters']['user_name'] for b in user_D['process']])
''' % DUMMY_PASSWORD),
        md('## 5. Insert the user'),
        run_cell('process', 'user_management/user/manage_process/manage_user.json'),
    ]
    return notebook(cells)


def insert_data_notebook():
    cells = [
        md('''
# Synthetic dataset - insert all data

Two synthetic datasets made from LUCAS 2015 (see `../README.md`):

| Set | Samples | Campaign | Sampling log |
|---|---|---|---|
| calibration (model formulation) | %d | synthetic calibration | synthetic calibration 2025 |
| validation (independent) | %d | synthetic validation | synthetic validation 2026 |

Run the cells in order. Everything except the spectra is read from excel with `insert_tabular_data`
(single step, INSERT-only). Spectra go through JSON files and pilot lists, because a 211-band array
does not fit in an excel cell.
''' % (N_CAL, N_VAL)),
        code(HEAD),
        code("scheme_file = '../scheme_synthetic.json'"),
        md('''
# 1. Utilities

Copies of the lucas utility excel files, plus the provision **foss xds 10nm** (provision,
provision_indicator, provision_serial_nr) for the 10 nm spectra. Cell 1.1 can be skipped if
`register_users.ipynb` already ran it.
'''),
        md('## 1.1 General utility'),
        run_cell('job', 'import_data/utility/job_insert_general_utility.json'),
        md('## 1.2 Observation utility'),
        run_cell('job', 'import_data/utility/job_insert_observation_utility.json'),
        md('## 1.3 Observation utility with inheritance (provisions)'),
        run_cell('job', 'import_data/utility/job_insert_observation_utility_inherit.json'),
        md('## 1.4 Landscape utility (land cover, land use, BIOGEO16)'),
        run_cell('job', 'import_data/utility/job_insert_landscape_utility.json'),
        md('''
# 2. Dataset metadata

Data source, person, dataset, the two campaigns and their sampling logs.
'''),
        run_cell('job', 'import_data/dataset_metadata/job_insert_dataset_metadata.json'),
        md('# 3. Geolocations and samples'),
        md('## 3.1 Calibration'),
        run_cell('process', 'import_data/sample/insert_sample_calibration.json'),
        md('## 3.2 Validation'),
        run_cell('process', 'import_data/sample/insert_sample_validation.json'),
        md('''
# 4. Observation logs

8 logs: lab, spectra, land cover/use (human interpretation) and BIOGEO16 (compilation), per sampling log.
'''),
        run_cell('process', 'import_data/observation_log/insert_observation_log.json'),
        md('''
# 5. Laboratory observations

OC (`c-org`), N (`n-tot`), EC (`ec`), pH in water (`ph-h2o`) and texture (`clay`, `silt`, `sand`;
the texture classes are derived on insert).
'''),
        md('## 5.1 Calibration'),
        run_cell('process', 'import_data/lab/insert_lab_calibration.json'),
        md('## 5.2 Validation'),
        run_cell('process', 'import_data/lab/insert_lab_validation.json'),
        md('# 6. Landscape observations (land cover, land use, BIOGEO16)'),
        md('## 6.1 Calibration'),
        run_cell('process', 'import_data/landscape/insert_landscape_calibration.json'),
        md('## 6.2 Validation'),
        run_cell('process', 'import_data/landscape/insert_landscape_validation.json'),
        md('''
# 7. Spectra

## 7.1 Spectrometer

The 10 nm wavelength array (400-2500 nm, 211 bands) of provision `foss xds 10nm`.
'''),
        run_cell('job', 'import_data/spectra/job_spectrometer.json'),
        md('## 7.2 Calibration spectra (%d files)' % N_CAL),
        run_cell('job', 'import_data/spectra/job_spectra_calibration.json'),
        md('## 7.3 Validation spectra (300 files)'),
        run_cell('job', 'import_data/spectra/job_spectra_validation.json'),
    ]
    return notebook(cells)


def main():
    write_json('scheme_synthetic.json', scheme(NETRC_ID))

    write_xlsx('user_management/organisation/excel/organisation.xlsx',
               ['name', 'alias', 'url', 'postal_address', 'territory_id__territory_name', 'contact_name',
                'contact_email'],
               [['synthetic soil lab', 'synthetic-lab', 'https://example.org', 'Nowhere', 'sweden', 'Dummy User',
                 'dummy.user@example.org']])
    write_json('user_management/organisation/insert_organisation.json',
               {'process': [{'process': 'insert_tabular_data', 'overwrite': True, 'parameters': {
                   'process': 'manage_organisation',
                   'tabular_data_path': 'user_management/organisation/excel/organisation.xlsx',
                   'dst_path': 'user_management/organisation/staging'}}]})
    write_xlsx('user_management/user/excel/user.xlsx',
               ['organisation_id__organisation_name', 'user_name', 'stratum_code', 'first_name', 'last_name',
                'email', 'territory_id__territory_name', 'position'],
               [['synthetic soil lab', DUMMY_USER, 5, 'Dummy', 'User', 'dummy.user@example.org', 'sweden',
                 'Analyst']])
    write_json('user_management/user/translate_user.json',
               {'process': [{'process': 'translate_tabular_data', 'overwrite': True, 'parameters': {
                   'process': 'manage_user',
                   'tabular_data_path': 'user_management/user/excel/user.xlsx',
                   'dst_path': 'user_management/user/manage_process'}}]})

    for rel, nb in (('user_management/register_users.ipynb', register_users_notebook()),
                    ('import_data/insert_synthetic_data.ipynb', insert_data_notebook())):
        with open(os.path.join(ROOT, rel), 'w', encoding='utf-8') as f:
            json.dump(nb, f, indent=1)
    print('scheme, user management files and notebooks written under', ROOT)


if __name__ == '__main__':
    main()
