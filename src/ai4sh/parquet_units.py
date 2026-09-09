'''
Created on 9 September 2026

@author: thomasgumbricht

Round-trip per-indicator units through Parquet files.

Units are stored as custom Parquet file metadata (a JSON-encoded {column: unit} dict),
NOT as a column MultiIndex — Parquet has no native support for column MultiIndex, and
writing one (via pandas/pyarrow) silently degrades to flat columns literally named after
the str() of each tuple (e.g. "('sample_name', '')"), breaking every plain column-name
lookup downstream. File metadata keeps the on-disk columns exactly as before (flat,
single-level strings), so no other code needs to change.
'''

# Standard library imports
import json

# Third-party imports
import pyarrow as pa
import pyarrow.parquet as pq

_UNITS_METADATA_KEY = b'ai4sh_indicator_units'


def Read_parquet_with_units(fpn, **kwargs):
    '''Read a Parquet file, returning (df, {column_name: unit}).

    Returns an empty units dict if the file has no embedded units (e.g. legacy files, or
    files not written via Save_parquet_with_units).
    '''
    table = pq.read_table(fpn, **kwargs)
    df = table.to_pandas()

    units_D = {}
    meta = table.schema.metadata or {}
    raw = meta.get(_UNITS_METADATA_KEY)
    if raw:
        try:
            units_D = json.loads(raw.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            units_D = {}

    return df, units_D


def Save_parquet_with_units(df, fpn, units_D, index=False):
    '''Write df to Parquet, embedding {column_name: unit} as custom file metadata.'''
    table = pa.Table.from_pandas(df, preserve_index=index)
    new_meta = dict(table.schema.metadata or {})
    new_meta[_UNITS_METADATA_KEY] = json.dumps(units_D or {}).encode('utf-8')
    table = table.replace_schema_metadata(new_meta)
    pq.write_table(table, fpn)

