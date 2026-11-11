'''Build process files + notebook <nr>_ml_model_predict_<covariate>.ipynb for project_synthetic.
Run from synthetic_dataset/project_synthetic: python make_cov_nb.py <spec name>'''
import json, sys, os, re

CAL = 'synthetic_calibration_10nm'
STEM = CAL + '.olif.snv.mc'
INDICATORS = ['c-org', 'n-tot', 'ph-water', 'clay']
REGRESSORS = ['plsr', 'svr', 'randfor', 'cubist']

SPECS = {
    'biogeo16': dict(nr=5, title='biogeographic region', groups=[
        ['boreal', 'alpine'], ['atlantic'], ['continental', 'pannonian', 'steppic', 'black-sea'], ['mediterranean']],
        other='exclude', intro='The rare regions (calibration samples: steppic 16, black-sea 3) are pooled into 4 groups.'),
    'landcover': dict(nr=6, title='land cover', groups=[
        ['cultivated'], ['grass-l-no-trees', 'grass-l-trees'], ['conif-woodl', 'broadl-woodl', 'mixed-woodl']],
        other='exclude', intro='3 groups: cultivated, grassland, forest. The other classes (agroforest, lichens, '
        'spontan, shrubland, swamp) are left out (`"other": "exclude"`): their samples are not modelled and not '
        'predicted by the land cover models.'),
    'landuse': dict(nr=7, title='land use', groups=[['agriculture'], ['forestry']],
        other='exclude', intro='2 groups: agriculture and forestry. The other classes (natural/semi-natural, '
        'recreation, unused, mining) are left out (`"other": "exclude"`).'),
    'texture': dict(nr=8, label='soil texture usda major group', title='soil texture (USDA major group)',
        groups=None, other=None, classes=['sandy soils', 'loamy soils', 'light clayey soils', 'heavy clayey soils'],
        intro='The 4 USDA major groups as they are (no class_grouping). Samples without a texture class (the same as '
        'those without clay) are not modelled and not predicted by the texture models. In this dataset the class is '
        'derived from the measured clay, silt and sand, so for **clay** the covariate leaks the target; in the field '
        'it would come from a soil map.'),
}

def md(t): return {"cell_type": "markdown", "metadata": {}, "source": t.splitlines(True)}
def code(t): return {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": t.splitlines(True)}
def dump(obj, fp):
    with open(fp, 'w') as fh:
        json.dump(obj, fh, indent=2, ensure_ascii=False); fh.write('\n')

def build(cov):
    spec = SPECS[cov]
    label = spec.get('label', cov)
    pdir = 'process/covariate_%s' % cov
    os.makedirs(pdir, exist_ok=True)
    tag = '_cv-' + re.sub(r'[^0-9a-z]+', '', label.lower())   # as _Covariate_tag in machine_learning_model.py
    reg = json.load(open('process/ml_model/regression_modeling.json'))
    p = reg['process'][0]['parameters']
    p.update(covariate_array=[label], save_observed_predicted=False)
    if spec['groups']:
        grouping = {"covariate": label, "groups": spec['groups']}
        if spec['other']:
            grouping['other'] = spec['other']
        p['class_grouping'] = [grouping]
    dump(reg, '%s/regression_modeling_%s.json' % (pdir, cov))
    pv = json.load(open('process/predict/predict_validation.json'))
    pp = pv['process'][0]['parameters']
    d0 = './project_synthetic/models/%s_tt/%s_%%s_%%s_tt.joblib' % (STEM, STEM)
    d1 = './project_synthetic/models/%s%s_tt/%s%s_%%s_%%s_tt.joblib' % (STEM, tag, STEM, tag)
    pp['model_array'] = [d % (i, r) for i in INDICATORS for d in (d0, d1) for r in REGRESSORS]
    pp.update(dst_fp='./project_synthetic/data/predictions/synthetic_validation_10nm_%s' % cov,
              show_observed_predicted=True, save_plot_layout=True)
    dump(pv, '%s/predict_validation_%s.json' % (pdir, cov))

    nb4 = json.load(open('4_ml_predict.ipynb'))
    imports = ''.join(nb4['cells'][1]['source'])
    run = lambda pf: ("process_file = '%s'\n\nstructured_process_D, scheme_params_D = Initiate_process(notebook_path, "
                      "scheme_file, process_file)\n\nif structured_process_D is not None:\n\n    Run_process("
                      "structured_process_D, scheme_params_D)" % pf)
    groups_md = '\n'.join('| %s | %s |' % (i + 1, ', '.join(g))
                          for i, g in enumerate(spec['groups'] or [[c] for c in spec['classes']]))
    compare = COMPARE.replace('COVLABEL', label).replace('COV', cov)
    cells = [
        md('# %d. Spectra + %s (%s)\n\nDoes the %s improve the predictions? The same chain as notebook 3 '
           '(preprocessing `olif.snv.mc` refitted inside the model; c-org, n-tot, ph-water, clay; plsr, svr, randfor, '
           'cubist; test size 0.3) with `%s` as a nominal covariate (one-hot encoded next to the spectra).\n\n%s\n\n'
           '| Group | Classes |\n|---|---|\n%s\n\nA group is named by its classes joined with `|` in the tables of '
           '%d.3. Models are saved in `models/%s%s_tt/`. Run notebook 3 first (the spectra-only models are '
           'compared here).' % (spec['nr'], spec['title'], cov, spec['title'], label, spec['intro'], groups_md,
                                spec['nr'], STEM, tag)),
        code(imports),
        md('## Scheme file'),
        code("scheme_file = '../scheme_synthetic.json'"),
        md('## %d.1 Train and test with %s' % (spec['nr'], cov)),
        code(run('project_synthetic/%s/regression_modeling_%s.json' % (pdir, cov))),
        md('## %d.2 Independent validation: spectra only and spectra + %s\n\nBoth model sets on the validation '
           'spectra; per indicator one row of spectra-only models and one row with %s (prediction columns '
           '`<indicator>__<regressor>_tt` and `<indicator>__<regressor>+%s_tt`).' % (spec['nr'], cov, cov, label)),
        code(run('project_synthetic/%s/predict_validation_%s.json' % (pdir, cov))),
        md('## %d.3 Compare\n\nr2 and RMSE of both model sets on the same validation samples (those the covariate '
           'models predict), `change` = with %s − spectra only (negative RMSE change = better); then the RMSE per '
           'group: a covariate can help in a group where the spectra-only model is biased even when the overall '
           'metrics hardly change.' % (spec['nr'], cov)),
        code(compare),
    ]
    nb = dict(nb4, cells=cells)
    dump(nb, '%d_ml_model_predict_%s.ipynb' % (spec['nr'], cov))
    print('built', cov)

COMPARE = r'''# Spectra only vs spectra + covariate, on the samples both model sets predict
import json
import numpy as np
import pandas as pd

from src.ai4sh.machine_learning_model import _compute_metrics

covariate = 'COVLABEL'
pred_dir  = 'data/predictions/synthetic_validation_10nm_COV'
params    = json.load(open('process/covariate_COV/regression_modeling_COV.json'))['process'][0]['parameters']
grouping  = (params.get('class_grouping') or [{}])[0]
group_of  = {c: '|'.join(g) for g in grouping.get('groups', []) for c in g}

pred = pd.read_parquet(path.join(pred_dir, 'synthetic_validation_10nm_pred.parquet'))
# Group of each sample; None: no class or a class left out by class_grouping
pred['group'] = pred[covariate].map(lambda c: None if pd.isna(c) else group_of.get(str(c), None if group_of else str(c)))
models = json.load(open(path.join(pred_dir, 'synthetic_validation_10nm_pred.json')))['models']

overall, per_group = [], []
for m in models:
    indicator, rest = m['column'].split('__')
    if '+' in rest:
        continue
    regressor, mode = rest.rsplit('_', 1)
    cols = {'spectra': m['column'], '+' + covariate: '%s__%s+%s_%s' % (indicator, regressor, covariate, mode)}
    if cols['+' + covariate] not in pred.columns:
        continue
    ok = pred[indicator].notna() & pred[list(cols.values())].notna().all(axis=1)
    for model, col in cols.items():
        met = _compute_metrics(pred.loc[ok, indicator].values, pred.loc[ok, col].values)
        overall.append(dict(indicator=indicator, regressor=regressor, model=model, n=int(ok.sum()),
                            r2=met['r2'], rmse=met['rmse']))
        for g, sub in pred[ok].groupby('group'):
            per_group.append(dict(indicator=indicator, regressor=regressor, model=model, group=g, n=len(sub),
                                  rmse=float(np.sqrt(((sub[col] - sub[indicator]) ** 2).mean()))))

overall = pd.DataFrame(overall)
table = overall.pivot_table(index=['indicator', 'regressor'], columns='model', values=['r2', 'rmse'])
for v in ('r2', 'rmse'):
    table[(v, 'change')] = table[(v, '+' + covariate)] - table[(v, 'spectra')]
print('validation samples compared:', overall.groupby('indicator')['n'].max().to_dict())
display(table.round(3))

per_group = pd.DataFrame(per_group)
print('validation samples per group:', per_group.groupby('group')['n'].max().to_dict())
with pd.option_context('display.max_columns', None, 'display.width', 200):
    display(per_group.pivot_table(index=['indicator', 'regressor', 'model'], columns='group', values='rmse').round(3))
'''

if __name__ == '__main__':
    for cov in sys.argv[1:] or SPECS:
        build(cov)
