"""Write project_synthetic: process files and notebooks for select -> preprocess -> model -> predict/register.

    python make_ml_project.py

All paths in the process files are relative to the project root (synthetic_dataset/, see
scheme_synthetic.json). The model and prediction file names below follow the naming rules of
src/ai4sh (chemometric_abbreviations.md, machine_learning_model.py): keep CHAIN in step with the
preprocessing processes if you change them.
"""

import json
import os

from make_synthetic_dataset import N_CAL, N_VAL

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PROJ = 'project_synthetic'
DATA = './%s/data' % PROJ

CAL = 'synthetic_calibration_10nm'
VAL = 'synthetic_validation_10nm'
SETS = {CAL: 'syn-cal_2025', VAL: 'syn-val_2026'}

INDICATORS = ['c-org', 'n-tot', 'ec', 'ph-water', 'clay', 'silt', 'sand']
MODEL_INDICATORS = ['c-org', 'n-tot', 'ph-water', 'clay']
REGRESSORS = ['plsr', 'svr', 'randfor', 'cubist']
OUTLIER_INDICATORS = ['c-org', 'n-tot', 'ec']
TEST_SIZE = 0.3

CHAIN = 'olif.snv.mc'                       # detect_outliers iforest -> snv -> meancentring
STEM = '%s.%s' % (CAL, CHAIN)
MODELS_FP = './%s/models' % PROJ
REGISTERED = 'synthetic_c-org_plsr'


def cal_fp():
    return '%s/compiled/%s' % (DATA, CAL)


def model_path(indicator, regressor):
    return '%s/%s_tt/%s_%s_%s_tt.joblib' % (MODELS_FP, STEM, STEM, indicator, regressor)


def proc(name, parameters, overwrite=None):
    p = {'process': name}
    if overwrite is not None:
        p['overwrite'] = overwrite
    p['parameters'] = parameters
    return p


def write(rel, *processes):
    fpn = os.path.join(ROOT, PROJ, 'process', rel)
    os.makedirs(os.path.dirname(fpn), exist_ok=True)
    with open(fpn, 'w', encoding='utf-8') as f:
        json.dump({'process': list(processes)}, f, indent=2)
    return '%s/process/%s' % (PROJ, rel)


# ---------------------------------------------------------------------------
# process files
# ---------------------------------------------------------------------------

def process_files():
    P = {}
    for name, sl in SETS.items():
        key = 'calibration' if name == CAL else 'validation'
        P['compile_%s' % key] = write('compile/compile_%s.json' % key, proc('compile_dataset_from_db', {
            'dataset': 'synthetic',
            'sampling_log': sl,
            'min_profile': 0,
            'max_profile': 20,
            'spectra_provision': 'foss-xds-10nm',
            'spectra_preparation_name': 'ds2',
            'begin_wavelength': 400,
            'end_wavelength': 2500,
            'output_bandwidth': 10,
            'output_spectra_signal': 'absorb',
            'indicator_array': INDICATORS,
            'covariate_array': ['landcover', 'landuse', 'biogeo16', 'soil texture usda major group'],
            'covariate_rank': 'family',
            'output_root_fp': DATA,
            'output_name': name}, overwrite=False))
        P['inspect_%s' % key] = write('inspect/inspect_%s.json' % key, proc('inspect_pandas_dataset', {
            'project_root_fp': '%s/compiled/%s' % (DATA, name), 'parquet_file': '', 'column_array': '',
            'max_rows': 10}))

    P['plot_indicators'] = write('plot/plot_indicators_calibration.json', proc('plot_indicators', {
        'project_root_fp': cal_fp(),
        'indicator_array': INDICATORS,
        'targetfeaturesymbols': 'default',
        'standardisation': 'none',
        'transformation': 'standard',
        'single_canvas_plot': True,
        'individual_canvas_plot': False,
        'boxplot': True,
        'histogram': True,
        'show': True,
        'save': True}))
    P['plot_spectra'] = write('plot/plot_spectra_calibration.json', proc('plot_spectra', {
        'project_root_fp': cal_fp(),
        'chemometrics_array': ['snv', 'meancentring'],
        'colormap': 'default',
        'max_spectra': 100,
        'show': True,
        'save': True}))

    P['outliers'] = write('ml_preprocess/1_detect_outliers.json', proc('detect_outliers', {
        'project_root_fp': cal_fp(), 'dataframe': 'raw', 'indicator_array': OUTLIER_INDICATORS,
        'detector': 'iforest', 'threshold': 0.05}))
    P['snv'] = write('ml_preprocess/2_scatter_correction_snv.json', proc('spectra_scatter_correction', {
        'project_root_fp': cal_fp(), 'dataframe': 'previous', 'scaler': ['snv']}))
    P['mc'] = write('ml_preprocess/3_meancentring.json', proc('spectra_scaling', {
        'project_root_fp': cal_fp(), 'dataframe': 'previous', 'method': 'meancentring'}))

    P['list_sets'] = write('ml_setting/list_parameter_sets.json', proc('list_parameter_sets', {'family': ''}))

    P['model'] = write('ml_model/regression_modeling.json', proc('regression_modeling', {
        'project_root_fp': cal_fp(),
        'dataframe': STEM,
        'indicator_array': MODEL_INDICATORS,
        'regressor_array': REGRESSORS,
        'model_parameters_fp': 'default',
        'indicator_transformation': 'standard',
        'indicator_standardisation': 'none',
        'refit_preprocessing': True,
        'traintest': True,
        'test_size': TEST_SIZE,
        'kfold': False,
        'model_fp': MODELS_FP,
        'show_observed_predicted': True,
        'save_observed_predicted': True}, overwrite=True))

    all_models = [model_path(i, r) for i in MODEL_INDICATORS for r in REGRESSORS]
    P['predict'] = write('predict/predict_validation.json', proc('predict_independent', {
        'project_root_fp': '%s/compiled/%s' % (DATA, VAL),
        'dataframe': VAL,
        'model_array': all_models,
        'dst_fp': '%s/predictions/%s' % (DATA, VAL)}, overwrite=True))
    P['register'] = write('ml_model/register_model.json', proc('register_model', {
        'model_array': [model_path('c-org', 'plsr')],
        'name': REGISTERED,
        'abstract': 'Organic carbon from synthetic FOSS XDS 10 nm spectra (calibration set, %d composites of ' % N_CAL +
                    'LUCAS 2015 points); SNV + meancentring, PLSR, standard indicator transformation. '
                    'Example model, not for real predictions.'}))
    P['predict_registered'] = write('predict/predict_validation_registered.json', proc('predict_independent', {
        'project_root_fp': '%s/compiled/%s' % (DATA, VAL),
        'dataframe': VAL,
        'model_array': [REGISTERED],
        'dst_fp': '%s/predictions/%s_registered' % (DATA, VAL)}, overwrite=True))
    P['retire'] = write('ml_model/retire_model.json', proc('retire_model', {'model_array': [REGISTERED]}))
    # Intermediate dataframes are not needed by the models; the modelling input (STEM) is kept for notebooks 5-8
    P['cleanup'] = write('cleanup/delete_dataframes_calibration.json', proc('delete_dataframes', {
        'project_root_fp': cal_fp(),
        'keep_array': ['raw', STEM]}))
    return P


# ---------------------------------------------------------------------------
# notebooks
# ---------------------------------------------------------------------------

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


def md(text):
    return {'cell_type': 'markdown', 'metadata': {}, 'source': text.strip('\n').splitlines(keepends=True)}


def code(text):
    return {'cell_type': 'code', 'execution_count': None, 'metadata': {}, 'outputs': [],
            'source': text.strip('\n').splitlines(keepends=True)}


def run(process_file, disabled=False):
    return code('''%sprocess_file = '%s'

structured_process_D, scheme_params_D = Initiate_process(notebook_path, scheme_file, process_file)

if structured_process_D is not None:

    Run_process(structured_process_D, scheme_params_D)
''' % ('%%script false --no-raise-error\n' if disabled else '', process_file))


def notebook(title, intro, cells):
    head = [md('# %s\n\n%s' % (title, intro.strip())), code(HEAD), md('## Scheme file'),
            code("scheme_file = '../scheme_synthetic.json'")]
    return {'cells': head + cells,
            'metadata': {'kernelspec': {'display_name': 'Python 3', 'language': 'python', 'name': 'python3'},
                         'language_info': {'name': 'python'}},
            'nbformat': 4, 'nbformat_minor': 5}


def notebooks(P):
    nb = {}
    nb['1_compile_dataset.ipynb'] = notebook('1. Compile the datasets', '''
Selects indicators, spectra (absorbance, 400-2500 nm, 10 nm) and covariates (land cover, land use, BIOGEO16,
USDA texture major group)
from the database `synthetic` in one step and saves each set as a compiled dataset:

- `data/compiled/%s/` - calibration, %d samples (sampling log `syn-cal_2025`)
- `data/compiled/%s/` - validation, %d samples (sampling log `syn-val_2026`)

Run `import_data/insert_synthetic_data.ipynb` first.
''' % (CAL, N_CAL, VAL, N_VAL), [
        md('## 1.1 Calibration set'), run(P['compile_calibration']), run(P['inspect_calibration']),
        md('## 1.2 Validation set\n\nUnprocessed: `predict_independent` applies the preprocessing stored in each model.'),
        run(P['compile_validation']), run(P['inspect_validation']),
        md('## 1.3 Look at the calibration data'), run(P['plot_indicators']), run(P['plot_spectra']),
    ])
    nb['2_ml_preprocess.ipynb'] = notebook('2. Preprocess the calibration set', '''
A short, common chain for soil spectra, each step reading the output of the one before:

| Step | Process | Output dataframe |
|---|---|---|
| 1 | `detect_outliers` (isolation forest on c-org, n-tot, ec; values set to missing) | `%s.olif` |
| 2 | `spectra_scatter_correction` (SNV) | `%s.olif.snv` |
| 3 | `spectra_scaling` (meancentring) | `%s` |

Only the calibration set is preprocessed. The model refits steps 2-3 on its training samples and
stores them, so the validation set stays unprocessed.
''' % (CAL, CAL, STEM), [
        md('## 2.1 Indicator outliers'), run(P['outliers']),
        md('## 2.2 SNV scatter correction'), run(P['snv']),
        md('## 2.3 Meancentring'), run(P['mc']),
    ])
    nb['3_ml_model.ipynb'] = notebook('3. Model the calibration set', '''
`regression_modeling` on `%s`: %s with %s, test size %s (sample-id hash, the same samples every run),
indicator transformation `standard` (log for skewed indicators), regressor set `standard`.

Models are saved in `models/%s_tt/` (folder `model_fp`, kept out of the data folders so registered
models are not cleaned up by accident).
''' % (STEM, ', '.join(MODEL_INDICATORS), ', '.join(REGRESSORS), TEST_SIZE, STEM), [
        md('## 3.1 Parameter sets available (optional)'), run(P['list_sets']),
        md('## 3.2 Train and test'), run(P['model']),
    ])
    nb['4_ml_predict.ipynb'] = notebook('4. Validate, register and predict', '''
1. Apply all %d models to the independent validation set (unprocessed spectra). The validation samples
   have observed values, so the run reports independent metrics.
2. Register the model you choose (here `c-org` PLSR as `%s`). Its parameter sets become frozen.
3. Delete the intermediate dataframes: the models do not need them.
4. Predict again by the registered name: the independent metrics are then stored in the registry.
5. Retire the model when it is replaced (disabled).
''' % (len(MODEL_INDICATORS) * len(REGRESSORS), REGISTERED), [
        md('## 4.1 Independent validation, all models'), run(P['predict']),
        md('## 4.2 Register the chosen model\n\nCompare `data/predictions/%s/%s_pred.json` first; '
           'change `model_array` / `name` in `register_model.json` for another model. '
           'A registered model can not be registered twice.' % (VAL, VAL)),
        run(P['register']),
        md('## 4.3 Clean up the intermediate dataframes\n\nA saved model holds its whole preprocessing chain and needs only its `.joblib` and `.manifest.json` in `models/`. The intermediate dataframes `%s.olif` and `%s.olif.snv` are no longer needed. The raw compiled dataset and `%s` (the modelling input, used again in notebooks 5-8) are kept. Answer `y` to delete.' % (CAL, CAL, STEM)), run(P['cleanup']),
        md('## 4.4 Predict with the registered model'), run(P['predict_registered']),
        md('## 4.5 Retire the model (disabled)'), run(P['retire'], disabled=True),
    ])
    for fn, d in nb.items():
        with open(os.path.join(ROOT, PROJ, fn), 'w', encoding='utf-8') as f:
            json.dump(d, f, indent=1)
    return list(nb)


def main():
    P = process_files()
    names = notebooks(P)
    print('%d process files, notebooks: %s' % (len(P), ', '.join(names)))


if __name__ == '__main__':
    main()
