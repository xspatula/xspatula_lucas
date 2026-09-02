"""
Assemble the harmonised LUCAS 2009 lab/geo/land-use data from 5 input files
into a single csv: 2009/LUCAS_2009_labdata_corr.csv

Row sources (stacked, one output row per input row):
    1. LUCAS.SOIL_corr.csv                  - main 2009 campaign
    2. SoilAttr_LUCAS_2012_BG_RO.dbf        - 2012 complement, Bulgaria/Romania
    3. SoilAttr_ICELAND.dbf                 - complement, Iceland
    4. SoilAttr_LUCAS_2009_CYP_MLT.dbf      - complement, Cyprus/Malta

The dbf files carry no sample.ID / date / SURV_DATE / LC1 / LU1 / mineral /
WRBFU, so those columns are left blank for their rows.

After stacking, PTotal2009.dbf is joined on POINT_ID and appended as the
24th column 'PTotal' (blank where POINT_ID has no match).

Finally ../LUCAS_Text_All_10032025.csv is joined on POINT_ID / POINTID:
  - coarse/clay/silt/sand are filled in from it only where the value is
    missing (blank or 'NA') in the assembled row
  - texture_class_USDA and texture_class_ISSS are appended as columns 25/26
"""

import csv
import os
from dbfread import DBF

OUT_COLUMNS = [
    "sample.ID", "POINT_ID", "iso.country", "date", "SURV_DATE",
    "GPS_LONG", "GPS_LAT", "LC1", "LU1", "mineral", "WRBFU",
    "coarse", "clay", "silt", "sand",
    "pH.in.CaCl2", "pH.in.H2O", "OC", "CaCO3", "N", "P", "K", "CEC",
]

TEXTURE_COLUMNS = ["coarse", "clay", "silt", "sand"]
TEXTURE_SRC_MAP = {"coarse": "Coarse", "clay": "Clay", "silt": "Silt", "sand": "Sand"}

FINAL_COLUMNS = OUT_COLUMNS + ["PTotal", "texture_class_USDA", "texture_class_ISSS"]

DST_FILENAME = "LUCAS_2009_labdata.csv"

# input files, all relative to the LUCAS 2009 directory except TEXTURE_SRC,
# which lives one directory above it
MAIN_CSV = "LUCAS.SOIL_corr.csv"
DBF_2012_BG_RO = "SoilAttr_LUCAS_2012_BG_RO.dbf"
DBF_ICELAND = "SoilAttr_ICELAND.dbf"
DBF_CYP_MLT = "SoilAttr_LUCAS_2009_CYP_MLT.dbf"
PTOTAL_DBF = "PTotal2009.dbf"
TEXTURE_CSV = "LUCAS_Text_All_10032025.csv"


def clean(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return value


def rows_from_main_csv(path):
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        header = next(reader)
        idx = {name: i for i, name in enumerate(header)}
        cols = [idx[c] for c in OUT_COLUMNS]
        for row in reader:
            yield [clean(row[i]) for i in cols]


def rows_from_dbf(path):
    """Map a complementary 2012/CYP-MLT/ICELAND dbf onto OUT_COLUMNS."""
    for rec in DBF(path, load=False, encoding="latin1"):
        rec = {k.strip(): v for k, v in rec.items()}  # ICELAND has ' Long'
        row = {c: "" for c in OUT_COLUMNS}
        row["POINT_ID"] = clean(rec.get("POINT_ID"))
        row["iso.country"] = clean(rec.get("NUTS_0"))
        row["GPS_LONG"] = clean(rec.get("Long"))
        row["GPS_LAT"] = clean(rec.get("Lat"))
        row["coarse"] = clean(rec.get("coarse"))
        row["clay"] = clean(rec.get("clay"))
        row["silt"] = clean(rec.get("silt"))
        row["sand"] = clean(rec.get("sand"))
        row["pH.in.CaCl2"] = clean(rec.get("pHinCaCl2"))
        row["pH.in.H2O"] = clean(rec.get("pHinH2O"))
        row["OC"] = clean(rec.get("OC"))
        row["CaCO3"] = clean(rec.get("CaCO3"))
        row["N"] = clean(rec.get("N"))
        row["P"] = clean(rec.get("P"))
        row["K"] = clean(rec.get("K"))
        row["CEC"] = clean(rec.get("CEC"))
        yield [row[c] for c in OUT_COLUMNS]


def load_ptotal(path):
    ptotal = {}
    for rec in DBF(path, load=False, encoding="latin1"):
        point_id = str(clean(rec.get("POINT_ID")))
        ptotal[point_id] = clean(rec.get("PTotal"))
    return ptotal


def load_texture(path):
    texture = {}
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        header = next(reader)
        idx = {name: i for i, name in enumerate(header)}
        for row in reader:
            point_id = clean(row[idx["POINTID"]])
            texture[point_id] = {
                "coarse": clean(row[idx["Coarse"]]),
                "clay": clean(row[idx["Clay"]]),
                "silt": clean(row[idx["Silt"]]),
                "sand": clean(row[idx["Sand"]]),
                "USDA": clean(row[idx["USDA"]]),
                "ISSS": clean(row[idx["ISSS"]]),
            }
    return texture


def is_missing(value):
    if not isinstance(value, str):
        return value is None
    return value == "" or value.strip().upper() == "NA"


def main(path_to_LUCAS_2009_directory, path_to_output_directory):
    texture_src = os.path.join(
        os.path.dirname(os.path.normpath(path_to_LUCAS_2009_directory)), TEXTURE_CSV
    )
    ptotal = load_ptotal(os.path.join(path_to_LUCAS_2009_directory, PTOTAL_DBF))
    texture = load_texture(texture_src)
    point_id_idx = OUT_COLUMNS.index("POINT_ID")

    os.makedirs(path_to_output_directory, exist_ok=True)
    dst = os.path.join(path_to_output_directory, DST_FILENAME)

    with open(dst, "w", newline="", encoding="utf-8") as fout:
        writer = csv.writer(fout)
        writer.writerow(FINAL_COLUMNS)

        n = 0
        n_ptotal_matched = 0
        n_texture_filled = 0
        n_texture_matched = 0
        for source_rows in (
            rows_from_main_csv(os.path.join(path_to_LUCAS_2009_directory, MAIN_CSV)),
            rows_from_dbf(os.path.join(path_to_LUCAS_2009_directory, DBF_2012_BG_RO)),
            rows_from_dbf(os.path.join(path_to_LUCAS_2009_directory, DBF_ICELAND)),
            rows_from_dbf(os.path.join(path_to_LUCAS_2009_directory, DBF_CYP_MLT)),
        ):
            for row in source_rows:
                point_id = str(row[point_id_idx])

                p = ptotal.get(point_id, "")
                if p != "":
                    n_ptotal_matched += 1

                tex = texture.get(point_id)
                usda = ""
                isss = ""
                if tex is not None:
                    n_texture_matched += 1
                    for col in TEXTURE_COLUMNS:
                        i = OUT_COLUMNS.index(col)
                        if is_missing(row[i]) and not is_missing(tex[col]):
                            row[i] = tex[col]
                            n_texture_filled += 1
                    usda = tex["USDA"]
                    isss = tex["ISSS"]

                writer.writerow(row + [p, usda, isss])
                n += 1

    print(f"Wrote {n} rows, {len(FINAL_COLUMNS)} columns to {dst}")
    print(f"PTotal matched for {n_ptotal_matched}/{n} rows")
    print(f"Texture row matched for {n_texture_matched}/{n} rows")
    print(f"Texture values (coarse/clay/silt/sand) back-filled: {n_texture_filled}")


if __name__ == "__main__":
    print("Starting to build LUCAS lab data for 2009")

    path_to_LUCAS_2009_directory = "/Users/thomasgumbricht/GitHub_xspatula/LUCAS_FIX/2009"

    path_to_output_directory = "/Users/thomasgumbricht/GitHub_xspatula/LUCAS_FIX/2009/output"

    main(path_to_LUCAS_2009_directory, path_to_output_directory)
