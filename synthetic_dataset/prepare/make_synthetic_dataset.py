"""Build two synthetic soil datasets from LUCAS 2015 for examples and training.

- calibration (model formulation): N_CAL (2000) composite samples, sampling log "synthetic calibration 2025"
- validation (independent):        N_VAL (300) composite samples, sampling log "synthetic validation 2026"

Every synthetic sample is a random-weight mixture of 3 LUCAS 2015 points that share
land cover family, land use family and BIOGEO16 region and lie within MAX_DIST_M of
each other. The same weights (Dirichlet(ALPHA)) are applied to:

- spectra:      mixed as absorbance (log10(1/R)), 0.5 nm -> 10 nm bin means (400-2500 nm,
                211 bands), the two LUCAS scans per point averaged first; stored as
                diffuse reflectance (10**-A) like the LUCAS import
- lab values:   OC, N, EC weighted means; pH(H2O) mixed as H+ concentration; clay/silt/sand
                weighted and renormalised to 100 (only if all 3 sources have texture)
- coordinates:  weighted mean of lon/lat

A value is left missing if any of the 3 sources misses it. Calibration and validation
composites never share a source point. No extra noise is added.

Output (all under synthetic_dataset/):
- import_data/... excel files for insert_tabular_data, spectra JSON + pilot files, job files
- data/synthetic_{calibration,validation}.csv  flat tables (spectra as reflectance)
- prepare/output/composite_sources.csv          source LUCAS point ids and weights (local only)

LUCAS 2015 is licensed by ESDAC/JRC: this output is derived data, keep it local.

Run: python make_synthetic_dataset.py   (about 5-10 minutes; spectra are cached after the first run)
"""

import csv
import json
import os
import sys
from datetime import date, timedelta

import numpy as np
import openpyxl

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)  # synthetic_dataset = project root
REPO = os.path.dirname(ROOT)

# Reuse the LUCAS 2015 converter's readers (coordinates, 2009 texture backfill)
sys.path.insert(0, os.path.join(REPO, 'lucas', 'prepare_lucas_data'))
import lucas_2015_to_xspatula as conv  # noqa: E402

CSV_PATH = conv.CSV_PATH
SEED = 20261104
N_CAL = 2000
N_VAL = 300
ALPHA = 2.0             # Dirichlet concentration: 2 = clearly unequal but no single-source composites
MAX_DIST_M = 50000      # max distance between the 3 sources (LAEA metres)

CACHE_FPN = os.path.join(HERE, 'cache', 'lucas2015_spectra_10nm.npz')
OUT_FP = os.path.join(HERE, 'output')

WAVELENGTHS = np.arange(400, 2501, 10).astype(float)  # 211 band centres

# LUCAS 2015 column -> indicator, decimals
LAB_COLUMNS = [('OC', '@c-org', 1), ('N', '@n-tot', 2), ('EC', '@ec', 2),
               ('pH(H2O)', '@ph-h2o', 2), ('clay', '@clay', 1), ('silt', '@silt', 1), ('sand', '@sand', 1)]
TEXTURE = ('clay', 'silt', 'sand')
REQUIRED = ('OC', 'N', 'pH(H2O)')

# Names in the database
DATASET = {'name': 'synthetic soil spectral library', 'alias': 'synthetic', 'tag': 'synthetic',
           'display_name': 'Synthetic soil spectral library'}
DATA_SOURCE = 'xspatula synthetic'
DATA_SOURCE_ALIAS = 'xspatula-synthetic'
CONTACT_NAME = 'Dummy Person'
CONTACT_EMAIL = 'dummy.person@example.org'
LAB_PROVISION = 'lucas wetlab 2015'
SPECTRA_PROVISION = 'foss xds 10nm'
SPECTRA_SERIAL = 'synthetic'
LANDSCAPE_PROVISION = 'human interpretation'
BIOGEO_PROVISION = 'compilation'
BIOGEO_OBSERVED_AT = 20160331
# Preparation of lab and spectra samples (name and alias are both 'ds2'); it is part of the composed
# observation log name: <sampling log>@<provision>#<preparation alias>
PREPARATION = 'ds2'

SETS = {
    'calibration': {'n': N_CAL, 'prefix': 'cal', 'campaign': 'synthetic calibration', 'campaign_tag': 'syn-cal',
                    'display': 'Synthetic calibration', 'year': 2025,
                    'abstract': 'Model formulation (calibration) set: %d synthetic composite topsoil samples' % N_CAL},
    'validation': {'n': N_VAL, 'prefix': 'val', 'campaign': 'synthetic validation', 'campaign_tag': 'syn-val',
                   'display': 'Synthetic validation', 'year': 2026,
                   'abstract': 'Independent validation set: %d synthetic composite topsoil samples' % N_VAL},
}


def sampling_log_name(s):
    return '%s %s' % (s['campaign'], s['year'])


def obs_log_name(s, provision, preparation=None):
    ''' Same as the auto_name concat of manage_observation_log (name):
    '%s@%s#%s#%s' %(sampling_log_name, provision_name, preparation_alias?, rescan_nr?) '''
    name = '%s@%s' % (sampling_log_name(s), provision)
    return '%s#%s' % (name, preparation) if preparation else name


# ---------------------------------------------------------------------------
# read LUCAS 2015
# ---------------------------------------------------------------------------

def load_points():
    ''' Main csv + coordinates + 2009 texture backfill + master grid (BIOGEO16, LAEA x/y) '''
    _h, idx, rows = conv.load_main_csv(os.path.join(CSV_PATH, conv.MAIN_CSV_FILENAME))
    coords = conv.load_coords(os.path.join(CSV_PATH, conv.COORDS_DBF_FILENAME))
    points = {}
    for row in rows:
        pid = row[idx['Point_ID']].strip()
        if pid not in coords:
            continue
        p = {'POINT_ID': pid, 'lon': coords[pid][0], 'lat': coords[pid][1],
             'LC1': row[idx['LC1']].strip().lower(), 'LU1': row[idx['LU1']].strip().lower(),
             'NUTS_0': row[idx['NUTS_0']].strip(),
             'REVISITED': row[idx['Revisited_point']].strip().lower() == 'yes'}
        for col in ('coarse',) + TEXTURE + ('OC', 'N', 'EC', 'pH(H2O)'):
            p[col] = conv.try_float(row[idx[col]])
        points[pid] = p
    print('  %d LUCAS 2015 points with coordinates' % len(points))

    conv.backfill_texture_from_2009(list(points.values()),
                                    os.path.join(conv.LUCAS_2009_ROOT, conv.LUCAS_2009_MAIN_CSV_FILENAME))

    with open(os.path.join(CSV_PATH, conv.MASTER_GRID_FILENAME), newline='', encoding='utf-8', errors='replace') as f:
        reader = csv.reader(f)
        header = next(reader)
        i_pid, i_bg, i_x, i_y = (header.index(c) for c in ('POINT_ID', 'BIOGEO16', 'X_LAEA', 'Y_LAEA'))
        for row in reader:
            p = points.get(row[i_pid].strip())
            if p is None:
                continue
            bg = row[i_bg].strip()
            p['BIOGEO16'] = None if bg in conv.BIOGEO_MISSING_VALUES else bg.lower()
            p['x'] = conv.try_float(row[i_x])
            p['y'] = conv.try_float(row[i_y])
    return points


def bin_matrix(native_wl):
    ''' Averaging matrix native bands -> 10 nm bins centred on WAVELENGTHS ([c-5, c+5)) '''
    b = np.floor((np.asarray(native_wl) - 395.0) / 10.0).astype(int)
    M = np.zeros((len(native_wl), len(WAVELENGTHS)))
    ok = (b >= 0) & (b < len(WAVELENGTHS))
    M[np.where(ok)[0], b[ok]] = 1.0
    return M / M.sum(axis=0, keepdims=True)


def load_spectra(point_ids):
    ''' Mean 10 nm absorbance per point (scans averaged); cached as npz '''
    if os.path.exists(CACHE_FPN):
        z = np.load(CACHE_FPN, allow_pickle=False)
        print('  spectra from cache: %d points' % len(z['ids']))
        return dict(zip(z['ids'].tolist(), z['absorbance']))

    countries = sorted({pid_c for pid_c in point_ids.values()})
    paths, missing = conv.spectra_paths_for_countries(os.path.join(CSV_PATH, conv.SPECTRA_SUBDIR), countries)
    if missing:
        print('  NOTE: no spectra file for %s' % ', '.join(missing))
    sums, counts, M = {}, {}, None
    for path in paths:
        with open(path, newline='', encoding='utf-8', errors='replace') as f:
            reader = csv.reader(f)
            header = next(reader)
            i_pid, i0 = header.index('PointID'), header.index('400')
            if M is None:
                M = bin_matrix([float(h) for h in header[i0:]])
            for row in reader:
                pid = row[i_pid].strip()
                if pid not in point_ids:
                    continue
                a = np.asarray(row[i0:], dtype=float) @ M
                sums[pid] = sums.get(pid, 0) + a
                counts[pid] = counts.get(pid, 0) + 1
        print('    %s: %d points so far' % (os.path.basename(path), len(sums)))
    ids = sorted(sums)
    absorbance = np.array([sums[i] / counts[i] for i in ids])
    os.makedirs(os.path.dirname(CACHE_FPN), exist_ok=True)
    np.savez_compressed(CACHE_FPN, ids=np.array(ids), absorbance=absorbance)
    return dict(zip(ids, absorbance))


# ---------------------------------------------------------------------------
# triplets and mixing
# ---------------------------------------------------------------------------

def landscape_codes():
    ''' From the landscape utility excel: genus -> family maps for land cover and land use,
    and a BIOGEO16 spelling map (master grid "BlackSea" -> utility alias "black sea") '''
    xl = os.path.join(ROOT, 'import_data', 'utility', 'landscape', 'excel')
    parents = {}
    for kind, fn in (('lc', 'landcover.xlsx'), ('lu', 'landuse.xlsx')):
        rows = list(openpyxl.load_workbook(os.path.join(xl, fn), read_only=True).active.iter_rows(values_only=True))
        i_rank, i_parent, i_alias = 0, 1, rows[0].index('alias')
        parents[kind] = {str(r[i_alias]).lower(): (str(r[i_parent]).lower() if r[i_rank] == 'genus' else None)
                         for r in rows[1:] if r[i_alias]}
    rows = list(openpyxl.load_workbook(os.path.join(xl, 'biogeo16.xlsx'), read_only=True).active.iter_rows(values_only=True))
    i_alias = rows[0].index('alias')
    biogeo = {str(r[i_alias]).lower().replace(' ', ''): str(r[i_alias]).lower() for r in rows[1:] if r[i_alias]}
    return parents, biogeo


def family(code, parents):
    ''' Genus code -> its family (b31 -> b10, u111 -> u110); family/order codes unchanged '''
    return parents.get(code) or code


def build_triplets(points, rng, parents):
    ''' Greedy disjoint triplets of nearby points within each stratum '''
    strata = {}
    for p in points:
        key = (family(p['LC1'], parents['lc']), family(p['LU1'], parents['lu']), p['BIOGEO16'])
        strata.setdefault(key, []).append(p)
    triplets = {}
    for key, members in strata.items():
        if len(members) < 3:
            continue
        xy = np.array([(m['x'], m['y']) for m in members])
        used = np.zeros(len(members), bool)
        for i in rng.permutation(len(members)):
            if used[i]:
                continue
            d = np.hypot(*(xy - xy[i]).T)
            d[used] = np.inf
            d[i] = np.inf
            nn = np.argsort(d)[:2]
            if len(nn) < 2 or d[nn[1]] > MAX_DIST_M:
                continue
            # the two neighbours must also be close to each other
            if np.hypot(*(xy[nn[0]] - xy[nn[1]])) > MAX_DIST_M:
                continue
            used[[i, *nn]] = True
            triplets.setdefault(key, []).append([members[i], members[nn[0]], members[nn[1]]])
    return triplets


def allocate(triplets, n_total, rng):
    ''' Proportional allocation with at least 1 per stratum, total exactly n_total '''
    keys = sorted(triplets, key=str)
    avail = np.array([len(triplets[k]) for k in keys])
    alloc = np.maximum(1, np.floor(n_total * avail / avail.sum())).astype(int)
    alloc = np.minimum(alloc, avail)
    order = np.argsort(-avail)
    while alloc.sum() < n_total:
        for j in order:
            if alloc.sum() == n_total:
                break
            if alloc[j] < avail[j]:
                alloc[j] += 1
    while alloc.sum() > n_total:
        for j in order:
            if alloc.sum() == n_total:
                break
            if alloc[j] > 1:
                alloc[j] -= 1
    chosen = {}
    for k, n in zip(keys, alloc):
        idx = rng.permutation(len(triplets[k]))[:n]
        chosen[k] = [triplets[k][i] for i in idx]
    return chosen


def split(chosen, n_val, n_total):
    ''' Stratified calibration/validation split of the chosen triplets '''
    exp = {k: len(v) * n_val / n_total for k, v in chosen.items()}
    nv = {k: int(np.floor(e)) for k, e in exp.items()}
    rest = n_val - sum(nv.values())
    for k in sorted(exp, key=lambda k: -(exp[k] - nv[k]))[:rest]:
        nv[k] += 1
    cal, val = [], []
    for k, trips in chosen.items():
        val += [(k, t) for t in trips[:nv[k]]]
        cal += [(k, t) for t in trips[nv[k]:]]
    return cal, val


def mix(key, trip, spectra, rng):
    w = rng.dirichlet([ALPHA] * 3)
    c = {'lon': float(np.dot(w, [p['lon'] for p in trip])), 'lat': float(np.dot(w, [p['lat'] for p in trip])),
         'weights': w, 'sources': [p['POINT_ID'] for p in trip]}
    lcs = {p['LC1'] for p in trip}
    lus = {p['LU1'] for p in trip}
    c['landcover'] = lcs.pop() if len(lcs) == 1 else key[0]
    c['landuse'] = lus.pop() if len(lus) == 1 else key[1]
    c['biogeo16'] = key[2]
    for col in ('OC', 'N', 'EC'):
        v = [p[col] for p in trip]
        c[col] = None if None in v else float(np.dot(w, v))
    ph = [p['pH(H2O)'] for p in trip]
    c['pH(H2O)'] = float(-np.log10(np.dot(w, 10.0 ** -np.array(ph))))
    tex = [[p[t] for t in TEXTURE] for p in trip]
    if any(None in t for t in tex):
        for t in TEXTURE:
            c[t] = None
    else:
        mixed = w @ np.array(tex)
        mixed = 100 * mixed / mixed.sum()
        for t, v in zip(TEXTURE, mixed):
            c[t] = float(v)
    c['absorbance'] = w @ np.array([spectra[p['POINT_ID']] for p in trip])
    return c


# ---------------------------------------------------------------------------
# writers
# ---------------------------------------------------------------------------

def write_xlsx(fpn, header, rows):
    os.makedirs(os.path.dirname(fpn), exist_ok=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Sheet1'
    ws.append(header)
    for r in rows:
        ws.append([None if v is None else v for v in r])
    wb.save(fpn)


def write_json(fpn, payload):
    os.makedirs(os.path.dirname(fpn), exist_ok=True)
    with open(fpn, 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2)


def insert_process(tabular_path, process, dst_path):
    return {'process': 'insert_tabular_data', 'overwrite': True,
            'parameters': {'process': process, 'tabular_data_path': tabular_path, 'dst_path': dst_path}}


def write_dataset_metadata():
    base = 'import_data/dataset_metadata'
    xl = os.path.join(ROOT, base, 'excel')
    write_xlsx(os.path.join(xl, 'data_source.xlsx'),
               ['name', 'alias', 'display_name', 'url', 'territory_id__territory_name', 'contact_name', 'contact_email'],
               [[DATA_SOURCE, DATA_SOURCE_ALIAS, 'Xspatula synthetic', 'https://xspatula.github.io', 'eu',
                 CONTACT_NAME, CONTACT_EMAIL]])
    write_xlsx(os.path.join(xl, 'person.xlsx'),
               ['data_source_id__data_source_name', 'first_name', 'last_name', 'email', 'territory_id__territory_name',
                'position'],
               [[DATA_SOURCE_ALIAS, 'Dummy', 'Person', CONTACT_EMAIL, 'eu', 'Data steward']])
    write_xlsx(os.path.join(xl, 'dataset.xlsx'),
               ['name', 'alias', 'tag', 'display_name', 'data_source_id__data_source_name', 'contact_name',
                'contact_email', 'begun_at', 'ended_at', 'species_id__species_name', 'profiling_id__profiling_name',
                'license_id__license_name', 'substance_array', 'keyword_array', 'abstract', 'laboratory',
                'territory_id__territory_name', 'spatial_reference_id__spatial_reference_name'],
               [[DATASET['name'], DATASET['alias'], DATASET['tag'], DATASET['display_name'], DATA_SOURCE_ALIAS,
                 CONTACT_NAME, CONTACT_EMAIL, 20250101, 20261231, 'soil', 'depth cm', 'jrc-lucas', 'soil',
                 'topsoil, synthetic, example, europe',
                 'Synthetic composite topsoil samples made by random-weight mixing of 3 LUCAS 2015 points. '
                 'For examples and training only.', 1, 'EU', 'geographic']])
    provisions = ','.join([LAB_PROVISION, SPECTRA_PROVISION, LANDSCAPE_PROVISION, BIOGEO_PROVISION])
    write_xlsx(os.path.join(xl, 'campaign.xlsx'),
               ['dataset_id__dataset_name', 'name', 'tag', 'display_name', 'contact_name', 'contact_email', 'begun_at',
                'ended_at', 'abstract', 'field', 'laboratory', 'territory_id__territory_name',
                'spatial_reference_id__spatial_reference_name', 'location_method_id__location_method_name',
                'location_error', 'location_error_unit_id__unit_name', 'provision_id__provision_name_array'],
               [[DATASET['alias'], s['campaign'], s['campaign_tag'], s['display'], CONTACT_NAME, CONTACT_EMAIL,
                 int('%d0501' % s['year']), int('%d1031' % s['year']), s['abstract'], 1, 1, 'EU', 'geographic', 'gps',
                 50, 'm', provisions] for s in SETS.values()])
    write_xlsx(os.path.join(xl, 'sampling_log.xlsx'),
               ['campaign_id__campaign_name', 'contact_name', 'contact_email', 'datetime_tag', 'abstract',
                'sampling_tool_array', 'begun_at', 'ended_at'],
               [[s['campaign'], CONTACT_NAME, CONTACT_EMAIL, str(s['year']), s['abstract'], 'spade',
                 int('%d0501' % s['year']), int('%d0930' % s['year'])] for s in SETS.values()])
    pilot = []
    for table in ('data_source', 'person', 'dataset', 'campaign', 'sampling_log'):
        write_json(os.path.join(ROOT, base, 'insert_process', '%s.json' % table),
                   {'process': [insert_process('%s/excel/%s.xlsx' % (base, table), 'manage_%s' % table,
                                               '%s/insert_process/staging' % base)]})
        pilot.append('%s.json' % table)
    with open(os.path.join(ROOT, base, 'insert_dataset_metadata.txt'), 'w') as f:
        f.write('###########################################\n'
                '##### SYNTHETIC DATASET METADATA ##########\n'
                '##### excel -> database in one step ######\n'
                '###########################################\n\n'
                '# order matters: source, person, dataset, campaign, sampling_log\n')
        f.write('\n'.join(pilot) + '\n')
    write_json(os.path.join(ROOT, base, 'job_insert_dataset_metadata.json'),
               {'process': {'job_folder': base, 'process_sub_folder': 'insert_process',
                            'pilot_file': 'insert_dataset_metadata.txt'}})


def write_observation_logs():
    base = 'import_data/observation_log'
    rows = []
    for s in SETS.values():
        sl = sampling_log_name(s)
        rows.append([sl, LAB_PROVISION, PREPARATION, 'ds2', 'amb', 1, None, None, None])
        rows.append([sl, SPECTRA_PROVISION, PREPARATION, 'ds2', 'amb', 1, None, None, None])
        rows.append([sl, LANDSCAPE_PROVISION, None, None, None, None, 1, None, None])
        rows.append([sl, BIOGEO_PROVISION, None, None, None, None, None, None, 1])
    write_xlsx(os.path.join(ROOT, base, 'excel', 'observation_log.xlsx'),
               ['sampling_log_id__sampling_log_name', 'provision_id__provision_name',
                'preparation_id__preparation_name', 'preservation_id__preservation_name', 'storage_id__storage_name',
                'laboratory', 'field', 'senses', 'auxiliary'], rows)
    write_json(os.path.join(ROOT, base, 'insert_observation_log.json'),
               {'process': [insert_process('%s/excel/observation_log.xlsx' % base, 'manage_observation_log',
                                           '%s/staging' % base)]})


def write_set(set_key, s, composites):
    ''' Excel files (geolocation, sample, lab, landscape) and spectra JSON for one set '''
    sl = sampling_log_name(s)
    geo, smp, lab, lc, lu, bg = [], [], [], [], [], []
    spec_files = []
    spec_fp = os.path.join(ROOT, 'import_data', 'spectra', set_key, 'manage_process')
    os.makedirs(spec_fp, exist_ok=True)
    for c in composites:
        geo.append([c['geolocation'], round(c['lon'], 6), round(c['lat'], 6), round(c['lat'], 6), round(c['lon'], 6)])
        smp.append([sl, c['tag'], c['sample'], c['sampled_at'], 'soil', c['geolocation'], 0, 20, 'general',
                    'composite'])
        lab.append([obs_log_name(s, LAB_PROVISION, PREPARATION), c['sample'], LAB_PROVISION, 'a', 0, c['lab_at']] +
                   [None if c[col] is None else round(c[col], dec) for col, _ind, dec in LAB_COLUMNS])
        lc.append([obs_log_name(s, LANDSCAPE_PROVISION), c['geolocation'], c['landcover'], c['sampled_at']])
        lu.append([obs_log_name(s, LANDSCAPE_PROVISION), c['geolocation'], c['landuse'], c['sampled_at']])
        bg.append([obs_log_name(s, BIOGEO_PROVISION), c['geolocation'], c['biogeo16'], BIOGEO_OBSERVED_AT])
        fn = '%s_spectra.json' % c['tag']
        write_json(os.path.join(spec_fp, fn), {'process': [{'process': 'manage_observation', 'parameters': {
            'observation_log_id__observation_log_name': obs_log_name(s, SPECTRA_PROVISION, PREPARATION),
            'sample_id__sample_name': c['sample'],
            'provision_id__provision_name': SPECTRA_PROVISION,
            'provision_serial_nr_id__provision_serial_nr_name': SPECTRA_SERIAL,
            'subsample': 'a', 'replicate': 0,
            'observed_at': c['spectra_at'],
            '@diffuse reflectance': [round(float(v), 6) for v in 10.0 ** -c['absorbance']]}}]})
        spec_files.append(fn)

    xl = os.path.join(ROOT, 'import_data', 'sample', 'excel')
    write_xlsx(os.path.join(xl, 'geolocation_%s.xlsx' % set_key),
               ['name', 'x_coordinate', 'y_coordinate', 'latitude', 'longitude'], geo)
    write_xlsx(os.path.join(xl, 'sample_%s.xlsx' % set_key),
               ['sampling_log_id__sampling_log_name', 'tag', 'name', 'sampled_at', 'species_id__species_name',
                'geolocation_id__geolocation_name', 'profile_min', 'profile_max', 'proximity_id__proximity_name',
                'composition_id__composition_name'], smp)
    write_xlsx(os.path.join(ROOT, 'import_data', 'lab', 'excel', 'lab_%s.xlsx' % set_key),
               ['observation_log_id__observation_log_name', 'sample_id__sample_name', 'provision_id__provision_name',
                'subsample', 'replicate', 'observed_at'] + [ind for _c, ind, _d in LAB_COLUMNS], lab)
    xl = os.path.join(ROOT, 'import_data', 'landscape', 'excel')
    write_xlsx(os.path.join(xl, 'land_cover_%s.xlsx' % set_key),
               ['observation_log_id__observation_log_name', 'geolocation_id__geolocation_name',
                'landcover_id__landcover_name', 'observed_at'], lc)
    write_xlsx(os.path.join(xl, 'land_use_%s.xlsx' % set_key),
               ['observation_log_id__observation_log_name', 'geolocation_id__geolocation_name',
                'landuse_id__landuse_name', 'observed_at'], lu)
    write_xlsx(os.path.join(xl, 'biogeo16_%s.xlsx' % set_key),
               ['observation_log_id__observation_log_name', 'geolocation_id__geolocation_name',
                'biogeo16_id__biogeo16_name', 'observed_at'], bg)

    # insert processes (single step) for this set
    for folder, items in (('sample', [('geolocation_%s.xlsx', 'manage_geolocation'),
                                      ('sample_%s.xlsx', 'manage_geolocated_profile_sample')]),
                          ('lab', [('lab_%s.xlsx', 'manage_observation')]),
                          ('landscape', [('land_cover_%s.xlsx', 'manage_land_cover_observation'),
                                         ('land_use_%s.xlsx', 'manage_land_use_observation'),
                                         ('biogeo16_%s.xlsx', 'manage_biogeo16_observation')])):
        base = 'import_data/%s' % folder
        write_json(os.path.join(ROOT, base, 'insert_%s_%s.json' % (folder, set_key)),
                   {'process': [insert_process('%s/excel/%s' % (base, fn % set_key), proc,
                                               '%s/staging/%s' % (base, set_key)) for fn, proc in items]})

    # spectra: pilot + job (JSON route, arrays do not fit an excel cell)
    spec_base = 'import_data/spectra/%s' % set_key
    with open(os.path.join(ROOT, spec_base, 'spectra_pilot.txt'), 'w') as f:
        f.write('#### synthetic %s spectra (%d) ####\n' % (set_key, len(spec_files)))
        f.write('\n'.join(spec_files) + '\n')
    write_json(os.path.join(ROOT, 'import_data', 'spectra', 'job_spectra_%s.json' % set_key),
               {'process': {'job_folder': spec_base, 'process_sub_folder': 'manage_process',
                            'pilot_file': 'spectra_pilot.txt'}})

    # flat table for pandas / excel users
    os.makedirs(os.path.join(ROOT, 'data'), exist_ok=True)
    with open(os.path.join(ROOT, 'data', 'synthetic_%s.csv' % set_key), 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['sample', 'longitude', 'latitude', 'sampled_at', 'landcover', 'landuse', 'biogeo16'] +
                   [ind[1:] for _c, ind, _d in LAB_COLUMNS] + ['%d' % wl for wl in WAVELENGTHS])
        for c in composites:
            w.writerow([c['sample'], round(c['lon'], 6), round(c['lat'], 6), c['sampled_at'], c['landcover'],
                        c['landuse'], c['biogeo16']] +
                       ['' if c[col] is None else round(c[col], dec) for col, _i, dec in LAB_COLUMNS] +
                       [round(float(v), 6) for v in 10.0 ** -c['absorbance']])


def write_spectrometer():
    base = 'import_data/spectra/spectrometer'
    write_json(os.path.join(ROOT, base, 'manage_process', 'foss_xds_10nm_spectrometer.json'),
               {'process': [{'process': 'manage_spectrometer', 'parameters': {
                   'provision_id__provision_name': SPECTRA_PROVISION,
                   'provision_serial_nr_id__provision_serial_nr_name': SPECTRA_SERIAL,
                   'wavelength_array': WAVELENGTHS.tolist(),
                   'wavelength_unit_id__wavelength_unit_name': 'nm'}}]})
    with open(os.path.join(ROOT, base, 'spectrometer_pilot.txt'), 'w') as f:
        f.write('#### synthetic 10 nm spectrometer ####\nfoss_xds_10nm_spectrometer.json\n')
    write_json(os.path.join(ROOT, 'import_data', 'spectra', 'job_spectrometer.json'),
               {'process': {'job_folder': base, 'process_sub_folder': 'manage_process',
                            'pilot_file': 'spectrometer_pilot.txt'}})


def add_provision_rows():
    ''' Register the 10 nm spectrometer provision in the copied observation utility excel files '''
    xl = os.path.join(ROOT, 'import_data', 'utility', 'observation', 'excel')
    add = {'provision.xlsx': ('name', SPECTRA_PROVISION,
                              [['foss', 'visnir', 'laboratory', SPECTRA_PROVISION, 'foss xds 10nm synthetic',
                                'foss-xds-10nm', 'FOSS XDS 10 nm (synthetic)',
                                'FOSS XDS RCA spectra resampled to 10 nm, synthetic composites', None, None, 1]]),
           'provision_indicator.xlsx': ('provision_id__provision_name', SPECTRA_PROVISION,
                                        [[SPECTRA_PROVISION, ind, '%s spectroscopy' % ind, 'unitless']
                                         for ind in ('reflectance', 'diffuse reflectance', 'absorbance')]),
           'provision_serial_nr.xlsx': ('provision_id__provision_name', SPECTRA_PROVISION,
                                        [[SPECTRA_PROVISION, SPECTRA_SERIAL]])}
    for fn, (key_col, key_val, rows) in add.items():
        fpn = os.path.join(xl, fn)
        wb = openpyxl.load_workbook(fpn)
        ws = wb.active
        header = [c.value for c in ws[1]]
        ki = header.index(key_col)
        # drop earlier synthetic rows (idempotent), then append
        for r in range(ws.max_row, 1, -1):
            if ws.cell(r, ki + 1).value == key_val:
                ws.delete_rows(r)
        for row in rows:
            ws.append(row + [None] * (len(header) - len(row)))
        wb.save(fpn)


def check_codes(composites):
    ''' Every land cover / land use / biogeo code must exist in the utility excel '''
    xl = os.path.join(ROOT, 'import_data', 'utility', 'landscape', 'excel')
    known = {}
    for fn, col in (('landcover.xlsx', 'alias'), ('landuse.xlsx', 'alias'), ('biogeo16.xlsx', 'alias')):
        ws = openpyxl.load_workbook(os.path.join(xl, fn), read_only=True).active
        rows = list(ws.iter_rows(values_only=True))
        i = rows[0].index(col)
        known[fn] = {str(r[i]).lower() for r in rows[1:] if r[i]}
    bad = set()
    for c in composites:
        for fn, key in (('landcover.xlsx', 'landcover'), ('landuse.xlsx', 'landuse'), ('biogeo16.xlsx', 'biogeo16')):
            if c[key] not in known[fn]:
                bad.add((fn, c[key]))
    return bad


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    rng = np.random.default_rng(SEED)
    print('Reading LUCAS 2015 ...')
    points = load_points()
    usable = {pid: p for pid, p in points.items()
              if p.get('BIOGEO16') and p.get('x') is not None and p['LC1'] and p['LU1']
              and all(p[c] is not None for c in REQUIRED)}
    print('  %d points with BIOGEO16, land cover/use and OC, N, pH(H2O)' % len(usable))
    spectra = load_spectra({pid: p['NUTS_0'].upper() for pid, p in usable.items()})
    usable = [p for pid, p in usable.items() if pid in spectra]
    print('  %d of them have spectra' % len(usable))

    parents, biogeo_map = landscape_codes()
    for p in usable:
        p['BIOGEO16'] = biogeo_map.get(p['BIOGEO16'].replace(' ', ''), p['BIOGEO16'])
    triplets = build_triplets(usable, rng, parents)
    n_trip = sum(len(v) for v in triplets.values())
    print('  %d possible triplets in %d strata' % (n_trip, len(triplets)))
    n_total = N_CAL + N_VAL
    if n_trip < n_total:
        sys.exit('Not enough triplets (%d) for %d composites' % (n_trip, n_total))
    chosen = allocate(triplets, n_total, rng)
    cal, val = split(chosen, N_VAL, n_total)

    os.makedirs(OUT_FP, exist_ok=True)
    src_rows = []
    all_comp = []
    for set_key, members in (('calibration', cal), ('validation', val)):
        s = SETS[set_key]
        comps = []
        for n, j in enumerate(rng.permutation(len(members)), start=1):
            key, trip = members[j]
            c = mix(key, trip, spectra, rng)
            c['tag'] = '%s%04d' % (s['prefix'], n)
            c['sample'] = '%s@0-20' % c['tag']
            c['geolocation'] = 'syn@%s' % c['tag']
            d0 = date(s['year'], 5, 1) + timedelta(days=int(rng.integers(0, 153)))
            c['sampled_at'] = int(d0.strftime('%Y%m%d'))
            c['lab_at'] = int((d0 + timedelta(days=45)).strftime('%Y%m%d'))
            c['spectra_at'] = (d0 + timedelta(days=60)).isoformat() + 'T00:00:00+00:00'
            comps.append(c)
            src_rows.append([set_key, c['tag'], '|'.join(key)] + c['sources'] + [round(float(x), 4) for x in c['weights']])
        write_set(set_key, s, comps)
        all_comp += comps
        print('  %s: %d composites written' % (set_key, len(comps)))

    bad = check_codes(all_comp)
    if bad:
        print('  ⚠️  codes missing in the landscape utility: %s' % sorted(bad))

    with open(os.path.join(OUT_FP, 'composite_sources.csv'), 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['set', 'tag', 'stratum', 'point_id_1', 'point_id_2', 'point_id_3', 'w1', 'w2', 'w3'])
        w.writerows(src_rows)

    write_dataset_metadata()
    write_observation_logs()
    write_spectrometer()
    add_provision_rows()

    # summary
    with open(os.path.join(OUT_FP, 'summary.txt'), 'w') as f:
        for set_key in ('calibration', 'validation'):
            comps = [c for c in all_comp if c['tag'].startswith(SETS[set_key]['prefix'])]
            f.write('== %s (%d)\n' % (set_key, len(comps)))
            for col, _i, _d in LAB_COLUMNS:
                v = np.array([c[col] for c in comps if c[col] is not None])
                f.write('  %-8s n=%4d  min=%8.2f  median=%8.2f  max=%8.2f\n' % (col, len(v), v.min(), np.median(v), v.max()))
            for key in ('landcover', 'landuse', 'biogeo16'):
                vals, cnt = np.unique([c[key] for c in comps], return_counts=True)
                f.write('  %s: %d classes, top: %s\n' % (key, len(vals), ', '.join(
                    '%s %d' % (vals[i], cnt[i]) for i in np.argsort(-cnt)[:8])))
    print(open(os.path.join(OUT_FP, 'summary.txt')).read())


if __name__ == '__main__':
    main()
