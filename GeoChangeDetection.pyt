# -*- coding: utf-8 -*-
"""
GeoChangeDetection.pyt
======================
Geo Change Detection & QC Review Tool — راصد التغيرات الجغرافية
Enterprise-grade ArcGIS Pro Python Toolbox v5.0.0 (Refined)
Compares two Feature Classes and detects geometry and attribute changes
with an Advanced Multi-Level Geometry Comparison Engine, and optional
QC Review & Issue Tracking correlation module.

Author  : Senior Enterprise GIS & QA/QC Specialist
Version : 5.0.0 (Refined)
Requires: ArcGIS Pro 3.x+, Python 3.x, openpyxl (for Excel output)

Changelog v5.0.0 — Enterprise Refined Architecture
---------------------------------------------------
- Rule 2 (Unique ID Validation): Strict enforcement that uid_field is unique in both
         Original and Modified FCs. Aborts with clear error listing duplicate IDs if found.
- Rule 5 (Coordinate System Consistency): Automatic CRS verification and on-the-fly
         reprojection into common projected CRS for linear metric geometry calculations.
- Rule 6 & Method B (Spatial Join with Ambiguity): Deterministic tie-breaking by largest overlap /
         closest distance, 1-to-1 greedy matching, and ambiguity tolerance flagging:
         "Ambiguous Match — Manual Review Required".
- QC Decision Matrix (v5.0 Rebuilt): Full 30-combination matrix with separated namespaces
         (IT-1..IT-5 and QA-1..QA-5), override rule for missing IDs (QA-4), and explicit rationales.
- Compact JSON Output: Old_Values and New_Values stored as compact, machine-parseable JSON strings.
- Validation / Dry-Run Mode: Added 'validate_only' parameter to check schemas without writing outputs.
- Logging & Auditability: Automated execution audit run log (.log) with Review_Run_ID tracking.
- Output Workspace Constraint: Strict enforcement of File/Enterprise Geodatabase (no shapefiles).
- Attribute Comparison: Default to all common non-system fields, type coercion compatibility checking,
         and 3-column field mapping (Orig_Field, Mod_Field, Compare_As).
- Versioned Settings Persistence: JSON schema version 5.0 with full backward compatibility.

Changelog v4.1.0 — QC Review & Issue Tracking Module
----------------------------------------------------
- Added: Optional "QC Review & Issue Tracking" module.
- Added: Point Feature Class creation for QC Notes template ("QC_Issues") with standard fields
         and coded value domains (QC_Issue_Type, QC_Status, QC_Assessment, Last_Check_Status).
- Added: Correlation and matching engine between historical QC Issues and detected changes by Feature ID.
- Added: Probabilistic assessment classification: "Maybe Changed", "Not Changed", "Needs Review",
         "Feature Not Found", "Feature Deleted".
- CRITICAL: The tool NEVER automatically classifies any issue as "Resolved" or "Potentially Resolved".
         The strongest automated indicator is strictly "Maybe Changed" to guide human verification.
- Added: Output Point Feature Class "QC_Review_Result" preserving original QC point geometry, reviewer
         notes, reviewer name, status, and tracking correlation metrics (Current_Feature_X/Y, Distance).
- Added: Support for multiple QC issues on the same feature, each evaluated independently.
- Added: "QC Review" dedicated tab in Multi-Sheet Excel report and QC summary statistics in "Summary" sheet.
- Added: Interactive "QC Review Summary" section with KPI cards and filterable table in standalone HTML report.
- Added: Automatic unique-value map symbology on QC_Assessment for "QC_Review_Result".
- Added: JSON settings persistence and loading for "qc_review" module with full backward compatibility.

Changelog v4.0.0 — Advanced Geometry Comparison Engine
------------------------------------------------------
- Added: Multi-Level Geometry Comparison Engine evaluating:
         1. Metric Precision (Area & Length Decimal Places)
         2. Vertex Count with configurable tolerance
         3. Spatial Displacement / Centroid & Endpoint Distance vs Spatial Tolerance
         4. Geometry Shape & Topological differences (symmetric difference & vertex deviation)
         5. 3D coordinate evaluation (Z Tolerance) for Point and 3D geometries
- Added: Explicit "Geometry_Change_Reason" tracking (e.g. "Area Changed; Vertex Count Changed",
         "Spatial Position Changed", "Shape Changed", "Z Coordinate Changed").
- Added: Output fields: Area_Changed, Length_Changed, Vertex_Count_Changed, Spatially_Changed,
         Shape_Changed, Geometry_Change_Reason, Old/New_Vertex_Count, Vertex_Count_Diff,
         Old/New_Centroid_X/Y, Centroid_Distance, Area_Decimals, Length_Decimals, Spatial_Tolerance.
- Added: Polyline start/end coordinate tracking (Old_Start_X/Y, Old_End_X/Y, New_Start_X/Y, New_End_X/Y).
- Added: Point coordinate delta tracking (X_Diff, Y_Diff, Z_Diff, Spatial_Distance).
- Added: Categorized Tool UI in ArcGIS Pro: Basic Comparison, Attribute Comparison,
         Geometry Comparison, QC Review / Issue Tracking, Output / Reports.
- Added: Dynamic UI enabling/disabling of parameters based on feature class geometry type.
- Added: Enhanced 4-sheet Excel Report and standalone interactive HTML report.
- Added: Full backward compatibility for legacy JSON configuration files and parameters.

Changelog v3.1.0
-----------------
- Added: "Match Features By" parameter with three matching modes:
         1. By Attribute ID Field   — original behavior, user selects a UID field
         2. By OBJECTID (Automatic) — uses OID@ token; no UID field needed
         3. By Spatial Location     — uses in-memory SpatialJoin to match features
- Added: _build_spatial_mapping() and _prepare_data() single entry points.

Changelog v3.0.0
-----------------
- Added: Filter output FC by change type, HTML report, Map integration, Excel Sheets 3 & 4.
"""

import arcpy
import os
import math
import json
import datetime
import traceback

# ---------------------------------------------------------------------------
# Toolbox
# ---------------------------------------------------------------------------

class Toolbox:
    def __init__(self):
        self.label       = "Geo Change Detection"
        self.alias       = "GeoChangeDetection"
        self.tools       = [ChangeDetectionTool]
        self.description = (
            "Enterprise-grade toolbox v5.0.0 (Refined) for comparing two Feature Classes "
            "and detecting geometry and attribute changes with an Advanced Multi-Level "
            "Geometry Comparison Engine, and an optional QC Review & Issue Tracking module. "
            "Supports attribute-based, OBJECTID-based, and spatial-location-based feature matching."
        )


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_MATCH_BY_ATTR    = "By Attribute ID Field"
_MATCH_BY_ATTR_ALT= "By Unique ID"
_MATCH_BY_OID     = "By OBJECTID (Automatic)"
_MATCH_BY_SPATIAL = "By Spatial Location (Spatial Join)"

CHANGE_AMBIGUOUS  = "Ambiguous Match — Manual Review Required"

_SKIP_FIELD_NAMES = {
    "Shape", "Shape_Length", "Shape_Area",
    "OBJECTID", "FID",
    "Shape.STArea()", "Shape.STLength()",
}

_SKIP_FIELD_TYPES = {
    "OID", "Geometry", "Blob", "Raster", "GlobalID", "Guid"
}

_FIELD_TYPE_FILTER = [
    "Short", "Long", "Float", "Double",
    "Text", "Date", "Integer", "BigInteger",
]

# ---------------------------------------------------------------------------
# QC Review & Issue Tracking Constants & Domain Dictionaries (v5.0 Namespaces)
# ---------------------------------------------------------------------------

QA_CODE_MAYBE_CHANGED = "QA-1"
QA_CODE_NOT_CHANGED   = "QA-2"
QA_CODE_NEEDS_REVIEW  = "QA-3"
QA_CODE_NOT_FOUND     = "QA-4"
QA_CODE_DELETED       = "QA-5"

QC_ASSESSMENT_NOT_CHECKED   = "Not Checked"
QC_ASSESSMENT_MAYBE_CHANGED = "Maybe Changed"
QC_ASSESSMENT_NOT_CHANGED   = "Not Changed"
QC_ASSESSMENT_NEEDS_REVIEW  = "Needs Review"
QC_ASSESSMENT_NOT_FOUND     = "Feature Not Found"
QC_ASSESSMENT_DELETED       = "Feature Deleted"

IT_CODE_GEOM      = "IT-1"
IT_CODE_ATTR      = "IT-2"
IT_CODE_GEOM_ATTR = "IT-3"
IT_CODE_MISSING   = "IT-4"
IT_CODE_EXTRA     = "IT-5"

QC_ISSUE_TYPE_MAP = {
    1: "Geometry Issue",
    2: "Attribute Issue",
    3: "Geometry and Attribute Issue",
    4: "Missing Feature",
    5: "Extra Feature",
    6: "Topology Issue",
    7: "Other",
}
QC_ISSUE_TYPE_CODE_MAP = {v.lower(): k for k, v in QC_ISSUE_TYPE_MAP.items()}

QC_STATUS_MAP = {
    1: "Open",
    2: "In Review",
    3: "Resolved",
    4: "Not Resolved",
}
QC_STATUS_CODE_MAP = {v.lower(): k for k, v in QC_STATUS_MAP.items()}

QC_ASSESSMENT_MAP = {
    0: "Not Checked",
    1: "Maybe Changed",
    2: "Not Changed",
    3: "Needs Review",
    4: "Feature Not Found",
    5: "Feature Deleted",
}
QC_ASSESSMENT_CODE_MAP = {v.lower(): k for k, v in QC_ASSESSMENT_MAP.items()}

QC_QA_CODE_TO_DESC = {
    "QA-1": "Maybe Changed",
    "QA-2": "Not Changed",
    "QA-3": "Needs Review",
    "QA-4": "Feature Not Found",
    "QA-5": "Feature Deleted",
}

QC_QA_DESC_TO_CODE = {v.lower(): k for k, v in QC_QA_CODE_TO_DESC.items()}

# Complete 30-combination decision matrix (v5.0 Refined, Section 6)
# Maps (Issue_Type_Code, Detected_Change_Type) -> (QA_Code, Assessment_Desc, Rationale)
QC_DECISION_MATRIX_V5 = {
    # IT-1 Geometry Issue
    ("IT-1", "Unchanged"):                       ("QA-2", "Not Changed", "No change detected yet — issue still open, not resolved"),
    ("IT-1", "Geometry Changed"):                ("QA-1", "Maybe Changed", "Matches the registered issue"),
    ("IT-1", "Attribute Changed"):               ("QA-3", "Needs Review", "Change doesn't match issue type — mismatch, needs human look"),
    ("IT-1", "Geometry and Attribute Changed"):  ("QA-1", "Maybe Changed", "Geometry component matches"),
    ("IT-1", "Added"):                           ("QA-3", "Needs Review", "Inconsistent: issue predates a feature that didn't exist before"),
    ("IT-1", "Deleted"):                         ("QA-5", "Feature Deleted", "Flagged feature vanished — must be reviewed, not just maybe"),

    # IT-2 Attribute Issue
    ("IT-2", "Unchanged"):                       ("QA-2", "Not Changed", "Still open, unresolved"),
    ("IT-2", "Attribute Changed"):               ("QA-1", "Maybe Changed", "Matches the registered issue"),
    ("IT-2", "Geometry Changed"):                ("QA-3", "Needs Review", "Mismatch — geometry changed, not the attribute in question"),
    ("IT-2", "Geometry and Attribute Changed"):  ("QA-1", "Maybe Changed", "Attribute component matches"),
    ("IT-2", "Added"):                           ("QA-3", "Needs Review", "Data-lifecycle inconsistency"),
    ("IT-2", "Deleted"):                         ("QA-5", "Feature Deleted", "Flagged feature vanished"),

    # IT-3 Geometry & Attribute Issue
    ("IT-3", "Unchanged"):                       ("QA-2", "Not Changed", "Still open"),
    ("IT-3", "Geometry Changed"):                ("QA-1", "Maybe Changed", "Partial match (one of the two dimensions)"),
    ("IT-3", "Attribute Changed"):               ("QA-1", "Maybe Changed", "Partial match"),
    ("IT-3", "Geometry and Attribute Changed"):  ("QA-1", "Maybe Changed", "Full match"),
    ("IT-3", "Added"):                           ("QA-3", "Needs Review", "Data-lifecycle inconsistency"),
    ("IT-3", "Deleted"):                         ("QA-5", "Feature Deleted", "Flagged feature vanished"),

    # IT-4 Missing Feature
    ("IT-4", "Unchanged"):                       ("QA-3", "Needs Review", "Contradiction: reviewer said it was missing, but it's present in both unchanged"),
    ("IT-4", "Added"):                           ("QA-1", "Maybe Changed", "Confirms — feature now exists, issue likely addressed"),
    ("IT-4", "Geometry Changed"):                ("QA-3", "Needs Review", "Feature existed all along (only edited) — wasn't truly missing"),
    ("IT-4", "Attribute Changed"):               ("QA-3", "Needs Review", "Feature existed all along (only edited) — mismatch"),
    ("IT-4", "Geometry and Attribute Changed"):  ("QA-3", "Needs Review", "Feature existed all along — mismatch"),
    ("IT-4", "Deleted"):                         ("QA-3", "Needs Review", "Contradiction — reported missing, now also gone; needs investigation"),

    # IT-5 Extra Feature
    ("IT-5", "Deleted"):                         ("QA-1", "Maybe Changed", "Confirms — feature removed as expected"),
    ("IT-5", "Unchanged"):                       ("QA-3", "Needs Review", "Still present despite the flag — not addressed"),
    ("IT-5", "Geometry Changed"):                ("QA-3", "Needs Review", "Still present, only edited — not addressed as expected"),
    ("IT-5", "Attribute Changed"):               ("QA-3", "Needs Review", "Still present, only edited — not addressed as expected"),
    ("IT-5", "Geometry and Attribute Changed"):  ("QA-3", "Needs Review", "Still present, only edited — not addressed as expected"),
    ("IT-5", "Added"):                           ("QA-3", "Needs Review", "Contradiction — flagged as extra/duplicate but registered as fresh addition"),
}

LAST_CHECK_STATUS_MAP = {
    0: "Not Checked",
    1: "Changed",
    2: "Not Changed",
    3: "Feature Added",
    4: "Feature Deleted",
    5: "Feature Not Found",
}
LAST_CHECK_STATUS_CODE_MAP = {v.lower(): k for k, v in LAST_CHECK_STATUS_MAP.items()}


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _get_fields(fc):
    """
    Return list of (name, type, aliasName) for user-accessible, comparable fields.
    Excludes system/geometry/blob fields that cannot be meaningfully compared.
    """
    fields = []
    for f in arcpy.ListFields(fc):
        if f.name in _SKIP_FIELD_NAMES:
            continue
        if f.name.upper().startswith("SHAPE"):
            continue
        if f.type in _SKIP_FIELD_TYPES:
            continue
        fields.append((f.name, f.type, f.aliasName))
    return fields


def _schema_matches(fc1, fc2):
    """Return True if both FCs share the same set of comparable field names."""
    f1 = {f[0].upper() for f in _get_fields(fc1)}
    f2 = {f[0].upper() for f in _get_fields(fc2)}
    return f1 == f2


def _is_compatible_type(type1, type2):
    """Check if two ArcPy field types belong to the same category."""
    if not type1 or not type2:
        return True
    t1, t2 = str(type1).capitalize(), str(type2).capitalize()
    if t1 == t2:
        return True
    is_num1 = any(t1.startswith(p) for p in ("Short", "Long", "Float", "Double", "Single", "Integer", "Small", "Big"))
    is_num2 = any(t2.startswith(p) for p in ("Short", "Long", "Float", "Double", "Single", "Integer", "Small", "Big"))
    if is_num1 and is_num2:
        return True
    is_text1 = t1 in ("String", "Text")
    is_text2 = t2 in ("String", "Text")
    if is_text1 and is_text2:
        return True
    is_date1 = "Date" in t1 or "Time" in t1
    is_date2 = "Date" in t2 or "Time" in t2
    if is_date1 and is_date2:
        return True
    return False


def _normalize_issue_type(raw_val):
    """Normalize raw issue type into (IT-Code, Description)."""
    if raw_val is None:
        return IT_CODE_GEOM, "Geometry Issue"
    s = str(raw_val).strip().upper()
    if s in ("1", "IT-1", "IT1") or "GEOMETRY ISSUE" in s or (s.startswith("GEOM") and "ATTR" not in s):
        return IT_CODE_GEOM, "Geometry Issue"
    if s in ("2", "IT-2", "IT2") or "ATTRIBUTE ISSUE" in s or (s.startswith("ATTR") and "GEOM" not in s):
        return IT_CODE_ATTR, "Attribute Issue"
    if s in ("3", "IT-3", "IT3") or ("GEOM" in s and "ATTR" in s):
        return IT_CODE_GEOM_ATTR, "Geometry and Attribute Issue"
    if s in ("4", "IT-4", "IT4") or "MISSING" in s:
        return IT_CODE_MISSING, "Missing Feature"
    if s in ("5", "IT-5", "IT5") or "EXTRA" in s:
        return IT_CODE_EXTRA, "Extra Feature"
    return IT_CODE_GEOM, "Geometry Issue"


def _compare_values(v1, v2, ignore_case=False, null_empty_equal=False, ftype="", compare_as=""):
    """Return True if v1 and v2 are considered equal under the given rules."""
    if null_empty_equal:
        n1 = v1 is None or (isinstance(v1, str) and v1.strip() == "")
        n2 = v2 is None or (isinstance(v2, str) and v2.strip() == "")
        if n1 and n2:
            return True
    if v1 is None and v2 is None:
        return True
    if v1 is None or v2 is None:
        return False

    c_as = (compare_as or "").strip().lower()
    if c_as == "text":
        s1 = str(v1).strip()
        s2 = str(v2).strip()
        if ignore_case:
            return s1.lower() == s2.lower()
        return s1 == s2
    elif c_as == "numeric":
        try:
            return abs(float(v1) - float(v2)) < 1e-9
        except (TypeError, ValueError):
            return str(v1).strip() == str(v2).strip()
    elif c_as == "date":
        try:
            d1 = v1.strftime("%Y-%m-%d %H:%M:%S") if hasattr(v1, "strftime") else str(v1).strip()
            d2 = v2.strftime("%Y-%m-%d %H:%M:%S") if hasattr(v2, "strftime") else str(v2).strip()
            return d1 == d2
        except Exception:
            return str(v1).strip() == str(v2).strip()

    if ignore_case and isinstance(v1, str) and isinstance(v2, str):
        return v1.strip().lower() == v2.strip().lower()
    if ftype in ("Double", "Single", "Float"):
        try:
            return abs(float(v1) - float(v2)) < 1e-9
        except (TypeError, ValueError):
            pass
    return v1 == v2


def _geom_type(fc):
    return arcpy.Describe(fc).shapeType


def _spatial_ref(fc):
    return arcpy.Describe(fc).spatialReference


def _safe_str(v):
    return "<NULL>" if v is None else str(v)


def _round_val(v, digits=6):
    if v is None:
        return None
    try:
        return round(float(v), digits)
    except (TypeError, ValueError):
        return v


def _validate_output_workspace(out_ws):
    """
    Ensure output workspace is File/Enterprise Geodatabase per Section 8 constraint.
    Rejects shapefile folders, shapefiles, or unsupported directory workspaces.
    """
    if not out_ws:
        raise ValueError("Output workspace (out_ws) must be specified.")
    ws_clean = str(out_ws).rstrip("\\/").lower()
    if ws_clean.endswith(".shp"):
        raise ValueError(
            f"Invalid Output Workspace: '{out_ws}'. Output workspace must be a File Geodatabase (.gdb) "
            f"or Enterprise Geodatabase (.sde), never a shapefile. Shapefiles truncate field names to 10 characters "
            f"and corrupt change detection schemas."
        )
    if not arcpy.Exists(out_ws):
        raise ValueError(f"Output workspace does not exist: {out_ws}")

    desc = arcpy.Describe(out_ws)
    ws_type = getattr(desc, "workspaceType", "")
    if ws_type not in ("LocalDatabase", "RemoteDatabase") and not ws_clean.endswith((".gdb", ".sde")):
        raise ValueError(
            f"Invalid Output Workspace: '{out_ws}' (workspaceType='{ws_type}'). "
            f"Output workspace must be a File Geodatabase (.gdb) or Enterprise Geodatabase (.sde), "
            f"never a shapefile folder or standard directory. Shapefiles truncate field names to 10 characters "
            f"and corrupt change detection schemas."
        )


def _extract_points(geom):
    """Extract list of (X, Y) coordinates for all vertices in geometry."""
    pts = []
    if geom is None:
        return pts
    try:
        for part in geom:
            for p in part:
                if p is not None:
                    pts.append((p.X, p.Y))
    except Exception:
        pass
    return pts


def _max_vertex_displacement(geom1, geom2):
    """
    Calculate maximum vertex displacement between two geometries.
    If point counts are equal, checks point-to-point distance in sequence.
    If point counts differ, checks bidirectional vertex-to-geometry distance.
    """
    try:
        pts1 = _extract_points(geom1)
        pts2 = _extract_points(geom2)
        if len(pts1) == len(pts2) and len(pts1) > 0:
            return max(math.hypot(p1[0] - p2[0], p1[1] - p2[1]) for p1, p2 in zip(pts1, pts2))

        sr = geom1.spatialReference
        max_d = 0.0
        for pt in pts1:
            pt_geom = arcpy.PointGeometry(arcpy.Point(pt[0], pt[1]), sr)
            d = geom2.distanceTo(pt_geom)
            if d > max_d:
                max_d = d
        for pt in pts2:
            pt_geom = arcpy.PointGeometry(arcpy.Point(pt[0], pt[1]), sr)
            d = geom1.distanceTo(pt_geom)
            if d > max_d:
                max_d = d
        return max_d
    except Exception:
        pass
    return 0.0


# ---------------------------------------------------------------------------
# Output FC creation helper
# ---------------------------------------------------------------------------

def _create_output_fc(out_ws, name, geom_type, sr, str_fields, dbl_fields, lng_fields=None):
    """
    Create (or overwrite) an output Feature Class with standard fields.

    str_fields : list of (field_name, field_length) -> TEXT
    dbl_fields : list of field_name strings          -> DOUBLE
    lng_fields : list of field_name strings          -> LONG
    """
    fc = os.path.join(out_ws, name)
    if arcpy.Exists(fc):
        try:
            arcpy.management.Delete(fc)
        except Exception:
            pass
    arcpy.management.CreateFeatureclass(
        out_ws, name, geom_type, spatial_reference=sr
    )
    for fname, flen in str_fields:
        arcpy.management.AddField(fc, fname, "TEXT", field_length=flen)
    for fname in dbl_fields:
        arcpy.management.AddField(fc, fname, "DOUBLE")
    if lng_fields:
        for fname in lng_fields:
            arcpy.management.AddField(fc, fname, "LONG")
    return fc


# ---------------------------------------------------------------------------
# QC Domain & Feature Class Creation Helpers
# ---------------------------------------------------------------------------

def _ensure_qc_domains(workspace):
    """
    Create standard QC Coded Value Domains if the workspace is a File Geodatabase or Enterprise GDB.
    Gracefully skips domain registration if workspace is a shapefile directory.
    """
    try:
        desc = arcpy.Describe(workspace)
        ws_type = getattr(desc, "workspaceType", "")
        if ws_type not in ("LocalDatabase", "RemoteDatabase"):
            return

        existing_domains = [d.name for d in arcpy.da.ListDomains(workspace)]

        # 1. QC_Issue_Type
        if "QC_Issue_Type" not in existing_domains:
            arcpy.management.CreateDomain(
                workspace, "QC_Issue_Type", "QC Issue Type", "SHORT", "CODED"
            )
            for code, desc_txt in QC_ISSUE_TYPE_MAP.items():
                arcpy.management.AddCodedValueToDomain(workspace, "QC_Issue_Type", code, desc_txt)

        # 2. QC_Status
        if "QC_Status" not in existing_domains:
            arcpy.management.CreateDomain(
                workspace, "QC_Status", "QC Review Status", "SHORT", "CODED"
            )
            for code, desc_txt in QC_STATUS_MAP.items():
                arcpy.management.AddCodedValueToDomain(workspace, "QC_Status", code, desc_txt)

        # 3. QC_Assessment (v5.0 TEXT domain with QA codes)
        if "QC_Assessment" not in existing_domains:
            try:
                arcpy.management.CreateDomain(
                    workspace, "QC_Assessment", "QC Change Correlation Assessment", "TEXT", "CODED"
                )
                for qa_code, qa_desc in QC_QA_CODE_TO_DESC.items():
                    arcpy.management.AddCodedValueToDomain(workspace, "QC_Assessment", qa_code, f"{qa_code}: {qa_desc}")
            except Exception:
                pass

        # 4. Last_Check_Status
        if "Last_Check_Status" not in existing_domains:
            arcpy.management.CreateDomain(
                workspace, "Last_Check_Status", "QC Last Check Status", "SHORT", "CODED"
            )
            for code, desc_txt in LAST_CHECK_STATUS_MAP.items():
                arcpy.management.AddCodedValueToDomain(workspace, "Last_Check_Status", code, desc_txt)

    except Exception:
        pass


def _create_qc_issues_fc(out_ws, name="QC_Issues", sr=None):
    """
    Create a standard QC_Issues Point Feature Class template.
    Assigns coded value domains if in a Geodatabase.
    """
    _ensure_qc_domains(out_ws)
    fc = os.path.join(out_ws, name)
    if arcpy.Exists(fc):
        try:
            arcpy.management.Delete(fc)
        except Exception:
            pass

    arcpy.management.CreateFeatureclass(out_ws, name, "Point", spatial_reference=sr)

    fields_to_add = [
        ("Issue_ID",               "LONG",  None, None, "QC Issue ID"),
        ("Feature_ID",             "TEXT",  255,  None, "Feature Unique ID"),
        ("Issue_Type",             "SHORT", None, "QC_Issue_Type", "Issue Type"),
        ("Reviewer_Note",          "TEXT",  2000, None, "Reviewer Note"),
        ("Created_Date",           "DATE",  None, None, "Creation Date"),
        ("Reviewer",               "TEXT",  100,  None, "Reviewer Name"),
        ("QC_Status",              "SHORT", None, "QC_Status", "QC Status"),
        ("Last_Check_Status",      "SHORT", None, "Last_Check_Status", "Last Check Status"),
        ("Change_Type",            "TEXT",  50,   None, "Detected Change Type"),
        ("Geometry_Change_Reason", "TEXT",  500,  None, "Geometry Change Reason"),
        ("QC_Assessment",          "TEXT",  20,   "QC_Assessment", "QC Assessment (QA-1..QA-5)"),
    ]

    is_gdb = False
    try:
        desc = arcpy.Describe(out_ws)
        is_gdb = getattr(desc, "workspaceType", "") in ("LocalDatabase", "RemoteDatabase")
    except Exception:
        pass

    for fname, ftype, flen, domain, alias in fields_to_add:
        try:
            kwargs = {
                "in_table": fc,
                "field_name": fname,
                "field_type": ftype,
                "field_alias": alias,
            }
            if flen:
                kwargs["field_length"] = flen
            if domain and is_gdb:
                kwargs["field_domain"] = domain
            arcpy.management.AddField(**kwargs)
        except Exception:
            try:
                arcpy.management.AddField(fc, fname, ftype, field_length=flen or 50, field_alias=alias)
            except Exception:
                pass

    return fc


def _create_qc_review_result_fc(out_ws, name="QC_Review_Result", sr=None):
    """
    Create the output QC Review Result Point Feature Class.
    """
    _ensure_qc_domains(out_ws)
    fc = os.path.join(out_ws, name)
    if arcpy.Exists(fc):
        try:
            arcpy.management.Delete(fc)
        except Exception:
            pass

    arcpy.management.CreateFeatureclass(out_ws, name, "Point", spatial_reference=sr)

    fields_to_add = [
        ("Issue_ID",                   "LONG",   None, None, "QC Issue ID"),
        ("Feature_ID",                 "TEXT",   255,  None, "Feature Unique ID"),
        ("Issue_Type",                 "SHORT",  None, "QC_Issue_Type", "Issue Type Code"),
        ("Issue_Type_Desc",            "TEXT",   100,  None, "Issue Type Description"),
        ("Reviewer_Note",              "TEXT",   2000, None, "Reviewer Note"),
        ("Reviewer",                   "TEXT",   100,  None, "Reviewer"),
        ("Created_Date",               "DATE",   None, None, "Created Date"),
        ("QC_Status",                  "SHORT",  None, "QC_Status", "Manual QC Status Code"),
        ("QC_Status_Desc",             "TEXT",   50,   None, "Manual QC Status"),
        ("Change_Type",                "TEXT",   50,   None, "Detected Change Type"),
        ("Geometry_Change_Reason",     "TEXT",   500,  None, "Geometry Change Reason"),
        ("QC_Assessment",              "TEXT",   20,   "QC_Assessment", "QC Assessment (QA-1..QA-5)"),
        ("QC_Assessment_Desc",         "TEXT",   50,   None, "QC Assessment"),
        ("Original_Feature_Found",     "SHORT",  None, None, "Original Feature Found (1/0)"),
        ("Modified_Feature_Found",     "SHORT",  None, None, "Modified Feature Found (1/0)"),
        ("Current_Feature_X",          "DOUBLE", None, None, "Current Feature Centroid X"),
        ("Current_Feature_Y",          "DOUBLE", None, None, "Current Feature Centroid Y"),
        ("Distance_To_Current_Feature","DOUBLE", None, None, "Distance to Current Feature"),
        ("Review_Run_ID",              "TEXT",   50,   None, "Review Run ID"),
        ("Review_Date",                "DATE",   None, None, "Review Execution Date"),
    ]

    is_gdb = False
    try:
        desc = arcpy.Describe(out_ws)
        is_gdb = getattr(desc, "workspaceType", "") in ("LocalDatabase", "RemoteDatabase")
    except Exception:
        pass

    for fname, ftype, flen, domain, alias in fields_to_add:
        try:
            kwargs = {
                "in_table": fc,
                "field_name": fname,
                "field_type": ftype,
                "field_alias": alias,
            }
            if flen:
                kwargs["field_length"] = flen
            if domain and is_gdb:
                kwargs["field_domain"] = domain
            arcpy.management.AddField(**kwargs)
        except Exception:
            try:
                arcpy.management.AddField(fc, fname, ftype, field_length=flen or 50, field_alias=alias)
            except Exception:
                pass

    return fc


# ---------------------------------------------------------------------------
# Core change detection engine
# ---------------------------------------------------------------------------

class ChangeEngine:
    """
    Advanced Change Detection Engine v4.1.0.
    
    Supports:
    - Three feature-matching modes (Attribute Field, OBJECTID, Spatial Location).
    - Multi-level Geometry Comparison Engine with dedicated metric precision,
      vertex count tolerance, spatial displacement tolerance, and shape analysis.
    - Explicit Geometry Change Reason tracking.
    - Optional QC Review & Issue Tracking correlation engine (Maybe Changed assessment).
    """

    CHANGE_UNCHANGED = "Unchanged"
    CHANGE_GEOM      = "Geometry Changed"
    CHANGE_ATTR      = "Attribute Changed"
    CHANGE_GEOM_ATTR = "Geometry and Attribute Changed"
    CHANGE_ADDED     = "Added"
    CHANGE_DELETED   = "Deleted"
    CHANGE_AMBIGUOUS = CHANGE_AMBIGUOUS

    def __init__(self, params, messages):
        self.p   = params
        self.msg = messages
        self.reprojections = []
        self.type_mismatches = []
        self.ambiguous_matches = []

    # ------------------------------------------------------------------
    def _progress(self, msg):
        self.msg.addMessage(msg)
        arcpy.SetProgressorLabel(msg)

    # ------------------------------------------------------------------
    # Feature loading & Rule 2 / Rule 5 validation
    # ------------------------------------------------------------------

    def _validate_unique_ids(self, fc, uid_field, is_original):
        """
        Validate Rule 2: Ensure uid_field contains strictly unique values.
        Aborts with a clear descriptive error listing duplicate IDs if found.
        """
        if not uid_field or uid_field == "OID@":
            return

        seen = set()
        duplicates = set()
        with arcpy.da.SearchCursor(fc, [uid_field]) as cur:
            for row in cur:
                val = row[0]
                if val is not None:
                    s_val = str(val).strip()
                    if s_val in seen:
                        duplicates.add(s_val)
                    else:
                        seen.add(s_val)

        if duplicates:
            sample = sorted(list(duplicates))[:10]
            suffix = f" ... and {len(duplicates) - 10} more" if len(duplicates) > 10 else ""
            fc_label = "Original" if is_original else "Modified"
            err_msg = (
                f"Rule 2 (Unique ID Validation) Violation: Duplicate '{uid_field}' values found in {fc_label} Feature Class. "
                f"Total {len(duplicates):,} duplicate ID(s) detected: {sample}{suffix}. "
                f"The Unique ID field must contain strictly unique values across all records. Execution aborted."
            )
            self.msg.addErrorMessage(err_msg)
            raise ValueError(err_msg)

    def _harmonize_crs(self, orig_fc, mod_fc):
        """
        Validate Rule 5: Verify CRS consistency.
        If CRS differs or either uses geographic degrees, determine a common projected CRS (linear units)
        for metric geometry comparison and log the reprojection.
        """
        sr_orig = _spatial_ref(orig_fc)
        sr_mod  = _spatial_ref(mod_fc)

        is_geo_orig = getattr(sr_orig, "type", "") == "Geographic"
        is_geo_mod  = getattr(sr_mod, "type", "") == "Geographic"

        target_sr = sr_orig
        reproject_msg = None

        if sr_orig.name != sr_mod.name or is_geo_orig or is_geo_mod:
            if not is_geo_orig:
                target_sr = sr_orig
                reproject_msg = (
                    f"Rule 5 (CRS Reprojection): Modified FC CRS ('{sr_mod.name}') differs from Original FC ('{sr_orig.name}'). "
                    f"Modified FC features will be projected on-the-fly into '{sr_orig.name}' for metric comparison."
                )
            elif not is_geo_mod:
                target_sr = sr_mod
                reproject_msg = (
                    f"Rule 5 (CRS Reprojection): Original FC uses Geographic CRS ('{sr_orig.name}'). "
                    f"Features will be projected on-the-fly into Modified FC's projected CRS ('{sr_mod.name}') for metric comparison."
                )
            else:
                try:
                    desc_orig = arcpy.Describe(orig_fc)
                    ext = desc_orig.extent
                    lon = (ext.XMin + ext.XMax) / 2.0 if ext else 0.0
                    lat = (ext.YMin + ext.YMax) / 2.0 if ext else 0.0
                    zone = int((lon + 180) / 6) + 1
                    epsg = (32600 if lat >= 0 else 32700) + zone
                    target_sr = arcpy.SpatialReference(epsg)
                    reproject_msg = (
                        f"Rule 5 (CRS Reprojection): Both FCs use Geographic CRS (degrees). "
                        f"Both FCs will be projected on-the-fly into local projected UTM Zone {zone} (EPSG:{epsg}) for linear metric calculations."
                    )
                except Exception:
                    target_sr = arcpy.SpatialReference(3857)
                    reproject_msg = (
                        "Rule 5 (CRS Reprojection): Both FCs use Geographic CRS (degrees). "
                        "Both FCs will be projected on-the-fly into WGS 1984 Web Mercator (EPSG:3857) for linear metric calculations."
                    )

        if reproject_msg:
            self.msg.addWarning(reproject_msg)
            self.reprojections.append(reproject_msg)
        else:
            self.msg.addMessage(f"CRS Check: Both FCs share compatible projected coordinate system: {sr_orig.name}")

        return target_sr

    def _load_fc(self, fc, uid_field, field_pairs, is_original, geom_type, comparison_sr=None):
        """
        Load features into a dict keyed by uid_field value.
        Pre-computes geometry summary metrics for fast O(1) comparisons.
        """
        attr_fields_this = [p[0] if is_original else p[1] for p in field_pairs]
        attr_keys        = [p[0] for p in field_pairs]      # canonical keys

        read_fields = [uid_field, "SHAPE@"] + attr_fields_this
        data        = {}
        duplicates  = set()

        cursor_kwargs = {"in_table": fc, "field_names": read_fields}
        if comparison_sr is not None:
            cursor_kwargs["spatial_reference"] = comparison_sr

        with arcpy.da.SearchCursor(**cursor_kwargs) as cur:
            for row in cur:
                uid_raw = row[0]
                uid     = str(uid_raw).strip() if uid_raw is not None else ""
                geom    = row[1]

                gm = {"geom": geom}
                if geom is not None and getattr(geom, "pointCount", 0) > 0:
                    if geom_type == "Polygon":
                        gm["area"] = geom.area if geom.area is not None else 0.0
                        gm["vertex_count"] = geom.pointCount
                        try:
                            tc = geom.trueCentroid
                            gm["cx"], gm["cy"] = tc.X, tc.Y
                        except Exception:
                            try:
                                c = geom.centroid
                                gm["cx"], gm["cy"] = c.X, c.Y
                            except Exception:
                                ext = geom.extent
                                gm["cx"] = (ext.XMin + ext.XMax) / 2.0 if ext else 0.0
                                gm["cy"] = (ext.YMin + ext.YMax) / 2.0 if ext else 0.0

                    elif geom_type == "Polyline":
                        gm["length"] = geom.length if geom.length is not None else 0.0
                        gm["vertex_count"] = geom.pointCount
                        try:
                            fp = geom.firstPoint
                            lp = geom.lastPoint
                            gm["start_x"] = fp.X if fp else None
                            gm["start_y"] = fp.Y if fp else None
                            gm["end_x"]   = lp.X if lp else None
                            gm["end_y"]   = lp.Y if lp else None
                        except Exception:
                            gm["start_x"] = gm["start_y"] = gm["end_x"] = gm["end_y"] = None

                        try:
                            tc = geom.trueCentroid
                            gm["cx"], gm["cy"] = tc.X, tc.Y
                        except Exception:
                            try:
                                c = geom.centroid
                                gm["cx"], gm["cy"] = c.X, c.Y
                            except Exception:
                                ext = geom.extent
                                gm["cx"] = (ext.XMin + ext.XMax) / 2.0 if ext else 0.0
                                gm["cy"] = (ext.YMin + ext.YMax) / 2.0 if ext else 0.0

                    elif geom_type == "Point":
                        pt = geom.firstPoint
                        if pt is not None:
                            gm["x"] = pt.X
                            gm["y"] = pt.Y
                            gm["z"] = pt.Z if geom.hasZ else None
                            gm["cx"] = pt.X
                            gm["cy"] = pt.Y
                        else:
                            gm["x"] = gm["y"] = gm["z"] = gm["cx"] = gm["cy"] = None

                    elif geom_type == "Multipoint":
                        gm["point_count"] = geom.pointCount
                        ext = geom.extent
                        if ext is not None:
                            gm["cx"] = (ext.XMin + ext.XMax) / 2.0
                            gm["cy"] = (ext.YMin + ext.YMax) / 2.0
                            gm["xmin"] = ext.XMin
                            gm["ymin"] = ext.YMin
                            gm["xmax"] = ext.XMax
                            gm["ymax"] = ext.YMax
                        else:
                            gm["cx"] = gm["cy"] = None
                            gm["xmin"] = gm["ymin"] = gm["xmax"] = gm["ymax"] = None
                else:
                    # Null or empty geometry
                    if geom_type == "Polygon":
                        gm["area"] = 0.0
                        gm["vertex_count"] = 0
                        gm["cx"] = gm["cy"] = None
                    elif geom_type == "Polyline":
                        gm["length"] = 0.0
                        gm["vertex_count"] = 0
                        gm["start_x"] = gm["start_y"] = gm["end_x"] = gm["end_y"] = None
                        gm["cx"] = gm["cy"] = None
                    elif geom_type == "Point":
                        gm["x"] = gm["y"] = gm["z"] = gm["cx"] = gm["cy"] = None
                    elif geom_type == "Multipoint":
                        gm["point_count"] = 0
                        gm["cx"] = gm["cy"] = None

                attrs = {attr_keys[i]: row[2 + i] for i in range(len(attr_keys))}

                if uid in data:
                    duplicates.add(uid)
                data[uid] = {"attrs": attrs, **gm}

        if duplicates:
            sample = sorted(list(duplicates))[:10]
            suffix = f" ... and {len(duplicates) - 10} more" if len(duplicates) > 10 else ""
            fc_label = "Original" if is_original else "Modified"
            err_msg = (
                f"Rule 2 (Unique ID Validation) Violation: Duplicate '{uid_field}' values found in {fc_label} Feature Class. "
                f"Total {len(duplicates):,} duplicate ID(s) detected: {sample}{suffix}. "
                f"The Unique ID field must contain strictly unique values across all records. Execution aborted."
            )
            self.msg.addErrorMessage(err_msg)
            raise ValueError(err_msg)

        return data

    # ------------------------------------------------------------------
    # Spatial mapping (Method B with Ambiguity Tie-Break & Greedy 1-to-1)
    # ------------------------------------------------------------------

    def _build_spatial_mapping_v5(self, orig_fc, mod_fc, geom_type, target_sr, ambiguity_tol=0.02):
        """
        Method B — Spatial Join with tie-break and ambiguity detection (Section 3).
        - Polygon: largest overlap area
        - Polyline: longest intersection length
        - Point: shortest distance
        - If two candidates are within ambiguity_tol, mark both as 'Ambiguous Match — Manual Review Required'.
        - 1-to-1 greedy matching by best score.
        """
        self._progress(f"  Building spatial feature mapping with tie-break & ambiguity check (tol={ambiguity_tol}) …")

        orig_copy = r"memory\cd_orig_sj"
        mod_copy  = r"memory\cd_mod_sj"
        sj_out    = r"memory\cd_sj_result"

        for p in (orig_copy, mod_copy, sj_out):
            if arcpy.Exists(p):
                try:
                    arcpy.management.Delete(p)
                except Exception:
                    pass

        arcpy.management.CreateFeatureclass(r"memory", "cd_orig_sj", geom_type, spatial_reference=target_sr)
        arcpy.management.AddField(orig_copy, "CD_ORIG_OID", "LONG")
        with arcpy.da.SearchCursor(orig_fc, ["OID@", "SHAPE@"], spatial_reference=target_sr) as scur:
            with arcpy.da.InsertCursor(orig_copy, ["CD_ORIG_OID", "SHAPE@"]) as icur:
                for oid, geom in scur:
                    icur.insertRow([oid, geom])

        arcpy.management.CreateFeatureclass(r"memory", "cd_mod_sj", geom_type, spatial_reference=target_sr)
        arcpy.management.AddField(mod_copy, "CD_MOD_OID", "LONG")
        with arcpy.da.SearchCursor(mod_fc, ["OID@", "SHAPE@"], spatial_reference=target_sr) as scur:
            with arcpy.da.InsertCursor(mod_copy, ["CD_MOD_OID", "SHAPE@"]) as icur:
                for oid, geom in scur:
                    icur.insertRow([oid, geom])

        match_opt = "INTERSECT" if geom_type != "Point" else "CLOSEST"
        arcpy.analysis.SpatialJoin(
            target_features   = orig_copy,
            join_features     = mod_copy,
            out_feature_class = sj_out,
            join_operation    = "JOIN_ONE_TO_MANY",
            join_type         = "KEEP_COMMON",
            match_option      = match_opt
        )

        orig_geoms = {oid: geom for oid, geom in arcpy.da.SearchCursor(orig_copy, ["CD_ORIG_OID", "SHAPE@"])}
        mod_geoms  = {oid: geom for oid, geom in arcpy.da.SearchCursor(mod_copy, ["CD_MOD_OID", "SHAPE@"])}

        candidates_by_orig = {}
        with arcpy.da.SearchCursor(sj_out, ["CD_ORIG_OID", "CD_MOD_OID"]) as cur:
            for orig_oid, mod_oid in cur:
                og = orig_geoms.get(orig_oid)
                mg = mod_geoms.get(mod_oid)
                if og is None or mg is None:
                    continue
                score = 0.0
                if geom_type == "Polygon":
                    try:
                        inter = og.intersect(mg, 4)
                        score = inter.area if inter else 0.0
                    except Exception:
                        score = 0.0
                elif geom_type == "Polyline":
                    try:
                        inter = og.intersect(mg, 2)
                        score = inter.length if inter else 0.0
                    except Exception:
                        score = 0.0
                elif geom_type == "Point":
                    try:
                        d = og.distanceTo(mg)
                        score = -d
                    except Exception:
                        score = -999999.0

                candidates_by_orig.setdefault(orig_oid, []).append((score, mod_oid))

        ambiguous_orig = set()
        ambiguous_mod  = set()
        scored_edges = []

        for orig_oid, c_list in candidates_by_orig.items():
            if not c_list:
                continue
            c_list.sort(key=lambda x: x[0], reverse=True)
            best_score, best_mod = c_list[0]

            is_ambiguous = False
            if len(c_list) > 1:
                second_score, second_mod = c_list[1]
                if geom_type in ("Polygon", "Polyline"):
                    if best_score > 0 and (best_score - second_score) / best_score <= ambiguity_tol:
                        is_ambiguous = True
                elif geom_type == "Point":
                    d1, d2 = abs(best_score), abs(second_score)
                    denom = max(d1, 1.0)
                    if abs(d2 - d1) / denom <= ambiguity_tol:
                        is_ambiguous = True

            if is_ambiguous:
                ambiguous_orig.add(str(orig_oid))
                for sc, m_oid in c_list[:2]:
                    ambiguous_mod.add(str(m_oid))
                self.ambiguous_matches.append(
                    f"Ambiguous Match: Original feature OID {orig_oid} ties between Modified OIDs {[m for _, m in c_list[:2]]} within ambiguity tolerance {ambiguity_tol}"
                )
            else:
                for sc, m_oid in c_list:
                    scored_edges.append((sc, orig_oid, m_oid))

        scored_edges.sort(key=lambda x: x[0], reverse=True)
        claimed_orig = set()
        claimed_mod  = set()
        mapping = {}

        for sc, orig_oid, mod_oid in scored_edges:
            s_orig = str(orig_oid)
            s_mod  = str(mod_oid)
            if s_orig in ambiguous_orig or s_mod in ambiguous_mod:
                continue
            if s_orig not in claimed_orig and s_mod not in claimed_mod:
                claimed_orig.add(s_orig)
                claimed_mod.add(s_mod)
                mapping[s_mod] = s_orig

        for p in (orig_copy, mod_copy, sj_out):
            if arcpy.Exists(p):
                try:
                    arcpy.management.Delete(p)
                except Exception:
                    pass

        matched = len(mapping)
        self.msg.addMessage(
            f"  Spatial mapping: {matched:,} 1-to-1 matches, {len(ambiguous_orig):,} ambiguous original features."
        )
        return mapping, ambiguous_orig, ambiguous_mod

    # ------------------------------------------------------------------
    # Data preparation — unified entry for all match modes
    # ------------------------------------------------------------------

    def _prepare_data(self, orig_fc, mod_fc, uid_field, field_pairs, geom_type, match_method, target_sr, ambiguity_tol=0.02):
        """Load feature data from both FCs into dicts with a consistent key space."""
        if match_method in (_MATCH_BY_ATTR, _MATCH_BY_ATTR_ALT):
            self._validate_unique_ids(orig_fc, uid_field, True)
            self._validate_unique_ids(mod_fc, uid_field, False)
            self._progress("(2/6) Loading original FC (by attribute ID) …")
            orig_data = self._load_fc(orig_fc, uid_field, field_pairs, True, geom_type, target_sr)
            self.msg.addMessage(f"  Original: {len(orig_data):,} features.")

            self._progress("(3/6) Loading modified FC (by attribute ID) …")
            mod_data = self._load_fc(mod_fc, uid_field, field_pairs, False, geom_type, target_sr)
            self.msg.addMessage(f"  Modified: {len(mod_data):,} features.")
            return orig_data, mod_data, {}, set(), set(), "attribute ID"

        elif match_method == _MATCH_BY_OID:
            self._progress("(2/6) Loading original FC (by OBJECTID) …")
            orig_data = self._load_fc(orig_fc, "OID@", field_pairs, True, geom_type, target_sr)
            self.msg.addMessage(f"  Original: {len(orig_data):,} features.")

            self._progress("(3/6) Loading modified FC (by OBJECTID) …")
            mod_data = self._load_fc(mod_fc, "OID@", field_pairs, False, geom_type, target_sr)
            self.msg.addMessage(f"  Modified: {len(mod_data):,} features.")
            return orig_data, mod_data, {}, set(), set(), "OBJECTID"

        elif match_method == _MATCH_BY_SPATIAL:
            self._progress("(2/6) Building spatial feature mapping …")
            spatial_map, amb_orig, amb_mod = self._build_spatial_mapping_v5(
                orig_fc, mod_fc, geom_type, target_sr, ambiguity_tol
            )

            self._progress("(3/6) Loading original FC (by OID, for spatial match) …")
            orig_data = self._load_fc(orig_fc, "OID@", field_pairs, True, geom_type, target_sr)
            self.msg.addMessage(f"  Original: {len(orig_data):,} features.")

            self._progress("(3/6) Loading modified FC (by OID, for spatial match) …")
            mod_raw = self._load_fc(mod_fc, "OID@", field_pairs, False, geom_type, target_sr)
            self.msg.addMessage(f"  Modified: {len(mod_raw):,} features.")

            mod_data   = {}
            orphan_mod = {}
            for mod_oid_str, mrec in mod_raw.items():
                orig_oid = spatial_map.get(mod_oid_str)
                if orig_oid is not None:
                    mod_data[orig_oid] = mrec
                else:
                    orphan_mod[mod_oid_str] = mrec

            return orig_data, mod_data, orphan_mod, amb_orig, amb_mod, "spatial location"
        else:
            raise ValueError(f"Unknown match method: {match_method!r}")

    # ------------------------------------------------------------------
    # Advanced Geometry Comparison Engine
    # ------------------------------------------------------------------

    def _geom_changed(self, orec, mrec, geom_type, g_opts):
        """
        Multi-level Geometry Comparison Engine.
        Evaluates metrics, vertex count, spatial displacement, shape difference, and Z.

        Returns (changed: bool, diff_dict: dict).
        """
        area_decimals    = g_opts.get("area_decimals", 3)
        length_decimals  = g_opts.get("length_decimals", 3)
        vertex_count_tol = g_opts.get("vertex_count_tol", 0)
        spatial_tol      = g_opts.get("spatial_tol", 0.3)
        compare_spatial  = g_opts.get("compare_spatial", True)
        compare_vc       = g_opts.get("compare_vertex_count", True)
        compare_shape    = g_opts.get("compare_shape", True)
        compare_z        = g_opts.get("compare_z", False)
        z_tol            = g_opts.get("z_tol", 0.001)
        geom_tol         = g_opts.get("geom_tol", 0.0)

        og = orec.get("geom")
        mg = mrec.get("geom")

        reasons           = []
        area_changed      = False
        length_changed    = False
        vc_changed        = False
        spatially_changed = False
        shape_changed     = False
        z_changed         = False
        diff              = {}

        # --------------------------------------------------------------
        # 1. POLYGON
        # --------------------------------------------------------------
        if geom_type == "Polygon":
            oa    = orec.get("area", 0.0) or 0.0
            na    = mrec.get("area", 0.0) or 0.0
            a_dif = na - oa
            a_pct = (a_dif / oa * 100.0) if oa != 0.0 else (100.0 if na != 0.0 else 0.0)

            ovc    = orec.get("vertex_count", 0) or 0
            nvc    = mrec.get("vertex_count", 0) or 0
            vc_dif = nvc - ovc

            ocx, ocy = orec.get("cx"), orec.get("cy")
            ncx, ncy = mrec.get("cx"), mrec.get("cy")

            if ocx is not None and ncx is not None and ocy is not None and ncy is not None:
                c_dist = math.hypot(ncx - ocx, ncy - ocy)
            else:
                c_dist = 0.0

            # Level 1: Area (using decimal precision)
            if round(oa, area_decimals) != round(na, area_decimals):
                if geom_tol <= 0.0 or abs(a_dif) > geom_tol:
                    area_changed = True
                    reasons.append("Area Changed")

            # Level 1: Vertex Count
            if compare_vc and abs(vc_dif) > vertex_count_tol:
                vc_changed = True
                reasons.append("Vertex Count Changed")

            # Level 1: Spatial Position / Centroid
            if compare_spatial and c_dist > spatial_tol:
                spatially_changed = True
                reasons.append("Spatial Position Changed")

            # Level 2: Geometry Shape / Topological comparison
            if compare_shape and og is not None and mg is not None:
                try:
                    if not og.equals(mg):
                        if spatial_tol == 0.0:
                            shape_changed = True
                        else:
                            v_disp = _max_vertex_displacement(og, mg)
                            if v_disp > spatial_tol:
                                shape_changed = True
                except Exception:
                    try:
                        if og.WKT != mg.WKT:
                            shape_changed = True
                    except Exception:
                        pass

            if shape_changed and "Shape Changed" not in reasons:
                reasons.append("Shape Changed")

            diff = {
                "Old_Area": oa, "New_Area": na, "Area_Diff": a_dif, "Area_Diff_Pct": a_pct,
                "Old_Vertex_Count": ovc, "New_Vertex_Count": nvc, "Vertex_Count_Diff": vc_dif,
                "Old_Centroid_X": ocx, "Old_Centroid_Y": ocy,
                "New_Centroid_X": ncx, "New_Centroid_Y": ncy,
                "Centroid_Distance": c_dist,
                "Area_Decimals": area_decimals,
                "Spatial_Tolerance": spatial_tol,
                "Area_Changed": "Yes" if area_changed else "No",
                "Length_Changed": "N/A",
                "Vertex_Count_Changed": "Yes" if vc_changed else "No",
                "Spatially_Changed": "Yes" if spatially_changed else "No",
                "Shape_Changed": "Yes" if shape_changed else "No",
            }

        # --------------------------------------------------------------
        # 2. POLYLINE
        # --------------------------------------------------------------
        elif geom_type == "Polyline":
            ol    = orec.get("length", 0.0) or 0.0
            nl    = mrec.get("length", 0.0) or 0.0
            l_dif = nl - ol
            l_pct = (l_dif / ol * 100.0) if ol != 0.0 else (100.0 if nl != 0.0 else 0.0)

            ovc    = orec.get("vertex_count", 0) or 0
            nvc    = mrec.get("vertex_count", 0) or 0
            vc_dif = nvc - ovc

            osx, osy = orec.get("start_x"), orec.get("start_y")
            oex, oey = orec.get("end_x"),   orec.get("end_y")
            nsx, nsy = mrec.get("start_x"), mrec.get("start_y")
            nex, ney = mrec.get("end_x"),   mrec.get("end_y")

            ocx, ocy = orec.get("cx"), orec.get("cy")
            ncx, ncy = mrec.get("cx"), mrec.get("cy")

            if ocx is not None and ncx is not None and ocy is not None and ncy is not None:
                c_dist = math.hypot(ncx - ocx, ncy - ocy)
            else:
                c_dist = 0.0

            s_dist = math.hypot(nsx - osx, nsy - osy) if (osx is not None and nsx is not None) else 0.0
            e_dist = math.hypot(nex - oex, ney - oey) if (oex is not None and nex is not None) else 0.0
            max_end_dist = max(s_dist, e_dist)
            displacement = max(c_dist, max_end_dist)

            # Level 1: Length
            if round(ol, length_decimals) != round(nl, length_decimals):
                if geom_tol <= 0.0 or abs(l_dif) > geom_tol:
                    length_changed = True
                    reasons.append("Length Changed")

            # Level 1: Vertex Count
            if compare_vc and abs(vc_dif) > vertex_count_tol:
                vc_changed = True
                reasons.append("Vertex Count Changed")

            # Level 1: Spatial Position
            if compare_spatial and (c_dist > spatial_tol or max_end_dist > spatial_tol):
                spatially_changed = True
                reasons.append("Spatial Position Changed")

            # Level 2: Geometry Shape
            if compare_shape and og is not None and mg is not None:
                try:
                    if not og.equals(mg):
                        if spatial_tol == 0.0:
                            shape_changed = True
                        else:
                            v_disp = _max_vertex_displacement(og, mg)
                            if v_disp > spatial_tol:
                                shape_changed = True
                except Exception:
                    try:
                        if og.WKT != mg.WKT:
                            shape_changed = True
                    except Exception:
                        pass

            if shape_changed and "Shape Changed" not in reasons:
                reasons.append("Shape Changed")

            diff = {
                "Old_Length": ol, "New_Length": nl, "Length_Diff": l_dif, "Length_Diff_Pct": l_pct,
                "Old_Vertex_Count": ovc, "New_Vertex_Count": nvc, "Vertex_Count_Diff": vc_dif,
                "Old_Start_X": osx, "Old_Start_Y": osy, "Old_End_X": oex, "Old_End_Y": oey,
                "New_Start_X": nsx, "New_Start_Y": nsy, "New_End_X": nex, "New_End_Y": ney,
                "Old_Centroid_X": ocx, "Old_Centroid_Y": ocy,
                "New_Centroid_X": ncx, "New_Centroid_Y": ncy,
                "Centroid_Distance": displacement,
                "Length_Decimals": length_decimals,
                "Spatial_Tolerance": spatial_tol,
                "Area_Changed": "N/A",
                "Length_Changed": "Yes" if length_changed else "No",
                "Vertex_Count_Changed": "Yes" if vc_changed else "No",
                "Spatially_Changed": "Yes" if spatially_changed else "No",
                "Shape_Changed": "Yes" if shape_changed else "No",
            }

        # --------------------------------------------------------------
        # 3. POINT
        # --------------------------------------------------------------
        elif geom_type == "Point":
            ox, oy, oz = orec.get("x"), orec.get("y"), orec.get("z")
            nx, ny, nz = mrec.get("x"), mrec.get("y"), mrec.get("z")

            x_dif = (nx - ox) if (ox is not None and nx is not None) else None
            y_dif = (ny - oy) if (oy is not None and ny is not None) else None
            z_dif = (nz - oz) if (oz is not None and nz is not None) else None

            if x_dif is not None and y_dif is not None:
                s_dist = math.hypot(x_dif, y_dif)
            else:
                s_dist = None

            if (ox is None) != (nx is None) or (oy is None) != (ny is None):
                spatially_changed = True
                reasons.append("Spatial Position Changed")
            elif s_dist is not None and compare_spatial and s_dist > spatial_tol:
                spatially_changed = True
                reasons.append("Spatial Position Changed")

            if compare_z:
                if (oz is None) != (nz is None):
                    z_changed = True
                    reasons.append("Z Coordinate Changed")
                elif z_dif is not None and abs(z_dif) > z_tol:
                    z_changed = True
                    reasons.append("Z Coordinate Changed")

            diff = {
                "Old_X": ox, "Old_Y": oy, "Old_Z": oz,
                "New_X": nx, "New_Y": ny, "New_Z": nz,
                "X_Diff": x_dif, "Y_Diff": y_dif, "Z_Diff": z_dif,
                "Spatial_Distance": s_dist,
                "Spatial_Tolerance": spatial_tol,
                "Area_Changed": "N/A",
                "Length_Changed": "N/A",
                "Vertex_Count_Changed": "N/A",
                "Spatially_Changed": "Yes" if spatially_changed else "No",
                "Shape_Changed": "N/A",
            }

        # --------------------------------------------------------------
        # 4. MULTIPOINT
        # --------------------------------------------------------------
        elif geom_type == "Multipoint":
            opc    = orec.get("point_count", 0) or 0
            npc    = mrec.get("point_count", 0) or 0
            pc_dif = npc - opc

            ocx, ocy = orec.get("cx"), orec.get("cy")
            ncx, ncy = mrec.get("cx"), mrec.get("cy")

            if ocx is not None and ncx is not None and ocy is not None and ncy is not None:
                c_dist = math.hypot(ncx - ocx, ncy - ocy)
            else:
                c_dist = 0.0

            if compare_vc and abs(pc_dif) > vertex_count_tol:
                vc_changed = True
                reasons.append("Point Count Changed")

            if compare_spatial and c_dist > spatial_tol:
                spatially_changed = True
                reasons.append("Spatial Position Changed")

            if compare_shape and og is not None and mg is not None:
                try:
                    if not og.equals(mg):
                        if spatial_tol == 0.0:
                            shape_changed = True
                        else:
                            oxmin, oymin = orec.get("xmin", 0), orec.get("ymin", 0)
                            oxmax, oymax = orec.get("xmax", 0), orec.get("ymax", 0)
                            nxmin, nymin = mrec.get("xmin", 0), mrec.get("ymin", 0)
                            nxmax, nymax = mrec.get("xmax", 0), mrec.get("ymax", 0)
                            bb_dif = max(abs(nxmin - oxmin), abs(nymin - oymin),
                                         abs(nxmax - oxmax), abs(nymax - oymax))
                            if bb_dif > spatial_tol or _max_vertex_displacement(og, mg) > spatial_tol:
                                shape_changed = True
                except Exception:
                    if og.WKT != mg.WKT:
                        shape_changed = True

            if shape_changed and "Shape Changed" not in reasons:
                reasons.append("Shape Changed")

            diff = {
                "Old_Point_Count": opc, "New_Point_Count": npc, "Point_Count_Diff": pc_dif,
                "Old_Centroid_X": ocx, "Old_Centroid_Y": ocy,
                "New_Centroid_X": ncx, "New_Centroid_Y": ncy,
                "Centroid_Distance": c_dist,
                "Spatial_Tolerance": spatial_tol,
                "Area_Changed": "N/A",
                "Length_Changed": "N/A",
                "Vertex_Count_Changed": "Yes" if vc_changed else "No",
                "Spatially_Changed": "Yes" if spatially_changed else "No",
                "Shape_Changed": "Yes" if shape_changed else "No",
            }

        reason_str = "; ".join(reasons) if reasons else ""
        diff["Geometry_Change_Reason"] = reason_str
        changed = bool(reasons)
        return changed, diff

    # ------------------------------------------------------------------
    # Attribute comparison
    # ------------------------------------------------------------------

    def _attr_changed(self, orig_attrs, mod_attrs, field_pairs,
                      field_types, ignore_case, null_empty_eq):
        """Return (changed_fields list, old_vals dict, new_vals dict)."""
        changed_fields = []
        old_vals = {}
        new_vals = {}
        for item in field_pairs:
            orig_f = item[0]
            compare_as = item[2] if len(item) > 2 else ""
            ov    = orig_attrs.get(orig_f)
            nv    = mod_attrs.get(orig_f)          # same key in both
            ftype = field_types.get(orig_f, "")
            if not _compare_values(ov, nv, ignore_case, null_empty_eq, ftype, compare_as):
                changed_fields.append(orig_f)
                old_vals[orig_f] = _safe_str(ov)
                new_vals[orig_f] = _safe_str(nv)
        return changed_fields, old_vals, new_vals

    # ------------------------------------------------------------------
    # QC Review & Issue Tracking Module
    # ------------------------------------------------------------------

    def _load_qc_issues(self, qc_fc, comparison_sr=None):
        """
        Load historical QC issues from a Point Feature Class or Layer.
        Gracefully handles schema variations, supports on-the-fly reprojection,
        and preserves all reviewer notes.
        """
        if not qc_fc or not arcpy.Exists(qc_fc):
            return []

        all_fields = {f.name.upper(): f.name for f in arcpy.ListFields(qc_fc)}

        def _find_field(candidates, default=""):
            for c in candidates:
                if c.upper() in all_fields:
                    return all_fields[c.upper()]
            return default

        f_issue_id    = _find_field(["Issue_ID", "ISSUEID", "ID"], "OID@")
        f_feat_id     = _find_field(["Feature_ID", "FEATUREID", "FEATURE_ID", "FID_FEATURE", "PARCEL_ID", "UID", "ID_FIELD"])
        f_issue_type  = _find_field(["Issue_Type", "ISSUETYPE", "TYPE", "ISSUE_CATEGORY"])
        f_note        = _find_field(["Reviewer_Note", "REVIEWERNOTE", "NOTE", "NOTES", "COMMENT", "COMMENTS"])
        f_reviewer    = _find_field(["Reviewer", "REVIEWER_NAME", "USER", "CREATED_BY", "QC_REVIEWER"])
        f_date        = _find_field(["Created_Date", "CREATEDDATE", "DATE", "CREATION_DATE", "QC_DATE"])
        f_status      = _find_field(["QC_Status", "QCSTATUS", "STATUS"])

        if not f_feat_id:
            self.msg.addWarning(
                f"QC Issues dataset '{qc_fc}' does not have a recognizable 'Feature_ID' field. "
                f"Using 'OID@' as fallback Feature ID."
            )
            f_feat_id = "OID@"

        read_fields = ["SHAPE@", f_issue_id, f_feat_id]
        idx_map = {
            "geom": 0, "issue_id": 1, "feature_id": 2,
            "issue_type": None, "note": None, "reviewer": None, "date": None, "status": None
        }

        if f_issue_type:
            idx_map["issue_type"] = len(read_fields)
            read_fields.append(f_issue_type)
        if f_note:
            idx_map["note"] = len(read_fields)
            read_fields.append(f_note)
        if f_reviewer:
            idx_map["reviewer"] = len(read_fields)
            read_fields.append(f_reviewer)
        if f_date:
            idx_map["date"] = len(read_fields)
            read_fields.append(f_date)
        if f_status:
            idx_map["status"] = len(read_fields)
            read_fields.append(f_status)

        issues = []
        cursor_kwargs = {"in_table": qc_fc, "field_names": read_fields}
        if comparison_sr is not None:
            cursor_kwargs["spatial_reference"] = comparison_sr

        with arcpy.da.SearchCursor(**cursor_kwargs) as cur:
            for row in cur:
                geom     = row[0]
                iid      = row[1] if row[1] is not None else 0
                fid_raw  = row[2]
                fid      = str(fid_raw).strip() if fid_raw is not None else ""

                itype_raw = row[idx_map["issue_type"]] if idx_map["issue_type"] is not None else 1
                note_raw  = row[idx_map["note"]] if idx_map["note"] is not None else ""
                rev_raw   = row[idx_map["reviewer"]] if idx_map["reviewer"] is not None else ""
                dt_raw    = row[idx_map["date"]] if idx_map["date"] is not None else None
                stat_raw  = row[idx_map["status"]] if idx_map["status"] is not None else 1

                # Normalize Issue Type
                itype_code = 1
                itype_desc = "Geometry Issue"
                if isinstance(itype_raw, int):
                    itype_code = itype_raw
                    itype_desc = QC_ISSUE_TYPE_MAP.get(itype_code, "Other")
                elif isinstance(itype_raw, str):
                    clean_type = itype_raw.strip().lower()
                    if clean_type in QC_ISSUE_TYPE_CODE_MAP:
                        itype_code = QC_ISSUE_TYPE_CODE_MAP[clean_type]
                        itype_desc = QC_ISSUE_TYPE_MAP[itype_code]
                    else:
                        try:
                            itype_code = int(itype_raw)
                            itype_desc = QC_ISSUE_TYPE_MAP.get(itype_code, "Other")
                        except ValueError:
                            itype_code = 7
                            itype_desc = itype_raw

                # Normalize QC Status
                stat_code = 1
                stat_desc = "Open"
                if isinstance(stat_raw, int):
                    stat_code = stat_raw
                    stat_desc = QC_STATUS_MAP.get(stat_code, "Open")
                elif isinstance(stat_raw, str):
                    clean_stat = stat_raw.strip().lower()
                    if clean_stat in QC_STATUS_CODE_MAP:
                        stat_code = QC_STATUS_CODE_MAP[clean_stat]
                        stat_desc = QC_STATUS_MAP[stat_code]
                    else:
                        try:
                            stat_code = int(stat_raw)
                            stat_desc = QC_STATUS_MAP.get(stat_code, "Open")
                        except ValueError:
                            stat_code = 1
                            stat_desc = stat_raw

                issues.append({
                    "geom":            geom,
                    "issue_id":        iid,
                    "feature_id":      fid,
                    "issue_type_code": itype_code,
                    "issue_type_desc": itype_desc,
                    "reviewer_note":   str(note_raw or ""),
                    "reviewer":        str(rev_raw or ""),
                    "created_date":    dt_raw,
                    "qc_status_code":  stat_code,
                    "qc_status_desc":  stat_desc,
                })

        return issues

    def _evaluate_qc_issues(self, qc_issues, orig_data, mod_data, results, run_id=None):
        """
        Evaluate QC issues against change detection results.
        
        CRITICAL PHILOSOPHY:
        - The tool NEVER automatically classifies any issue as 'Resolved'.
        - The strongest automated indicator is 'Maybe Changed'.
        - Preserves all original reviewer notes and issue points.
        """
        run_id      = run_id or getattr(self, "run_id", None) or ("RUN_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
        review_date = datetime.datetime.now()

        change_results_by_uid = {str(r["uid"]).strip(): r for r in results}
        orig_data_by_uid      = {str(k).strip(): v for k, v in orig_data.items()}
        mod_data_by_uid       = {str(k).strip(): v for k, v in mod_data.items()}

        qc_records = []
        qc_stats = {
            "total":         len(qc_issues),
            "maybe_changed": 0,
            "not_changed":   0,
            "needs_review":  0,
            "not_found":     0,
            "deleted":       0,
        }

        for issue in qc_issues:
            fid = str(issue["feature_id"]).strip()
            qg = issue.get("geom")

            orig_found = bool(fid and fid in orig_data_by_uid)
            mod_found  = bool(fid and fid in mod_data_by_uid)

            # Spatial resolution fallback:
            # When Feature_ID is blank/empty/not specified (common in Spatial Join or map-click QC notes),
            # resolve the feature spatially via point-in-polygon containment or closest proximity.
            if (not fid or fid == "0") and qg is not None:
                matched_uid = None

                # 1. Point containment in modified FC (current/after state)
                for u_k, m_v in mod_data.items():
                    mg = m_v.get("geom")
                    if mg is not None:
                        try:
                            if mg.contains(qg) or mg.touches(qg) or mg.intersects(qg):
                                matched_uid = str(u_k).strip()
                                break
                        except Exception:
                            pass

                # 2. Point containment in original FC (baseline/before state)
                if matched_uid is None:
                    for u_k, o_v in orig_data.items():
                        og = o_v.get("geom")
                        if og is not None:
                            try:
                                if og.contains(qg) or og.touches(qg) or og.intersects(qg):
                                    matched_uid = str(u_k).strip()
                                    break
                            except Exception:
                                pass

                # 3. Nearest proximity fallback
                if matched_uid is None:
                    best_d = float("inf")
                    for u_k, m_v in mod_data.items():
                        mg = m_v.get("geom")
                        if mg is not None:
                            try:
                                d = qg.distanceTo(mg)
                                if d < best_d:
                                    best_d = d
                                    matched_uid = str(u_k).strip()
                            except Exception:
                                pass
                    for u_k, o_v in orig_data.items():
                        og = o_v.get("geom")
                        if og is not None:
                            try:
                                d = qg.distanceTo(og)
                                if d < best_d:
                                    best_d = d
                                    matched_uid = str(u_k).strip()
                            except Exception:
                                pass

                if matched_uid is not None:
                    fid = matched_uid
                    issue["feature_id"] = fid
                    orig_found = fid in orig_data_by_uid
                    mod_found  = fid in mod_data_by_uid
                    if hasattr(self, "msg") and self.msg:
                        self.msg.addMessage(
                            f"  QC Issue #{issue.get('issue_id', 0)}: Spatially resolved to Feature ID '{fid}'."
                        )

            orec = orig_data_by_uid.get(fid)
            mrec = mod_data_by_uid.get(fid)
            change_rec = change_results_by_uid.get(fid)

            # Spatial distance tracking
            cur_x, cur_y, dist_to_cur = None, None, None

            target_rec = mrec if mrec is not None else orec
            if target_rec is not None:
                cur_x = target_rec.get("cx") if target_rec.get("cx") is not None else target_rec.get("x")
                cur_y = target_rec.get("cy") if target_rec.get("cy") is not None else target_rec.get("y")
                tg_geom = target_rec.get("geom")
                if qg is not None and tg_geom is not None:
                    try:
                        dist_to_cur = qg.distanceTo(tg_geom)
                    except Exception:
                        pass

            # Core Assessment Decision Logic (v5.0 Rebuilt)
            # Override rule (applied first): If Feature_ID not in either Original or Modified
            if not orig_found and not mod_found:
                assessment_code = QA_CODE_NOT_FOUND  # "QA-4"
                assessment_desc = QC_ASSESSMENT_NOT_FOUND # "Feature Not Found"
                change_type_out = "Feature Not Found"
                geom_reason_out = ""
                qc_stats["not_found"] += 1
                itype_code, itype_desc = _normalize_issue_type(issue.get("issue_type_code"))

            # Ambiguous match bypass (§6 footnote):
            elif change_rec is not None and change_rec.get("change_type") == CHANGE_AMBIGUOUS:
                assessment_code = "Ambiguous Match"
                assessment_desc = CHANGE_AMBIGUOUS
                change_type_out = CHANGE_AMBIGUOUS
                geom_reason_out = change_rec.get("Geometry_Change_Reason", "")
                qc_stats["needs_review"] += 1
                itype_code, itype_desc = _normalize_issue_type(issue.get("issue_type_code"))

            else:
                itype_code, itype_desc = _normalize_issue_type(issue.get("issue_type_code"))

                if change_rec is None:
                    if orig_found and not mod_found:
                        chg_type = self.CHANGE_DELETED
                        geom_reason = "Deleted Feature"
                    elif not orig_found and mod_found:
                        chg_type = self.CHANGE_ADDED
                        geom_reason = "Added Feature"
                    else:
                        chg_type = self.CHANGE_UNCHANGED
                        geom_reason = ""
                else:
                    chg_type = change_rec["change_type"]
                    geom_reason = change_rec.get("Geometry_Change_Reason", "")

                change_type_out = chg_type
                geom_reason_out = geom_reason

                matrix_key = (itype_code, chg_type)
                qa_code, qa_desc, _rationale = QC_DECISION_MATRIX_V5.get(
                    matrix_key,
                    (QA_CODE_NEEDS_REVIEW, QC_ASSESSMENT_NEEDS_REVIEW, "Unclassified combination")
                )

                assessment_code = qa_code
                assessment_desc = qa_desc

                if qa_code == QA_CODE_MAYBE_CHANGED:
                    qc_stats["maybe_changed"] += 1
                elif qa_code == QA_CODE_NOT_CHANGED:
                    qc_stats["not_changed"] += 1
                elif qa_code == QA_CODE_NEEDS_REVIEW:
                    qc_stats["needs_review"] += 1
                elif qa_code == QA_CODE_NOT_FOUND:
                    qc_stats["not_found"] += 1
                elif qa_code == QA_CODE_DELETED:
                    qc_stats["deleted"] += 1

            qc_records.append({
                "geom":                        qg,
                "Issue_ID":                    issue.get("issue_id", 0),
                "Feature_ID":                  fid,
                "Issue_Type":                  issue.get("issue_type_code", 1),
                "Issue_Type_Desc":             itype_desc,
                "Reviewer_Note":               issue.get("reviewer_note", ""),
                "Reviewer":                    issue.get("reviewer", ""),
                "Created_Date":                issue.get("created_date"),
                "QC_Status":                   issue.get("qc_status_code", 1),
                "QC_Status_Desc":              issue.get("qc_status_desc", "Open"),
                "Change_Type":                 change_type_out,
                "Geometry_Change_Reason":      geom_reason_out,
                "QC_Assessment":               assessment_code,
                "QC_Assessment_Desc":          assessment_desc,
                "Original_Feature_Found":      1 if orig_found else 0,
                "Modified_Feature_Found":      1 if mod_found else 0,
                "Current_Feature_X":           cur_x,
                "Current_Feature_Y":           cur_y,
                "Distance_To_Current_Feature": dist_to_cur,
                "Review_Run_ID":               run_id,
                "Review_Date":                 review_date,
            })

        qc_stats["qa_1"] = qc_stats["maybe_changed"]
        qc_stats["qa_2"] = qc_stats["not_changed"]
        qc_stats["qa_3"] = qc_stats["needs_review"]
        qc_stats["qa_4"] = qc_stats["not_found"]
        qc_stats["qa_5"] = qc_stats["deleted"]

        return qc_records, qc_stats

    def _write_qc_review_result_fc(self, out_ws, out_name, sr, qc_records):
        """Write the evaluated QC Review records to a Point Feature Class."""
        fc = _create_qc_review_result_fc(out_ws, out_name, sr)
        insert_fields = [
            "SHAPE@", "Issue_ID", "Feature_ID", "Issue_Type", "Issue_Type_Desc",
            "Reviewer_Note", "Reviewer", "Created_Date", "QC_Status", "QC_Status_Desc",
            "Change_Type", "Geometry_Change_Reason", "QC_Assessment", "QC_Assessment_Desc",
            "Original_Feature_Found", "Modified_Feature_Found",
            "Current_Feature_X", "Current_Feature_Y", "Distance_To_Current_Feature",
            "Review_Run_ID", "Review_Date"
        ]

        with arcpy.da.InsertCursor(fc, insert_fields) as cur:
            for r in qc_records:
                cur.insertRow([
                    r["geom"],
                    r["Issue_ID"],
                    str(r["Feature_ID"]),
                    r["Issue_Type"],
                    r["Issue_Type_Desc"],
                    r["Reviewer_Note"],
                    r["Reviewer"],
                    r["Created_Date"],
                    r["QC_Status"],
                    r["QC_Status_Desc"],
                    r["Change_Type"],
                    r["Geometry_Change_Reason"],
                    r["QC_Assessment"],
                    r["QC_Assessment_Desc"],
                    r["Original_Feature_Found"],
                    r["Modified_Feature_Found"],
                    r["Current_Feature_X"],
                    r["Current_Feature_Y"],
                    r["Distance_To_Current_Feature"],
                    r["Review_Run_ID"],
                    r["Review_Date"],
                ])
        return fc

    # ------------------------------------------------------------------
    # Audit Run Log (Section 11)
    # ------------------------------------------------------------------

    def _write_run_log(self, log_path, elapsed_seconds, counters, qc_stats=None):
        """
        Write execution audit run log capturing execution details per Section 11.
        Captures: parameters used, row counts, Rule 5 reprojections, mismatches, ambiguous matches, elapsed time.
        """
        try:
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            mins, secs = divmod(int(elapsed_seconds), 60)
            elapsed_fmt = f"{mins}m {secs}s ({elapsed_seconds:.2f} seconds)"

            lines = [
                "=" * 80,
                "GEO CHANGE DETECTION & QC REVIEW TOOL (v5.0 — Refined)",
                f"EXECUTION AUDIT RUN LOG — {self.run_id}",
                "=" * 80,
                f"Execution Timestamp : {now_str}",
                f"Review Run ID       : {self.run_id}",
                f"Elapsed Time        : {elapsed_fmt}",
                "",
                "-" * 80,
                "1. RUN CONFIGURATION & PARAMETERS",
                "-" * 80,
                f"Original FC         : {self.p.get('orig_fc')}",
                f"Modified FC         : {self.p.get('mod_fc')}",
                f"Unique ID Field     : {self.p.get('uid_field') or 'N/A'}",
                f"Match Method        : {self.p.get('match_method')}",
                f"Output Workspace    : {self.p.get('out_ws')}",
                f"Output FC Name      : {self.p.get('out_name')}",
                f"Compare Geometry    : {self.p.get('compare_geom')}",
                f"Spatial Tolerance   : {self.p.get('spatial_tol')}",
                f"Ambiguity Tolerance : {self.p.get('ambiguity_tolerance', 0.02)}",
                f"Compare Attributes  : {self.p.get('compare_attrs')}",
                f"Ignore Case         : {self.p.get('ignore_case')}",
                f"Null == Empty String: {self.p.get('null_empty_eq')}",
                f"QC Review Enabled   : {self.p.get('enable_qc_review')}",
                "",
                "-" * 80,
                "2. RULE 5 COORDINATE SYSTEM & REPROJECTION AUDIT",
                "-" * 80,
            ]

            if self.reprojections:
                for r_msg in self.reprojections:
                    lines.append(f"  • {r_msg}")
            else:
                lines.append("  • CRS Verified Compatible: Both Feature Classes share compatible spatial reference.")

            lines.extend([
                "",
                "-" * 80,
                "3. FEATURE INVENTORY & PROCESSED ROW COUNTS",
                "-" * 80,
                f"Total Original Features : {counters.get('total_orig', 0):,}",
                f"Total Modified Features : {counters.get('total_mod', 0):,}",
                f"Unchanged Features      : {counters.get('unchanged', 0):,}",
                f"Geometry Only Changed   : {counters.get('geom_only', 0):,}",
                f"Attribute Only Changed  : {counters.get('attr_only', 0):,}",
                f"Geometry + Attr Changed : {counters.get('geom_attr', 0):,}",
                f"Added Features          : {counters.get('added', 0):,}",
                f"Deleted Features        : {counters.get('deleted', 0):,}",
                f"Ambiguous Matches       : {counters.get('ambiguous', 0):,}",
                "",
                "-" * 80,
                "4. DETAILED GEOMETRY CHANGE REASONS",
                "-" * 80,
                f"  • Area Changed         : {counters.get('reason_area', 0):,}",
                f"  • Length Changed       : {counters.get('reason_length', 0):,}",
                f"  • Vertex Count Changed : {counters.get('reason_vertex', 0):,}",
                f"  • Spatial Position     : {counters.get('reason_spatial', 0):,}",
                f"  • Shape Changed        : {counters.get('reason_shape', 0):,}",
                f"  • Z Coordinate Changed : {counters.get('reason_z', 0):,}",
            ])

            if self.type_mismatches:
                lines.extend([
                    "",
                    "-" * 80,
                    "5. ATTRIBUTE TYPE MISMATCH AUDIT",
                    "-" * 80,
                ])
                for tm in self.type_mismatches:
                    lines.append(f"  • [Field_Type_Mismatch] {tm}")

            if counters.get("ambiguous", 0) > 0:
                lines.extend([
                    "",
                    "-" * 80,
                    "6. AMBIGUOUS SPATIAL MATCHES AUDIT",
                    "-" * 80,
                    f"  Total Ambiguous Matches: {counters.get('ambiguous', 0):,} feature(s).",
                    "  These features have multiple candidate matches within the ambiguity tolerance",
                    "  and have been flagged for manual review rather than auto-assigned."
                ])

            if qc_stats:
                lines.extend([
                    "",
                    "-" * 80,
                    "7. QC REVIEW & ISSUE TRACKING AUDIT",
                    "-" * 80,
                    f"Total QC Issues Evaluated : {qc_stats.get('total', 0):,}",
                    f"  • QA-1 Maybe Changed    : {qc_stats.get('maybe_changed', 0):,}",
                    f"  • QA-2 Not Changed      : {qc_stats.get('not_changed', 0):,}",
                    f"  • QA-3 Needs Review     : {qc_stats.get('needs_review', 0):,}",
                    f"  • QA-4 Feature Not Found: {qc_stats.get('not_found', 0):,}",
                    f"  • QA-5 Feature Deleted  : {qc_stats.get('deleted', 0):,}",
                ])

            lines.extend([
                "",
                "=" * 80,
                "END OF EXECUTION AUDIT LOG",
                "=" * 80,
                ""
            ])

            with open(log_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            self.msg.addMessage(f"  Run Log: {log_path}")
        except Exception as ex:
            self.msg.addWarning(f"Could not write audit run log: {ex}")

    # ------------------------------------------------------------------
    # Main run
    # ------------------------------------------------------------------

    def run(self):
        """Orchestrate the full change detection and QC workflow (v5.0 Refined)."""
        p = self.p

        orig_fc        = p["orig_fc"]
        mod_fc         = p["mod_fc"]
        uid_field      = p["uid_field"]
        out_ws         = p["out_ws"]
        out_name       = p["out_name"]
        compare_attrs  = p["compare_attrs"]
        compare_geom   = p["compare_geom"]
        geom_tol       = p["geom_tol"]
        ignore_case    = p["ignore_case"]
        null_empty_eq  = p["null_empty_eq"]
        field_pairs    = p["field_pairs"]
        export_added   = p["export_added"]
        export_deleted = p["export_deleted"]
        save_settings  = p["save_settings"]
        settings_file  = p["settings_file"]
        filter_types   = p["filter_types"]
        gen_html       = p["gen_html"]
        match_method   = p["match_method"]
        ambiguity_tol  = p.get("ambiguity_tolerance", 0.02)
        validate_only  = p.get("validate_only", False)

        start_time     = datetime.datetime.now()
        self.run_id    = "RUN_" + start_time.strftime("%Y%m%d_%H%M%S")

        # QC Parameters
        enable_qc_review   = p.get("enable_qc_review", False)
        create_qc_issues   = p.get("create_qc_issues", False)
        existing_qc_issues = p.get("existing_qc_issues", None)
        qc_output_name     = p.get("qc_output_name", "QC_Review_Result")

        # Geometry options bundle
        g_opts = {
            "area_decimals":        p.get("area_decimals", 3),
            "length_decimals":      p.get("length_decimals", 3),
            "vertex_count_tol":     p.get("vertex_count_tol", 0),
            "spatial_tol":          p.get("spatial_tol", 0.3),
            "compare_spatial":      p.get("compare_spatial", True),
            "compare_vertex_count": p.get("compare_vertex_count", True),
            "compare_shape":        p.get("compare_shape", True),
            "compare_z":            p.get("compare_z", False),
            "z_tol":                p.get("z_tol", 0.001),
            "geom_tol":             geom_tol,
        }

        # Validate Output Workspace format constraint (§8)
        _validate_output_workspace(out_ws)

        # Validate geometry types
        self._progress("Validating inputs & geometry types …")
        orig_geom_type = _geom_type(orig_fc)
        mod_geom_type  = _geom_type(mod_fc)
        if orig_geom_type != mod_geom_type:
            raise ValueError(
                f"Geometry type mismatch: "
                f"original='{orig_geom_type}', modified='{mod_geom_type}'. "
                f"Both Feature Classes must have the same geometry type."
            )
        geom_type = orig_geom_type

        # Rule 5: Harmonize CRS
        target_sr = self._harmonize_crs(orig_fc, mod_fc)

        # Field types
        field_types = {f.name: f.type for f in arcpy.ListFields(orig_fc)}

        # Check field type compatibility for field_pairs per §5
        if compare_attrs and field_pairs:
            orig_ft_map = {f.name: f.type for f in arcpy.ListFields(orig_fc)}
            mod_ft_map  = {f.name: f.type for f in arcpy.ListFields(mod_fc)}
            for item in field_pairs:
                of = item[0]
                mf = item[1]
                cas = item[2] if len(item) > 2 else None
                t1 = orig_ft_map.get(of, "")
                t2 = mod_ft_map.get(mf, "")
                if not cas and not _is_compatible_type(t1, t2):
                    mis_msg = f"Type mismatch between '{of}' ({t1}) and '{mf}' ({t2})."
                    self.type_mismatches.append(mis_msg)
                    self.msg.addWarning(f"[Field_Type_Mismatch] {mis_msg}")

        # Dry-run / Validation mode branch (§10)
        if validate_only:
            self._progress("[VALIDATION MODE] Running pre-flight schema and parameter validation …")
            if match_method in (_MATCH_BY_ATTR, _MATCH_BY_ATTR_ALT):
                self._validate_unique_ids(orig_fc, uid_field, True)
                self._validate_unique_ids(mod_fc, uid_field, False)
                self.msg.addMessage(f"  [PASS] Rule 2 Unique ID validation verified for '{uid_field}'.")

            if enable_qc_review and existing_qc_issues and arcpy.Exists(existing_qc_issues):
                q_type = _geom_type(existing_qc_issues)
                if q_type != "Point":
                    raise ValueError(f"Existing QC issues must be a Point Feature Class (found '{q_type}').")
                self.msg.addMessage(f"  [PASS] QC review input dataset validated: {existing_qc_issues}")

            self.msg.addMessage("=" * 65)
            self.msg.addMessage("[VALIDATION SUCCESS] All schema and pre-flight checks passed!")
            self.msg.addMessage(f"  Target Comparison CRS: {target_sr.name}")
            self.msg.addMessage(f"  Workspace: {out_ws} (Valid Geodatabase)")
            self.msg.addMessage(f"  Compared Field Pairs: {len(field_pairs)}")
            if self.type_mismatches:
                self.msg.addWarning(f"  Field Type Warnings: {len(self.type_mismatches)} mismatch(es) detected.")
            self.msg.addMessage("Dry-run validation complete. No output feature classes or reports were written.")
            self.msg.addMessage("=" * 65)
            return None, None, None, None

        TOTAL_STEPS = 7 if enable_qc_review else 6
        arcpy.SetProgressor("step", "Initialising …", 0, TOTAL_STEPS, 1)

        # Optionally save settings
        if save_settings and settings_file:
            try:
                settings = {
                    "schema_version": "5.0",
                    "orig_fc": orig_fc, "mod_fc": mod_fc,
                    "uid_field": uid_field, "match_method": match_method,
                    "ambiguity_tolerance": ambiguity_tol,
                    "compare_attrs": compare_attrs, "compare_geom": compare_geom,
                    "geom_tol": geom_tol, "ignore_case": ignore_case,
                    "null_empty_eq": null_empty_eq, "field_pairs": field_pairs,
                    "area_decimal_places": g_opts["area_decimals"],
                    "length_decimal_places": g_opts["length_decimals"],
                    "vertex_count_tolerance": g_opts["vertex_count_tol"],
                    "spatial_tolerance": g_opts["spatial_tol"],
                    "compare_spatial_position": g_opts["compare_spatial"],
                    "compare_vertex_count": g_opts["compare_vertex_count"],
                    "compare_geometry_shape": g_opts["compare_shape"],
                    "compare_z": g_opts["compare_z"],
                    "z_tolerance": g_opts["z_tol"],
                    "report_folder": p.get("report_folder", ""),
                    "qc_review": {
                        "enabled": enable_qc_review,
                        "create_qc_issues": create_qc_issues,
                        "existing_qc_issues": existing_qc_issues or "",
                        "qc_output": qc_output_name,
                    }
                }
                with open(settings_file, "w", encoding="utf-8") as jf:
                    json.dump(settings, jf, indent=2, default=str)
                self.msg.addMessage(f"Settings saved -> {settings_file}")
            except Exception as ex:
                self.msg.addWarning(f"Could not save settings: {ex}")

        self.msg.addMessage(f"Match method: {match_method}")
        arcpy.SetProgressorPosition(1)

        # ---- Steps 2–3: Load both FCs (mode-aware) ----
        orig_data, mod_data, orphan_mod, amb_orig, amb_mod, match_label = self._prepare_data(
            orig_fc, mod_fc, uid_field, field_pairs, geom_type, match_method, target_sr, ambiguity_tol
        )

        # ---- Set operations ----
        orig_ids = set(orig_data.keys())
        mod_ids  = set(mod_data.keys())

        attr_added_ids = mod_ids  - orig_ids
        deleted_ids    = (orig_ids - mod_ids) - amb_orig
        common_ids     = (orig_ids & mod_ids) - amb_orig

        # Exclude ambiguous modified features from orphan_mod
        amb_mod_orphans = {oid: rec for oid, rec in orphan_mod.items() if oid in amb_mod}
        for oid in amb_mod_orphans:
            del orphan_mod[oid]

        total_ambiguous = len(amb_orig) + len(amb_mod_orphans)
        total_added = len(attr_added_ids) + len(orphan_mod)

        self.msg.addMessage(
            f"  Common: {len(common_ids):,} | "
            f"Added: {total_added:,} | "
            f"Deleted: {len(deleted_ids):,} | "
            f"Ambiguous: {total_ambiguous:,}"
        )

        arcpy.SetProgressorPosition(2)

        # ---- Step 4: Compare common features ----
        self._progress(f"(4/6) Comparing {len(common_ids):,} common features …")

        results  = []
        counters = {
            "total_orig":         len(orig_ids),
            "total_mod":          len(mod_ids) + len(orphan_mod) + len(amb_mod_orphans),
            "unchanged":          0,
            "geom_only":          0,
            "attr_only":          0,
            "geom_attr":          0,
            "added":              total_added,
            "deleted":            len(deleted_ids),
            "ambiguous":          total_ambiguous,
            "total_area_diff":    0.0,
            "max_area_diff":      0.0,
            "max_len_diff":       0.0,
            "max_spatial_dist":   0.0,
            "total_attr_changes": 0,
            "reason_area":        0,
            "reason_length":      0,
            "reason_vertex":      0,
            "reason_spatial":     0,
            "reason_shape":       0,
            "reason_z":           0,
        }

        total_common = len(common_ids)
        report_every = max(1, total_common // 20)

        for idx, uid in enumerate(common_ids, 1):
            if idx % report_every == 0:
                pct = int(idx / total_common * 100)
                arcpy.SetProgressorLabel(
                    f"(4/6) Comparing … {pct}% ({idx:,}/{total_common:,})"
                )

            orec = orig_data[uid]
            mrec = mod_data[uid]

            geom_chg  = False
            geom_diff = {}
            if compare_geom:
                geom_chg, geom_diff = self._geom_changed(
                    orec, mrec, geom_type, g_opts
                )

            attr_chg     = False
            changed_flds = []
            old_vals     = {}
            new_vals     = {}
            if compare_attrs and field_pairs:
                changed_flds, old_vals, new_vals = self._attr_changed(
                    orec["attrs"], mrec["attrs"],
                    field_pairs, field_types, ignore_case, null_empty_eq
                )
                attr_chg = bool(changed_flds)

            if geom_chg and attr_chg:
                change_type = self.CHANGE_GEOM_ATTR
                counters["geom_attr"] += 1
            elif geom_chg:
                change_type = self.CHANGE_GEOM
                counters["geom_only"] += 1
            elif attr_chg:
                change_type = self.CHANGE_ATTR
                counters["attr_only"] += 1
            else:
                counters["unchanged"] += 1
                continue

            # Update geometry counters and reasons
            if geom_chg:
                reason_str = geom_diff.get("Geometry_Change_Reason", "")
                if "Area Changed" in reason_str:
                    counters["reason_area"] += 1
                if "Length Changed" in reason_str:
                    counters["reason_length"] += 1
                if "Vertex Count Changed" in reason_str or "Point Count Changed" in reason_str:
                    counters["reason_vertex"] += 1
                if "Spatial Position Changed" in reason_str:
                    counters["reason_spatial"] += 1
                if "Shape Changed" in reason_str:
                    counters["reason_shape"] += 1
                if "Z Coordinate Changed" in reason_str:
                    counters["reason_z"] += 1

                if "Area_Diff" in geom_diff:
                    ad = abs(geom_diff["Area_Diff"])
                    counters["total_area_diff"] += ad
                    counters["max_area_diff"]    = max(counters["max_area_diff"], ad)
                if "Length_Diff" in geom_diff:
                    counters["max_len_diff"] = max(counters["max_len_diff"], abs(geom_diff["Length_Diff"]))
                if "Centroid_Distance" in geom_diff and geom_diff["Centroid_Distance"] is not None:
                    counters["max_spatial_dist"] = max(counters["max_spatial_dist"], geom_diff["Centroid_Distance"])
                if "Spatial_Distance" in geom_diff and geom_diff["Spatial_Distance"] is not None:
                    counters["max_spatial_dist"] = max(counters["max_spatial_dist"], geom_diff["Spatial_Distance"])

            counters["total_attr_changes"] += len(changed_flds)

            results.append({
                "uid":               uid,
                "change_type":       change_type,
                "geom_chg":          "Yes" if geom_chg else "No",
                "attr_chg":          "Yes" if attr_chg else "No",
                "geom":              mrec["geom"],
                "changed_flds":      ", ".join(changed_flds),
                "changed_flds_list": changed_flds,
                "old_vals":          json.dumps(old_vals, ensure_ascii=False, default=str, separators=(',', ':')),
                "new_vals":          json.dumps(new_vals, ensure_ascii=False, default=str, separators=(',', ':')),
                "old_vals_dict":     old_vals,
                "new_vals_dict":     new_vals,
                **geom_diff
            })

        # ---- Ambiguous Features (Spatial Join Ties) ----
        for orig_oid in amb_orig:
            orec = orig_data[orig_oid]
            results.append({
                "uid":               str(orig_oid),
                "change_type":       self.CHANGE_AMBIGUOUS,
                "geom_chg":          "Ambiguous",
                "attr_chg":          "Ambiguous",
                "geom":              orec["geom"],
                "changed_flds":      "",
                "changed_flds_list": [],
                "old_vals":          "{}",
                "new_vals":          "{}",
                "old_vals_dict":     {},
                "new_vals_dict":     {},
                "Geometry_Change_Reason": "Spatial Join Candidate Ambiguity within tolerance",
                "Area_Changed":      "N/A",
                "Length_Changed":    "N/A",
                "Vertex_Count_Changed": "N/A",
                "Spatially_Changed": "Ambiguous",
                "Shape_Changed":     "Ambiguous",
            })

        for mod_oid, mrec in amb_mod_orphans.items():
            results.append({
                "uid":               f"AMB-{mod_oid}",
                "change_type":       self.CHANGE_AMBIGUOUS,
                "geom_chg":          "Ambiguous",
                "attr_chg":          "Ambiguous",
                "geom":              mrec["geom"],
                "changed_flds":      "",
                "changed_flds_list": [],
                "old_vals":          "{}",
                "new_vals":          "{}",
                "old_vals_dict":     {},
                "new_vals_dict":     {},
                "Geometry_Change_Reason": "Spatial Join Candidate Ambiguity within tolerance",
                "Area_Changed":      "N/A",
                "Length_Changed":    "N/A",
                "Vertex_Count_Changed": "N/A",
                "Spatially_Changed": "Ambiguous",
                "Shape_Changed":     "Ambiguous",
            })

        # ---- Added features (attribute/OID mode) ----
        for uid in attr_added_ids:
            mrec = mod_data[uid]
            self._append_added_result(results, uid, mrec, geom_type, counters, g_opts)

        # ---- Added features (spatial mode — orphan mod features) ----
        for mod_oid, mrec in orphan_mod.items():
            display_uid = f"NEW-{mod_oid}"
            self._append_added_result(results, display_uid, mrec, geom_type, counters, g_opts)

        # ---- Deleted features ----
        for uid in deleted_ids:
            orec = orig_data[uid]
            self._append_deleted_result(results, uid, orec, geom_type, counters, g_opts)

        # ---- Apply change type filter ----
        if filter_types:
            output_results = [r for r in results if r["change_type"] in filter_types]
            self.msg.addMessage(
                f"Change type filter ({', '.join(filter_types)}): "
                f"{len(output_results):,} / {len(results):,} records written."
            )
        else:
            output_results = results

        arcpy.SetProgressorPosition(3)

        # ---- Step 5: Write output FC ----
        self._progress("(5/6) Writing output Feature Class …")
        sr     = _spatial_ref(mod_fc)
        out_fc = self._write_output_fc(out_ws, out_name, geom_type, sr, output_results)
        self.msg.addMessage(f"  Output FC: {out_fc} ({len(output_results):,} features)")

        if export_added and total_added > 0:
            added_recs = [r for r in results if r["change_type"] == self.CHANGE_ADDED]
            self._write_output_fc(out_ws, out_name + "_Added", geom_type, sr, added_recs)
            self.msg.addMessage(f"  Added FC: {out_name}_Added ({len(added_recs):,})")

        if export_deleted and deleted_ids:
            del_recs = [r for r in results if r["change_type"] == self.CHANGE_DELETED]
            self._write_output_fc(out_ws, out_name + "_Deleted", geom_type, sr, del_recs)
            self.msg.addMessage(f"  Deleted FC: {out_name}_Deleted ({len(del_recs):,})")

        arcpy.SetProgressorPosition(4)

        # ---- Optional Step: QC Review & Issue Tracking Processing ----
        qc_review_fc       = None
        qc_issues_template = None
        qc_records         = None
        qc_stats           = None

        if enable_qc_review:
            self._progress("(QC) Processing QC Review & Issue Tracking …")

            # 1. Template creation
            if create_qc_issues:
                should_create = True
                if existing_qc_issues:
                    try:
                        exist_p = arcpy.Describe(existing_qc_issues).catalogPath.lower().replace("/", "\\")
                        out_p   = os.path.join(out_ws, "QC_Issues").lower().replace("/", "\\")
                        if exist_p == out_p:
                            should_create = False
                            self.msg.addWarning("Existing QC Issues points to target template; skipping recreation to preserve existing data.")
                    except Exception:
                        pass
                if should_create:
                    qc_issues_template = _create_qc_issues_fc(out_ws, "QC_Issues", sr)
                    self.msg.addMessage(f"  Created QC Issues template: {qc_issues_template}")

            # 2. Existing QC issues correlation
            if existing_qc_issues and arcpy.Exists(existing_qc_issues):
                qc_issues_list = self._load_qc_issues(existing_qc_issues, comparison_sr=target_sr)
                self.msg.addMessage(f"  Loaded {len(qc_issues_list):,} QC issue(s) from: {existing_qc_issues}")

                if qc_issues_list:
                    qc_records, qc_stats = self._evaluate_qc_issues(
                        qc_issues_list, orig_data, mod_data, results, run_id=self.run_id
                    )
                    qc_review_fc = self._write_qc_review_result_fc(
                        out_ws, qc_output_name, sr, qc_records
                    )
                    self.msg.addMessage(
                        f"  QC Review Result FC: {qc_review_fc} ({len(qc_records):,} evaluated issues)"
                    )
                    self.msg.addMessage(
                        f"  QC Assessment Breakdown: "
                        f"Maybe Changed={qc_stats['maybe_changed']:,}, "
                        f"Not Changed={qc_stats['not_changed']:,}, "
                        f"Needs Review={qc_stats['needs_review']:,}, "
                        f"Not Found={qc_stats['not_found']:,}, "
                        f"Deleted={qc_stats['deleted']:,}"
                    )
            elif not create_qc_issues:
                self.msg.addWarning(
                    "QC Review was enabled but no valid 'Existing QC Issues' dataset was provided, "
                    "and 'Create QC Issues Feature Class' was not checked."
                )

        arcpy.SetProgressorPosition(5)

        # ---- Step 6: Reports & Audit Run Log ----
        self._progress("(6/6) Generating reports & audit run log …")

        user_report_folder = p.get("report_folder")
        if user_report_folder and arcpy.Exists(user_report_folder):
            report_folder = user_report_folder
        elif out_ws.lower().endswith((".gdb", ".mdb", ".sde")):
            report_folder = os.path.dirname(out_ws)
        else:
            report_folder = out_ws

        excel_path = os.path.join(report_folder, out_name + "_ChangeReport.xlsx")
        self._write_excel(
            excel_path, results, counters, geom_type, match_method, g_opts,
            qc_records=qc_records, qc_stats=qc_stats
        )
        self.msg.addMessage(f"  Excel: {excel_path}")

        html_path = None
        if gen_html:
            html_path = os.path.join(report_folder, out_name + "_ChangeReport.html")
            self._write_html(
                html_path, results, counters, geom_type,
                orig_fc, mod_fc, match_method, g_opts,
                qc_records=qc_records, qc_stats=qc_stats
            )
            self.msg.addMessage(f"  HTML:  {html_path}")

        # Section 11: Write Audit Run Log
        end_time = datetime.datetime.now()
        elapsed_seconds = (end_time - start_time).total_seconds()
        log_path = os.path.join(report_folder, f"{out_name}_{self.run_id}_audit.log")
        self._write_run_log(log_path, elapsed_seconds, counters, qc_stats=qc_stats)

        arcpy.SetProgressorPosition(TOTAL_STEPS)
        self._print_summary(counters, geom_type, qc_stats=qc_stats)
        arcpy.ResetProgressor()

        self.qc_review_fc = qc_review_fc
        self.qc_issues_template = qc_issues_template

        return out_fc, excel_path, html_path, qc_review_fc

    # ------------------------------------------------------------------
    # Helper: build and append an "Added" result record
    # ------------------------------------------------------------------

    def _append_added_result(self, results, uid, mrec, geom_type, counters, g_opts):
        """Construct and append an 'Added' result dict."""
        gd = {
            "Geometry_Change_Reason": "Added Feature",
            "Area_Changed":           "N/A",
            "Length_Changed":         "N/A",
            "Vertex_Count_Changed":   "N/A",
            "Spatially_Changed":      "N/A",
            "Shape_Changed":          "N/A",
            "Spatial_Tolerance":      g_opts.get("spatial_tol", 0.03),
        }

        if geom_type == "Polygon":
            a = mrec.get("area", 0.0) or 0.0
            gd.update({
                "Old_Area": 0.0, "New_Area": a,
                "Area_Diff": a, "Area_Diff_Pct": 100.0,
                "Old_Vertex_Count": 0, "New_Vertex_Count": mrec.get("vertex_count", 0),
                "Vertex_Count_Diff": mrec.get("vertex_count", 0),
                "Old_Centroid_X": None, "Old_Centroid_Y": None,
                "New_Centroid_X": mrec.get("cx"), "New_Centroid_Y": mrec.get("cy"),
                "Centroid_Distance": None,
                "Area_Decimals": g_opts.get("area_decimals", 3),
            })
            counters["total_area_diff"] += a
            counters["max_area_diff"]    = max(counters["max_area_diff"], a)

        elif geom_type == "Polyline":
            l = mrec.get("length", 0.0) or 0.0
            gd.update({
                "Old_Length": 0.0, "New_Length": l,
                "Length_Diff": l, "Length_Diff_Pct": 100.0,
                "Old_Vertex_Count": 0, "New_Vertex_Count": mrec.get("vertex_count", 0),
                "Vertex_Count_Diff": mrec.get("vertex_count", 0),
                "Old_Start_X": None, "Old_Start_Y": None, "Old_End_X": None, "Old_End_Y": None,
                "New_Start_X": mrec.get("start_x"), "New_Start_Y": mrec.get("start_y"),
                "New_End_X": mrec.get("end_x"), "New_End_Y": mrec.get("end_y"),
                "Old_Centroid_X": None, "Old_Centroid_Y": None,
                "New_Centroid_X": mrec.get("cx"), "New_Centroid_Y": mrec.get("cy"),
                "Centroid_Distance": None,
                "Length_Decimals": g_opts.get("length_decimals", 3),
            })
            counters["max_len_diff"] = max(counters["max_len_diff"], l)

        elif geom_type == "Point":
            gd.update({
                "Old_X": None, "Old_Y": None, "Old_Z": None,
                "New_X": mrec.get("x"), "New_Y": mrec.get("y"), "New_Z": mrec.get("z"),
                "X_Diff": None, "Y_Diff": None, "Z_Diff": None,
                "Spatial_Distance": None,
            })

        elif geom_type == "Multipoint":
            gd.update({
                "Old_Point_Count": 0, "New_Point_Count": mrec.get("point_count", 0),
                "Point_Count_Diff": mrec.get("point_count", 0),
                "Old_Centroid_X": None, "Old_Centroid_Y": None,
                "New_Centroid_X": mrec.get("cx"), "New_Centroid_Y": mrec.get("cy"),
                "Centroid_Distance": None,
            })

        new_attrs_str = {k: _safe_str(v) for k, v in mrec["attrs"].items()}
        results.append({
            "uid":               uid,
            "change_type":       self.CHANGE_ADDED,
            "geom_chg":          "Yes",
            "attr_chg":          "N/A",
            "geom":              mrec["geom"],
            "changed_flds":      "",
            "changed_flds_list": [],
            "old_vals":          "{}",
            "new_vals":          json.dumps(new_attrs_str, ensure_ascii=False, default=str, separators=(',', ':')),
            "old_vals_dict":     {},
            "new_vals_dict":     new_attrs_str,
            **gd
        })

    # ------------------------------------------------------------------
    # Helper: build and append a "Deleted" result record
    # ------------------------------------------------------------------

    def _append_deleted_result(self, results, uid, orec, geom_type, counters, g_opts):
        """Construct and append a 'Deleted' result dict."""
        gd = {
            "Geometry_Change_Reason": "Deleted Feature",
            "Area_Changed":           "N/A",
            "Length_Changed":         "N/A",
            "Vertex_Count_Changed":   "N/A",
            "Spatially_Changed":      "N/A",
            "Shape_Changed":          "N/A",
            "Spatial_Tolerance":      g_opts.get("spatial_tol", 0.03),
        }

        if geom_type == "Polygon":
            a = orec.get("area", 0.0) or 0.0
            gd.update({
                "Old_Area": a, "New_Area": 0.0,
                "Area_Diff": -a, "Area_Diff_Pct": -100.0,
                "Old_Vertex_Count": orec.get("vertex_count", 0), "New_Vertex_Count": 0,
                "Vertex_Count_Diff": -orec.get("vertex_count", 0),
                "Old_Centroid_X": orec.get("cx"), "Old_Centroid_Y": orec.get("cy"),
                "New_Centroid_X": None, "New_Centroid_Y": None,
                "Centroid_Distance": None,
                "Area_Decimals": g_opts.get("area_decimals", 3),
            })
            counters["total_area_diff"] += a
            counters["max_area_diff"]    = max(counters["max_area_diff"], a)

        elif geom_type == "Polyline":
            l = orec.get("length", 0.0) or 0.0
            gd.update({
                "Old_Length": l, "New_Length": 0.0,
                "Length_Diff": -l, "Length_Diff_Pct": -100.0,
                "Old_Vertex_Count": orec.get("vertex_count", 0), "New_Vertex_Count": 0,
                "Vertex_Count_Diff": -orec.get("vertex_count", 0),
                "Old_Start_X": orec.get("start_x"), "Old_Start_Y": orec.get("start_y"),
                "Old_End_X": orec.get("end_x"),     "Old_End_Y": orec.get("end_y"),
                "New_Start_X": None, "New_Start_Y": None, "New_End_X": None, "New_End_Y": None,
                "Old_Centroid_X": orec.get("cx"), "Old_Centroid_Y": orec.get("cy"),
                "New_Centroid_X": None, "New_Centroid_Y": None,
                "Centroid_Distance": None,
                "Length_Decimals": g_opts.get("length_decimals", 3),
            })
            counters["max_len_diff"] = max(counters["max_len_diff"], l)

        elif geom_type == "Point":
            gd.update({
                "Old_X": orec.get("x"), "Old_Y": orec.get("y"), "Old_Z": orec.get("z"),
                "New_X": None, "New_Y": None, "New_Z": None,
                "X_Diff": None, "Y_Diff": None, "Z_Diff": None,
                "Spatial_Distance": None,
            })

        elif geom_type == "Multipoint":
            gd.update({
                "Old_Point_Count": orec.get("point_count", 0), "New_Point_Count": 0,
                "Point_Count_Diff": -orec.get("point_count", 0),
                "Old_Centroid_X": orec.get("cx"), "Old_Centroid_Y": orec.get("cy"),
                "New_Centroid_X": None, "New_Centroid_Y": None,
                "Centroid_Distance": None,
            })

        old_attrs_str = {k: _safe_str(v) for k, v in orec["attrs"].items()}
        results.append({
            "uid":               uid,
            "change_type":       self.CHANGE_DELETED,
            "geom_chg":          "Yes",
            "attr_chg":          "N/A",
            "geom":              orec["geom"],
            "changed_flds":      "",
            "changed_flds_list": [],
            "old_vals":          json.dumps(old_attrs_str, ensure_ascii=False, default=str, separators=(',', ':')),
            "new_vals":          "{}",
            "old_vals_dict":     old_attrs_str,
            "new_vals_dict":     {},
            **gd
        })

    # ------------------------------------------------------------------
    # Output FC schema definition
    # ------------------------------------------------------------------

    def _build_field_schema(self, geom_type):
        str_fields = [
            ("Unique_ID",              255),
            ("Change_Type",             50),
            ("Geometry_Changed",         5),
            ("Attributes_Changed",       5),
            ("Geometry_Change_Reason", 255),
            ("Area_Changed",             5),
            ("Length_Changed",           5),
            ("Vertex_Count_Changed",     5),
            ("Spatially_Changed",        5),
            ("Shape_Changed",            5),
            ("Changed_Fields",        2000),
            ("Old_Values",            4000),
            ("New_Values",            4000),
        ]

        if geom_type == "Polygon":
            dbl_fields = [
                "Old_Area", "New_Area", "Area_Diff", "Area_Diff_Pct",
                "Old_Centroid_X", "Old_Centroid_Y", "New_Centroid_X", "New_Centroid_Y",
                "Centroid_Distance", "Spatial_Tolerance"
            ]
            lng_fields = ["Old_Vertex_Count", "New_Vertex_Count", "Vertex_Count_Diff", "Area_Decimals"]

        elif geom_type == "Polyline":
            dbl_fields = [
                "Old_Length", "New_Length", "Length_Diff", "Length_Diff_Pct",
                "Old_Start_X", "Old_Start_Y", "Old_End_X", "Old_End_Y",
                "New_Start_X", "New_Start_Y", "New_End_X", "New_End_Y",
                "Old_Centroid_X", "Old_Centroid_Y", "New_Centroid_X", "New_Centroid_Y",
                "Centroid_Distance", "Spatial_Tolerance"
            ]
            lng_fields = ["Old_Vertex_Count", "New_Vertex_Count", "Vertex_Count_Diff", "Length_Decimals"]

        elif geom_type == "Point":
            dbl_fields = [
                "Old_X", "Old_Y", "Old_Z", "New_X", "New_Y", "New_Z",
                "X_Diff", "Y_Diff", "Z_Diff", "Spatial_Distance", "Spatial_Tolerance"
            ]
            lng_fields = []

        elif geom_type == "Multipoint":
            dbl_fields = [
                "Old_Centroid_X", "Old_Centroid_Y", "New_Centroid_X", "New_Centroid_Y",
                "Centroid_Distance", "Spatial_Tolerance"
            ]
            lng_fields = ["Old_Point_Count", "New_Point_Count", "Point_Count_Diff"]

        else:
            dbl_fields = []
            lng_fields = []

        insert_fields = (
            ["SHAPE@", "Unique_ID", "Change_Type",
             "Geometry_Changed", "Attributes_Changed",
             "Geometry_Change_Reason",
             "Area_Changed", "Length_Changed", "Vertex_Count_Changed",
             "Spatially_Changed", "Shape_Changed",
             "Changed_Fields", "Old_Values", "New_Values"]
            + dbl_fields
            + lng_fields
        )
        return str_fields, dbl_fields, lng_fields, insert_fields

    # ------------------------------------------------------------------
    # Write output FC
    # ------------------------------------------------------------------

    def _write_output_fc(self, out_ws, out_name, geom_type, sr, results):
        str_fields, dbl_fields, lng_fields, insert_fields = self._build_field_schema(geom_type)
        fc = _create_output_fc(out_ws, out_name, geom_type, sr, str_fields, dbl_fields, lng_fields)
        with arcpy.da.InsertCursor(fc, insert_fields) as icur:
            for rec in results:
                row = [
                    rec["geom"],
                    str(rec["uid"]),
                    rec["change_type"],
                    rec["geom_chg"],
                    rec["attr_chg"],
                    rec.get("Geometry_Change_Reason", ""),
                    rec.get("Area_Changed", "N/A"),
                    rec.get("Length_Changed", "N/A"),
                    rec.get("Vertex_Count_Changed", "N/A"),
                    rec.get("Spatially_Changed", "N/A"),
                    rec.get("Shape_Changed", "N/A"),
                    rec["changed_flds"],
                    rec["old_vals"],
                    rec["new_vals"],
                ]
                for fname in dbl_fields:
                    row.append(rec.get(fname))
                for fname in lng_fields:
                    row.append(rec.get(fname))
                icur.insertRow(row)
        return fc

    # ------------------------------------------------------------------
    # Excel report
    # ------------------------------------------------------------------

    def _write_excel(self, path, results, cnt, geom_type, match_method="", g_opts=None,
                     qc_records=None, qc_stats=None):
        try:
            import openpyxl
            from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
            from openpyxl.utils import get_column_letter
        except ImportError:
            self.msg.addWarning(
                "openpyxl not found — Excel export skipped. "
                "Install: pip install openpyxl"
            )
            return

        g_opts = g_opts or {}
        wb = openpyxl.Workbook()

        HDR_FILL = PatternFill("solid", fgColor="1F3864")
        HDR_FONT = Font(bold=True, color="FFFFFF", size=11)
        SUB_FILL = PatternFill("solid", fgColor="2E75B6")
        SUB_FONT = Font(bold=True, color="FFFFFF", size=10)
        BOLD_FONT = Font(bold=True)
        THIN = Border(
            left=Side(style="thin"), right=Side(style="thin"),
            top=Side(style="thin"), bottom=Side(style="thin")
        )
        CHANGE_COLORS = {
            self.CHANGE_GEOM:      "FFF2CC",
            self.CHANGE_ATTR:      "DDEEFF",
            self.CHANGE_GEOM_ATTR: "FFE2CC",
            self.CHANGE_ADDED:     "D9EAD3",
            self.CHANGE_DELETED:   "FFD7D7",
            self.CHANGE_AMBIGUOUS: "E1D5E7",
        }

        def _hdr(ws, r, c, v, merge_end=None):
            cl = ws.cell(row=r, column=c, value=v)
            cl.fill = HDR_FILL; cl.font = HDR_FONT
            cl.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cl.border = THIN
            if merge_end:
                ws.merge_cells(start_row=r, start_column=c, end_row=r, end_column=merge_end)
            return cl

        def _sub(ws, r, c, v):
            cl = ws.cell(row=r, column=c, value=v)
            cl.fill = SUB_FILL; cl.font = SUB_FONT
            cl.alignment = Alignment(horizontal="left")
            cl.border = THIN
            return cl

        def _cell(ws, r, c, v, fill=None, bold=False):
            cl = ws.cell(row=r, column=c, value=v)
            cl.border = THIN
            cl.alignment = Alignment(wrap_text=True, vertical="top")
            if fill:
                cl.fill = PatternFill("solid", fgColor=fill)
            if bold:
                cl.font = BOLD_FONT
            return cl

        def _auto_w(ws, lo=12, hi=55):
            for col in ws.columns:
                ltr = get_column_letter(col[0].column)
                mx  = max((len(str(c.value or "")) for c in col), default=0)
                ws.column_dimensions[ltr].width = max(lo, min(mx + 2, hi))

        if geom_type == "Polygon":
            geo_hdrs = [
                "Old_Area", "New_Area", "Area_Diff", "Area_Diff_%",
                "Old_Vertex_Count", "New_Vertex_Count", "Vertex_Count_Diff",
                "Old_Centroid_X", "Old_Centroid_Y", "New_Centroid_X", "New_Centroid_Y",
                "Centroid_Distance", "Area_Changed", "Vertex_Count_Changed", "Spatially_Changed", "Shape_Changed"
            ]
            geo_keys = [
                "Old_Area", "New_Area", "Area_Diff", "Area_Diff_Pct",
                "Old_Vertex_Count", "New_Vertex_Count", "Vertex_Count_Diff",
                "Old_Centroid_X", "Old_Centroid_Y", "New_Centroid_X", "New_Centroid_Y",
                "Centroid_Distance", "Area_Changed", "Vertex_Count_Changed", "Spatially_Changed", "Shape_Changed"
            ]
        elif geom_type == "Polyline":
            geo_hdrs = [
                "Old_Length", "New_Length", "Length_Diff", "Length_Diff_%",
                "Old_Vertex_Count", "New_Vertex_Count", "Vertex_Count_Diff",
                "Old_Start_X", "Old_Start_Y", "Old_End_X", "Old_End_Y",
                "New_Start_X", "New_Start_Y", "New_End_X", "New_End_Y",
                "Centroid_Distance", "Length_Changed", "Vertex_Count_Changed", "Spatially_Changed", "Shape_Changed"
            ]
            geo_keys = [
                "Old_Length", "New_Length", "Length_Diff", "Length_Diff_Pct",
                "Old_Vertex_Count", "New_Vertex_Count", "Vertex_Count_Diff",
                "Old_Start_X", "Old_Start_Y", "Old_End_X", "Old_End_Y",
                "New_Start_X", "New_Start_Y", "New_End_X", "New_End_Y",
                "Centroid_Distance", "Length_Changed", "Vertex_Count_Changed", "Spatially_Changed", "Shape_Changed"
            ]
        elif geom_type == "Point":
            geo_hdrs = ["Old_X", "Old_Y", "Old_Z", "New_X", "New_Y", "New_Z", "X_Diff", "Y_Diff", "Z_Diff", "Spatial_Distance", "Spatially_Changed"]
            geo_keys = geo_hdrs[:]
        elif geom_type == "Multipoint":
            geo_hdrs = [
                "Old_Point_Count", "New_Point_Count", "Point_Count_Diff",
                "Old_Centroid_X", "Old_Centroid_Y", "New_Centroid_X", "New_Centroid_Y",
                "Centroid_Distance", "Vertex_Count_Changed", "Spatially_Changed", "Shape_Changed"
            ]
            geo_keys = geo_hdrs[:]
        else:
            geo_hdrs = geo_keys = []

        now_str   = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        total_chg = (cnt["geom_only"] + cnt["attr_only"] +
                     cnt["geom_attr"] + cnt["added"] + cnt["deleted"])

        # === Sheet 1 — Summary ===
        ws1 = wb.active
        ws1.title = "Summary"
        ws1.column_dimensions["A"].width = 44
        ws1.column_dimensions["B"].width = 24

        _hdr(ws1, 1, 1, "Geo Change Detection — Summary Report", merge_end=2)
        ws1.row_dimensions[1].height = 32

        for i, (k, v) in enumerate([
            ("Report Generated",        now_str),
            ("Geometry Type",           geom_type),
            ("Match Method",            match_method),
            ("Spatial Tolerance",       g_opts.get("spatial_tol", 0.3)),
            ("Area Decimal Places",     g_opts.get("area_decimals", 3) if geom_type == "Polygon" else "N/A"),
            ("Length Decimal Places",   g_opts.get("length_decimals", 3) if geom_type == "Polyline" else "N/A"),
            ("Vertex Count Tolerance",  g_opts.get("vertex_count_tol", 0)),
        ], start=2):
            _sub(ws1, i, 1, k)
            _cell(ws1, i, 2, v)

        sep = 10
        _hdr(ws1, sep, 1, "Change Statistics", merge_end=2)

        stats = [
            ("Total Features (Original)",      cnt["total_orig"]),
            ("Total Features (Modified)",      cnt["total_mod"]),
            ("",                               ""),
            ("Unchanged",                      cnt["unchanged"]),
            ("Geometry Changed",               cnt["geom_only"]),
            ("Attribute Changed",              cnt["attr_only"]),
            ("Geometry and Attribute Changed", cnt["geom_attr"]),
            ("Added Features",                 cnt["added"]),
            ("Deleted Features",               cnt["deleted"]),
            ("Ambiguous Matches",              cnt.get("ambiguous", 0)),
            ("Total Changed Features",         total_chg),
            ("",                               ""),
            ("--- Geometry Changes by Reason ---", ""),
            ("  • Area Changed",               cnt["reason_area"]),
            ("  • Length Changed",             cnt["reason_length"]),
            ("  • Vertex / Point Count Changed",cnt["reason_vertex"]),
            ("  • Spatial Position Changed",   cnt["reason_spatial"]),
            ("  • Shape Changed",              cnt["reason_shape"]),
            ("  • Z Coordinate Changed",       cnt["reason_z"]),
        ]

        if geom_type == "Polygon":
            stats += [("", ""),
                      ("Total Changed Area",       round(cnt["total_area_diff"], 4)),
                      ("Maximum Area Difference",  round(cnt["max_area_diff"],   4))]
        elif geom_type == "Polyline":
            stats += [("", ""),
                      ("Max Length Difference",    round(cnt["max_len_diff"],    4))]

        stats += [
            ("Max Spatial Displacement", round(cnt["max_spatial_dist"], 4)),
            ("Total Attribute Field Changes", cnt["total_attr_changes"])
        ]

        row_idx = sep + 1
        for k, v in stats:
            if k == "":
                ws1.row_dimensions[row_idx].height = 5
                row_idx += 1
                continue
            _sub(ws1, row_idx, 1, k)
            _cell(ws1, row_idx, 2, v, bold=(isinstance(v, (int, float)) and v > 0))
            row_idx += 1

        # QC Review Summary section on Sheet 1
        if qc_stats:
            row_idx += 1
            _hdr(ws1, row_idx, 1, "QC Review & Issue Tracking Summary", merge_end=2)
            row_idx += 1
            qc_summary_rows = [
                ("Total QC Issues Reviewed",              qc_stats["total"]),
                ("  • Maybe Changed (Verify Changes)",    qc_stats["maybe_changed"]),
                ("  • Not Changed",                       qc_stats["not_changed"]),
                ("  • Needs Review (Change Mismatch)",    qc_stats["needs_review"]),
                ("  • Feature Not Found",                 qc_stats["not_found"]),
                ("  • Feature Deleted",                   qc_stats["deleted"]),
            ]
            for k, v in qc_summary_rows:
                _sub(ws1, row_idx, 1, k)
                _cell(ws1, row_idx, 2, v, bold=(isinstance(v, int) and v > 0))
                row_idx += 1

        # === Sheet 2 — Detailed Report ===
        ws2 = wb.create_sheet("Detailed Report")
        detail_hdrs = (
            ["Unique_ID", "Change_Type", "Geometry_Change_Reason", "Geometry_Changed", "Attributes_Changed"]
            + geo_hdrs
            + ["Changed_Fields", "Old_Values", "New_Values"]
        )
        for ci, h in enumerate(detail_hdrs, 1):
            _hdr(ws2, 1, ci, h)

        for ri, rec in enumerate(results, 2):
            fc = CHANGE_COLORS.get(rec["change_type"], "F2F2F2" if ri % 2 == 0 else None)
            col = 1
            _cell(ws2, ri, col, str(rec["uid"]),                     fc); col += 1
            _cell(ws2, ri, col, rec["change_type"],                  fc); col += 1
            _cell(ws2, ri, col, rec.get("Geometry_Change_Reason",""),fc); col += 1
            _cell(ws2, ri, col, rec["geom_chg"],                     fc); col += 1
            _cell(ws2, ri, col, rec["attr_chg"],                     fc); col += 1
            for gk in geo_keys:
                _cell(ws2, ri, col, _round_val(rec.get(gk)), fc); col += 1
            _cell(ws2, ri, col, rec["changed_flds"], fc); col += 1
            _cell(ws2, ri, col, rec["old_vals"],     fc); col += 1
            _cell(ws2, ri, col, rec["new_vals"],     fc); col += 1

        ws2.freeze_panes = "A2"
        ws2.auto_filter.ref = ws2.dimensions
        _auto_w(ws2)

        # === Sheet 3 — Geometry Changes ===
        geom_types_set = {self.CHANGE_GEOM, self.CHANGE_GEOM_ATTR, self.CHANGE_ADDED, self.CHANGE_DELETED}
        geom_recs = [r for r in results if r["change_type"] in geom_types_set]
        if geom_recs:
            ws3 = wb.create_sheet("Geometry Changes")
            ws3_hdrs = ["Unique_ID", "Change_Type", "Geometry_Change_Reason"] + geo_hdrs
            for ci, h in enumerate(ws3_hdrs, 1):
                _hdr(ws3, 1, ci, h)

            for ri, rec in enumerate(geom_recs, 2):
                fc = CHANGE_COLORS.get(rec["change_type"], "F2F2F2" if ri % 2 == 0 else None)
                _cell(ws3, ri, 1, str(rec["uid"]),                      fc)
                _cell(ws3, ri, 2, rec["change_type"],                   fc)
                _cell(ws3, ri, 3, rec.get("Geometry_Change_Reason",""), fc)
                for ci, gk in enumerate(geo_keys, 4):
                    _cell(ws3, ri, ci, _round_val(rec.get(gk)), fc)

            ws3.freeze_panes = "A2"
            ws3.auto_filter.ref = ws3.dimensions
            _auto_w(ws3)

        # === Sheet 4 — Attribute Changes (flattened) ===
        attr_recs = [r for r in results if r["change_type"] in (self.CHANGE_ATTR, self.CHANGE_GEOM_ATTR)]
        if attr_recs:
            ws4 = wb.create_sheet("Attribute Changes")
            for ci, h in enumerate(["Unique_ID", "Change_Type", "Field_Name", "Old_Value", "New_Value"], 1):
                _hdr(ws4, 1, ci, h)
            ri = 2
            for rec in attr_recs:
                flds = rec.get("changed_flds_list", [])
                ov_d = rec.get("old_vals_dict", {})
                nv_d = rec.get("new_vals_dict", {})
                fc   = CHANGE_COLORS.get(rec["change_type"], "F2F2F2" if ri % 2 == 0 else None)
                if flds:
                    for fn in flds:
                        _cell(ws4, ri, 1, str(rec["uid"]),  fc)
                        _cell(ws4, ri, 2, rec["change_type"], fc)
                        _cell(ws4, ri, 3, fn,               fc)
                        _cell(ws4, ri, 4, ov_d.get(fn, ""), fc)
                        _cell(ws4, ri, 5, nv_d.get(fn, ""), fc)
                        ri += 1
                else:
                    _cell(ws4, ri, 1, str(rec["uid"]),      fc)
                    _cell(ws4, ri, 2, rec["change_type"],   fc)
                    ri += 1
            ws4.freeze_panes = "A2"
            ws4.auto_filter.ref = ws4.dimensions
            _auto_w(ws4)

        # === Sheet 5 — QC Review & Issue Tracking ===
        if qc_records:
            ws5 = wb.create_sheet("QC Review")
            qc_hdrs = [
                "Issue_ID", "Feature_ID", "Issue_Type", "Reviewer_Note", "Reviewer",
                "Created_Date", "QC_Status", "Change_Type", "Geometry_Change_Reason",
                "QC_Assessment", "Original_Feature_Found", "Modified_Feature_Found",
                "Distance_To_Current_Feature", "Review_Run_ID"
            ]
            for ci, h in enumerate(qc_hdrs, 1):
                _hdr(ws5, 1, ci, h)

            QC_ASSESSMENT_COLORS = {
                QC_ASSESSMENT_MAYBE_CHANGED: "E2EFDA",  # Soft green
                QC_ASSESSMENT_NOT_CHANGED:   "F2F2F2",  # Soft gray
                QC_ASSESSMENT_NEEDS_REVIEW:  "FFF2CC",  # Soft amber
                QC_ASSESSMENT_NOT_FOUND:     "FCE4D6",  # Soft salmon
                QC_ASSESSMENT_DELETED:       "FFD7D7",  # Soft red
            }

            for ri, qrec in enumerate(qc_records, 2):
                ass_desc = qrec.get("QC_Assessment_Desc", QC_ASSESSMENT_NOT_CHECKED)
                qa_code = qrec.get("QC_Assessment", "")
                label_out = f"{qa_code} {ass_desc}".strip() if qa_code else ass_desc
                qfc = QC_ASSESSMENT_COLORS.get(ass_desc, "F2F2F2" if ri % 2 == 0 else None)
                _cell(ws5, ri, 1, qrec.get("Issue_ID", ""), qfc)
                _cell(ws5, ri, 2, str(qrec.get("Feature_ID", "")), qfc)
                _cell(ws5, ri, 3, qrec.get("Issue_Type_Desc", ""), qfc)
                _cell(ws5, ri, 4, qrec.get("Reviewer_Note", ""), qfc)
                _cell(ws5, ri, 5, qrec.get("Reviewer", ""), qfc)
                c_date = qrec.get("Created_Date")
                c_date_str = c_date.strftime("%Y-%m-%d %H:%M:%S") if isinstance(c_date, (datetime.datetime, datetime.date)) else str(c_date or "")
                _cell(ws5, ri, 6, c_date_str, qfc)
                _cell(ws5, ri, 7, qrec.get("QC_Status_Desc", ""), qfc)
                _cell(ws5, ri, 8, qrec.get("Change_Type", ""), qfc)
                _cell(ws5, ri, 9, qrec.get("Geometry_Change_Reason", ""), qfc)
                _cell(ws5, ri, 10, label_out, qfc, bold=True)
                _cell(ws5, ri, 11, "Yes" if qrec.get("Original_Feature_Found") else "No", qfc)
                _cell(ws5, ri, 12, "Yes" if qrec.get("Modified_Feature_Found") else "No", qfc)
                dist_val = qrec.get("Distance_To_Current_Feature")
                _cell(ws5, ri, 13, _round_val(dist_val, 4) if dist_val is not None else "N/A", qfc)
                _cell(ws5, ri, 14, qrec.get("Review_Run_ID", ""), qfc)

            ws5.freeze_panes = "A2"
            ws5.auto_filter.ref = ws5.dimensions
            _auto_w(ws5)

        wb.save(path)

    # ------------------------------------------------------------------
    # HTML report
    # ------------------------------------------------------------------

    def _write_html(self, path, results, cnt, geom_type,
                    orig_fc, mod_fc, match_method="", g_opts=None,
                    qc_records=None, qc_stats=None):
        g_opts = g_opts or {}
        now_str    = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        orig_name  = os.path.basename(orig_fc) if orig_fc else "Original"
        mod_name   = os.path.basename(mod_fc) if mod_fc else "Modified"
        method_lbl = match_method or "By Spatial Location (Spatial Join)"
        sp_tol     = g_opts.get("spatial_tol", 0.03)

        total_orig = cnt.get("total_orig", 0)
        total_mod  = cnt.get("total_mod", 0)
        unchanged  = cnt.get("unchanged", 0)
        geom_only  = cnt.get("geom_only", 0)
        attr_only  = cnt.get("attr_only", 0)
        geom_attr  = cnt.get("geom_attr", 0)
        added      = cnt.get("added", 0)
        deleted    = cnt.get("deleted", 0)
        ambiguous  = cnt.get("ambiguous", 0)
        total_chg  = geom_only + attr_only + geom_attr + added + deleted

        # ── KPI Stat Cards ──
        card_data = [
            ("Total (Original)", f"{total_orig:,}", "📋", "var(--brand)", False),
            ("Unchanged",        f"{unchanged:,}",  "⏸", "var(--text-muted)", False),
            ("Geom Changed",     f"{geom_only:,}",  "📐", "var(--amber)", False),
            ("Attr Changed",     f"{attr_only:,}",  "🏷", "var(--blue)", False),
            ("Geom + Attr",      f"{geom_attr:,}",  "🔀", "var(--orange)", False),
            ("Added",            f"{added:,}",      "➕", "var(--green)", False),
            ("Deleted",          f"{deleted:,}",    "➖", "var(--red)", False),
        ]
        if ambiguous > 0:
            card_data.append(("Ambiguous", f"{ambiguous:,}", "🟣", "var(--purple)", False))
        card_data.append(("Total Changed", f"{total_chg:,}", "⚡", "var(--brand-light)", True))

        cards_html = "".join(
            f'<div class="stat-card stat-card--highlight card emphasis" style="--card-accent:{accent};">'
            f'<div class="stat-card__value card-val">{val}</div>'
            f'<div class="stat-card__label card-lbl"><span class="icon">{icon}</span> {lbl}</div>'
            f'</div>'
            if is_emph else
            f'<div class="stat-card card" style="--card-accent:{accent};">'
            f'<div class="stat-card__value card-val">{val}</div>'
            f'<div class="stat-card__label card-lbl"><span class="icon">{icon}</span> {lbl}</div>'
            f'</div>'
            for lbl, val, icon, accent, is_emph in card_data
        )

        # ── Geometry Change Reasons & Mini Bar Chart Percentages ──
        r_area   = cnt.get("reason_area", 0)
        r_length = cnt.get("reason_length", 0)
        r_vertex = cnt.get("reason_vertex", 0)
        r_pos    = cnt.get("reason_spatial", 0)
        r_shape  = cnt.get("reason_shape", 0)
        r_z      = cnt.get("reason_z", 0)

        geom_chg_base = max(geom_only + geom_attr, 1) if (geom_only + geom_attr) > 0 else 1
        has_geom_chg  = (geom_only + geom_attr) > 0

        def _bar_pct(val):
            if not has_geom_chg or val <= 0:
                return 0.0
            return min(100.0, (val / geom_chg_base) * 100.0)

        p_area   = _bar_pct(r_area)
        p_length = _bar_pct(r_length)
        p_vertex = _bar_pct(r_vertex)
        p_pos    = _bar_pct(r_pos)
        p_shape  = _bar_pct(r_shape)
        p_z      = _bar_pct(r_z)

        # ── Summary Grid Rows ──
        left_rows = f"""
            <div class="summary-row">
                <span class="summary-row__label">Total Features (Original)</span>
                <span class="summary-row__value">{total_orig:,}</span>
            </div>
            <div class="summary-row">
                <span class="summary-row__label">Total Features (Modified)</span>
                <span class="summary-row__value">{total_mod:,}</span>
            </div>
            <div class="summary-row">
                <span class="summary-row__label">Match Method</span>
                <span class="summary-row__value" style="font-family:var(--font-sans);font-weight:500;font-size:0.85em;">{method_lbl}</span>
            </div>
            <div class="summary-row">
                <span class="summary-row__label">Unchanged</span>
                <span class="summary-row__value">{unchanged:,}</span>
            </div>
            <div class="summary-row">
                <span class="summary-row__label">Geometry Changed</span>
                <span class="summary-row__value summary-row__value--highlight">{geom_only:,}</span>
            </div>
            <div class="summary-row">
                <span class="summary-row__label">Attribute Changed</span>
                <span class="summary-row__value">{attr_only:,}</span>
            </div>
            <div class="summary-row">
                <span class="summary-row__label">Geom + Attr Changed</span>
                <span class="summary-row__value">{geom_attr:,}</span>
            </div>
            <div class="summary-row">
                <span class="summary-row__label">Added Features</span>
                <span class="summary-row__value">{added:,}</span>
            </div>
            <div class="summary-row">
                <span class="summary-row__label">Deleted Features</span>
                <span class="summary-row__value">{deleted:,}</span>
            </div>
            {f'<div class="summary-row"><span class="summary-row__label">Ambiguous Matches</span><span class="summary-row__value" style="color:var(--purple);font-weight:600;">{ambiguous:,}</span></div>' if ambiguous > 0 else ''}
            <div class="summary-row summary-row--total">
                <span class="summary-row__label">Total Changed</span>
                <span class="summary-row__value">{total_chg:,}</span>
            </div>
        """

        right_metrics = []
        if geom_type == "Polygon":
            right_metrics.append(f"""
                <div class="summary-row">
                    <span class="summary-row__label">Total Changed Area</span>
                    <span class="summary-row__value">{cnt.get('total_area_diff', 0.0):.4f}</span>
                </div>
                <div class="summary-row">
                    <span class="summary-row__label">Maximum Area Difference</span>
                    <span class="summary-row__value">{cnt.get('max_area_diff', 0.0):.4f}</span>
                </div>
            """)
        elif geom_type == "Polyline":
            right_metrics.append(f"""
                <div class="summary-row">
                    <span class="summary-row__label">Maximum Length Difference</span>
                    <span class="summary-row__value">{cnt.get('max_len_diff', 0.0):.4f}</span>
                </div>
            """)

        right_metrics.append(f"""
            <div class="summary-row">
                <span class="summary-row__label">Max Spatial Displacement</span>
                <span class="summary-row__value">{cnt.get('max_spatial_dist', 0.0):.4f}</span>
            </div>
            <div class="summary-row">
                <span class="summary-row__label">Attribute Field Changes</span>
                <span class="summary-row__value">{cnt.get('total_attr_changes', 0):,}</span>
            </div>
        """)

        # ── QC Review Section ──
        qc_section_html = ""
        if qc_stats and qc_records:
            qc_card_data = [
                ("Total QC Issues", f"{qc_stats['total']:,}",         "👁️", "var(--brand)"),
                ("Maybe Changed",   f"{qc_stats['maybe_changed']:,}", "✅", "var(--green)"),
                ("Not Changed",     f"{qc_stats['not_changed']:,}",   "⏸", "var(--text-muted)"),
                ("Needs Review",    f"{qc_stats['needs_review']:,}",  "⚠️", "var(--amber)"),
                ("Not Found",       f"{qc_stats['not_found']:,}",     "❓", "var(--purple)"),
                ("Deleted",         f"{qc_stats['deleted']:,}",       "🗑️", "var(--red)"),
            ]
            qc_cards_html = "".join(
                f'<div class="stat-card card" style="--card-accent:{accent};">'
                f'<div class="stat-card__value card-val">{val}</div>'
                f'<div class="stat-card__label card-lbl"><span class="icon">{icon}</span> {lbl}</div>'
                f'</div>'
                for lbl, val, icon, accent in qc_card_data
            )

            QC_BADGES = {
                QC_ASSESSMENT_MAYBE_CHANGED: "badge-qc-maybe",
                QC_ASSESSMENT_NOT_CHANGED:   "badge-qc-not",
                QC_ASSESSMENT_NEEDS_REVIEW:  "badge-qc-review",
                QC_ASSESSMENT_NOT_FOUND:     "badge-qc-missing",
                QC_ASSESSMENT_DELETED:       "badge-qc-deleted",
                "Ambiguous Match":           "badge-ambiguous",
            }

            qc_rows = []
            for qr in qc_records:
                ass_desc  = qr["QC_Assessment_Desc"]
                qa_code   = qr.get("QC_Assessment", "")
                badge_lbl = f"{qa_code} {ass_desc}".strip() if qa_code else ass_desc
                badge_c   = QC_BADGES.get(ass_desc, "badge-qc-not")
                c_date    = qr.get("Created_Date")
                c_date_str= c_date.strftime("%Y-%m-%d") if isinstance(c_date, (datetime.datetime, datetime.date)) else str(c_date or "")
                dist_str  = f"{qr['Distance_To_Current_Feature']:.2f}" if qr.get("Distance_To_Current_Feature") is not None else "N/A"
                r_note    = str(qr.get("Reviewer_Note", "")).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
                iss_id    = str(qr.get("Issue_ID", ""))
                feat_id   = str(qr.get("Feature_ID", ""))
                iss_type  = str(qr.get("Issue_Type_Desc", ""))
                reviewer  = str(qr.get("Reviewer", ""))
                qc_st     = str(qr.get("QC_Status_Desc", ""))
                chg_t     = str(qr.get("Change_Type", ""))
                chg_r     = str(qr.get("Geometry_Change_Reason", ""))

                qc_rows.append(
                    f'<tr data-qc-assessment="{ass_desc}">'
                    f'<td class="uid">{iss_id}</td>'
                    f'<td class="uid">{feat_id}</td>'
                    f'<td><span class="reason-tag">{iss_type}</span></td>'
                    f'<td style="max-width:320px;word-break:break-word">{r_note}</td>'
                    f'<td>{reviewer}</td>'
                    f'<td>{c_date_str}</td>'
                    f'<td>{qc_st}</td>'
                    f'<td>{chg_t}</td>'
                    f'<td><small>{chg_r}</small></td>'
                    f'<td><span class="badge {badge_c}">{badge_lbl}</span></td>'
                    f'<td class="num">{dist_str}</td>'
                    f'</tr>'
                )

            qc_section_html = f"""
    <div class="section" id="qc-review-section">
        <div class="section__title">
            👁️ QC Review &amp; Issue Tracking Summary
            <small>({len(qc_records):,} historical issues analyzed)</small>
        </div>
        <div class="stats-grid" style="padding:0 0 var(--sp-4) 0;">
            {qc_cards_html}
        </div>

        <div class="filter-panel" id="qcFilterPanel">
            <div class="filter-group">
                <span class="filter-group__label">QC Assessment</span>
                <button type="button" class="filter-btn-qc active" data-qc="ALL">All <span class="count-badge">{len(qc_records):,}</span></button>
                <button type="button" class="filter-btn-qc" data-qc="{QC_ASSESSMENT_MAYBE_CHANGED}">Maybe Changed <span class="count-badge">{qc_stats['maybe_changed']:,}</span></button>
                <button type="button" class="filter-btn-qc" data-qc="{QC_ASSESSMENT_NEEDS_REVIEW}">Needs Review <span class="count-badge">{qc_stats['needs_review']:,}</span></button>
                <button type="button" class="filter-btn-qc" data-qc="{QC_ASSESSMENT_NOT_CHANGED}">Not Changed <span class="count-badge">{qc_stats['not_changed']:,}</span></button>
                <button type="button" class="filter-btn-qc" data-qc="{QC_ASSESSMENT_NOT_FOUND}">Not Found <span class="count-badge">{qc_stats['not_found']:,}</span></button>
                <button type="button" class="filter-btn-qc" data-qc="{QC_ASSESSMENT_DELETED}">Deleted <span class="count-badge">{qc_stats['deleted']:,}</span></button>
            </div>
            <div class="filter-group">
                <input class="search-input" id="qcTableSearch" type="text" placeholder="Search Issue ID, Feature ID, Note, Reviewer…" />
                <button type="button" class="btn-reset" id="resetQcFilters">Reset</button>
            </div>
            <div class="filter-stats">
                Showing <strong id="visibleQcCount">{len(qc_records):,}</strong> of {len(qc_records):,} issues
            </div>
        </div>

        <div class="table-wrap">
            <table class="det" id="qcTable">
                <thead>
                    <tr>
                        <th>Issue ID</th>
                        <th>Feature ID</th>
                        <th>Issue Type</th>
                        <th>Reviewer Note</th>
                        <th>Reviewer</th>
                        <th>Created</th>
                        <th>Status</th>
                        <th>Detected Change</th>
                        <th>Change Reason</th>
                        <th>QC Assessment</th>
                        <th class="num">Dist to Mod</th>
                    </tr>
                </thead>
                <tbody>
                    {"".join(qc_rows)}
                    <tr id="noQcResultsRow" class="no-results-row" style="display:none">
                        <td colspan="11">No QC issues match the selected filters.</td>
                    </tr>
                </tbody>
            </table>
        </div>
    </div>
"""

        # ── Feature Class Comparison Table ──
        if geom_type == "Polygon":
            geo_hdrs = ["Old Area", "New Area", "Area Δ", "Area Δ%", "Old V", "New V", "Centroid Δ"]
            geo_keys = ["Old_Area", "New_Area", "Area_Diff", "Area_Diff_Pct", "Old_Vertex_Count", "New_Vertex_Count", "Centroid_Distance"]
        elif geom_type == "Polyline":
            geo_hdrs = ["Old Length", "New Length", "Length Δ", "Length Δ%", "Old V", "New V", "Displacement"]
            geo_keys = ["Old_Length", "New_Length", "Length_Diff", "Length_Diff_Pct", "Old_Vertex_Count", "New_Vertex_Count", "Centroid_Distance"]
        elif geom_type == "Point":
            geo_hdrs = ["Old X", "Old Y", "Old Z", "New X", "New Y", "New Z", "Spatial Δ"]
            geo_keys = ["Old_X", "Old_Y", "Old_Z", "New_X", "New_Y", "New_Z", "Spatial_Distance"]
        elif geom_type == "Multipoint":
            geo_hdrs = ["Old Points", "New Points", "Points Δ", "Centroid Δ"]
            geo_keys = ["Old_Point_Count", "New_Point_Count", "Point_Count_Diff", "Centroid_Distance"]
        else:
            geo_hdrs = geo_keys = []

        BADGES = {
            self.CHANGE_GEOM:      "badge-geom",
            self.CHANGE_ATTR:      "badge-attr",
            self.CHANGE_GEOM_ATTR: "badge-both",
            self.CHANGE_ADDED:     "badge-added",
            self.CHANGE_DELETED:   "badge-deleted",
            self.CHANGE_AMBIGUOUS: "badge-ambiguous",
        }

        def _fmt(v):
            if v is None: return "—"
            if isinstance(v, float):
                if abs(v) < 1e-10: return "0"
                if abs(v) < 0.0001: return f"{v:.4e}"
                return f"{v:.4f}"
            return str(v)

        geo_th = "".join(f'<th class="num">{h}</th>' for h in geo_hdrs)
        col_span = 3 + len(geo_hdrs) + 3
        rows = []

        for rec in results:
            chg_type = rec["change_type"]
            badge_cls = BADGES.get(chg_type, "badge-ambiguous")
            reason = rec.get("Geometry_Change_Reason", "")
            reason_badge = f'<span class="reason-tag">{reason}</span>' if reason else ""
            geos = "".join(f'<td class="num">{_fmt(rec.get(gk))}</td>' for gk in geo_keys)
            ov = rec["old_vals"].replace("&","&amp;").replace("<","&lt;")
            nv = rec["new_vals"].replace("&","&amp;").replace("<","&lt;")
            uid_val = _fmt(rec["uid"])
            flds = rec.get("changed_flds", "") or "—"

            rows.append(
                f'<tr data-change-type="{chg_type}" data-reason="{reason}">'
                f'<td class="uid">{uid_val}</td>'
                f'<td><span class="badge {badge_cls}">{chg_type}</span></td>'
                f'<td>{reason_badge}</td>'
                f'{geos}'
                f'<td class="flds">{flds}</td>'
                f'<td class="json">{ov}</td>'
                f'<td class="json">{nv}</td>'
                f'</tr>'
            )

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Geo Change Detection &amp; QC Review Dashboard</title>
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link href="https://fonts.googleapis.com/css2?family=Inter:opsz,wght@14..32,400;14..32,500;14..32,600;14..32,700;14..32,800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet" />
    <style>
        /* ═══════════════════ DESIGN TOKENS ═══════════════════ */
        :root {{
            --bg-body: #f2f4f0;
            --bg-surface: #ffffff;
            --bg-surface-alt: #f8f9f6;
            --bg-header: #1e2b27;
            --bg-header-grad: linear-gradient(145deg, #1e2b27 0%, #2a3f35 100%);

            --text-primary: #1e2b27;
            --text-secondary: #3f5245;
            --text-muted: #6b7d6e;
            --text-inverse: #ffffff;
            --text-on-brand: #d4e0c8;

            --border: #dce1d6;
            --border-light: #eaece4;
            --border-focus: #588157;

            --brand: #588157;
            --brand-dark: #3a5a40;
            --brand-light: #7a9b79;
            --brand-tint: rgba(88, 129, 87, 0.12);
            --brand-glow: rgba(88, 129, 87, 0.25);

            --amber: #b47d44;
            --amber-tint: #f5ede2;
            --blue: #4f7a86;
            --blue-tint: #e6edef;
            --orange: #b86a2e;
            --orange-tint: #f3e7dc;
            --green: #3a7a4a;
            --green-tint: #e2ede4;
            --red: #a5534a;
            --red-tint: #f0e0dd;
            --purple: #7a5f78;
            --purple-tint: #ede6ec;

            --radius-sm: 6px;
            --radius-md: 10px;
            --radius-lg: 16px;
            --radius-xl: 20px;

            --shadow-xs: 0 1px 3px rgba(0, 0, 0, 0.04);
            --shadow-sm: 0 2px 8px rgba(0, 0, 0, 0.06);
            --shadow-md: 0 8px 30px rgba(0, 0, 0, 0.08);
            --shadow-lg: 0 16px 48px rgba(0, 0, 0, 0.10);
            --shadow-focus: 0 0 0 4px var(--brand-tint);

            --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            --font-mono: 'JetBrains Mono', 'Consolas', 'Courier New', monospace;

            --sp-1: 4px;
            --sp-2: 8px;
            --sp-3: 12px;
            --sp-4: 16px;
            --sp-5: 24px;
            --sp-6: 32px;
            --sp-7: 40px;
            --sp-8: 56px;

            --transition: 0.2s cubic-bezier(0.4, 0, 0.2, 1);

            /* dark mode overrides */
            --dm-bg-body: #141b17;
            --dm-bg-surface: #1e2b24;
            --dm-bg-surface-alt: #25332b;
            --dm-text-primary: #e4ece0;
            --dm-text-secondary: #bccbbc;
            --dm-text-muted: #879b85;
            --dm-border: #334238;
            --dm-border-light: #2a3a2f;
            --dm-shadow: 0 8px 30px rgba(0, 0, 0, 0.5);
        }}

        [data-theme="dark"] {{
            --bg-body: var(--dm-bg-body);
            --bg-surface: var(--dm-bg-surface);
            --bg-surface-alt: var(--dm-bg-surface-alt);
            --text-primary: var(--dm-text-primary);
            --text-secondary: var(--dm-text-secondary);
            --text-muted: var(--dm-text-muted);
            --border: var(--dm-border);
            --border-light: var(--dm-border-light);
            --brand-tint: rgba(88, 129, 87, 0.18);
            --shadow-sm: var(--dm-shadow);
            --shadow-md: var(--dm-shadow);
            --shadow-lg: var(--dm-shadow);
            --amber-tint: #2f2618;
            --blue-tint: #182b2f;
            --orange-tint: #311f12;
            --green-tint: #142b19;
            --red-tint: #2f1b18;
            --purple-tint: #281e27;
            --bg-header: #0f1713;
            --bg-header-grad: linear-gradient(145deg, #0f1713 0%, #1a2a20 100%);
        }}

        /* ═══════════════════ RESET & BASE ═══════════════════ */
        *, *::before, *::after {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}

        ::-webkit-scrollbar {{
            width: 7px;
            height: 7px;
        }}
        ::-webkit-scrollbar-track {{
            background: var(--bg-body);
        }}
        ::-webkit-scrollbar-thumb {{
            background: var(--brand);
            border-radius: 10px;
        }}
        ::-webkit-scrollbar-thumb:hover {{
            background: var(--brand-dark);
        }}

        html {{
            scroll-behavior: smooth;
        }}

        body {{
            font-family: var(--font-sans);
            background: var(--bg-body);
            color: var(--text-primary);
            font-size: 14px;
            line-height: 1.6;
            -webkit-font-smoothing: antialiased;
            -moz-osx-font-smoothing: grayscale;
            transition: background var(--transition), color var(--transition);
        }}

        /* ═══════════════════ HEADER ═══════════════════ */
        .app-header {{
            background: var(--bg-header-grad);
            color: var(--text-inverse);
            padding: var(--sp-5) var(--sp-6);
            border-bottom: 3px solid var(--brand);
            position: sticky;
            top: 0;
            z-index: 100;
            backdrop-filter: blur(4px);
        }}
        .app-header__inner {{
            max-width: 1440px;
            margin: 0 auto;
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            justify-content: space-between;
            gap: var(--sp-3);
        }}
        .app-header__brand {{
            display: flex;
            align-items: center;
            gap: var(--sp-2);
        }}
        .app-header__brand .dot {{
            color: var(--brand-light);
            font-size: 1.6em;
            line-height: 1;
        }}
        .app-header h1 {{
            font-family: var(--font-sans);
            font-size: 1.4em;
            font-weight: 700;
            letter-spacing: -0.02em;
            line-height: 1.2;
        }}
        .app-header h1 small {{
            font-weight: 400;
            font-size: 0.6em;
            color: var(--text-on-brand);
            opacity: 0.7;
            margin-left: var(--sp-2);
        }}
        .app-header__meta {{
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: var(--sp-2) var(--sp-4);
            font-size: 0.85em;
            color: var(--text-on-brand);
            opacity: 0.85;
        }}
        .app-header__meta .sep {{
            color: rgba(255, 255, 255, 0.15);
        }}
        .app-header__meta strong {{
            color: var(--text-inverse);
            font-weight: 600;
        }}

        .header-tags {{
            display: flex;
            flex-wrap: wrap;
            gap: var(--sp-2);
            margin-top: var(--sp-3);
            max-width: 1440px;
            margin-left: auto;
            margin-right: auto;
        }}
        .header-tag {{
            background: var(--brand-tint);
            color: var(--text-on-brand);
            border: 1px solid rgba(255, 255, 255, 0.10);
            padding: 4px 14px;
            border-radius: 30px;
            font-size: 0.78em;
            font-weight: 500;
            display: inline-flex;
            align-items: center;
            gap: 6px;
            letter-spacing: 0.2px;
            backdrop-filter: blur(2px);
        }}

        /* ═══════════════════ THEME TOGGLE ═══════════════════ */
        .theme-toggle {{
            background: rgba(255, 255, 255, 0.08);
            border: 1px solid rgba(255, 255, 255, 0.12);
            color: var(--text-inverse);
            width: 36px;
            height: 36px;
            border-radius: 50%;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.1em;
            transition: background var(--transition), transform var(--transition);
            flex-shrink: 0;
        }}
        .theme-toggle:hover {{
            background: rgba(255, 255, 255, 0.16);
            transform: scale(1.05);
        }}
        .theme-toggle:active {{
            transform: scale(0.94);
        }}

        /* ═══════════════════ STAT CARDS ═══════════════════ */
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(110px, 1fr));
            gap: var(--sp-3);
            padding: var(--sp-5) var(--sp-6);
            max-width: 1440px;
            margin: 0 auto;
        }}
        .stat-card {{
            background: var(--bg-surface);
            border: 1px solid var(--border);
            border-radius: var(--radius-md);
            padding: var(--sp-3) var(--sp-4);
            box-shadow: var(--shadow-xs);
            transition: transform var(--transition), box-shadow var(--transition), border-color var(--transition);
            position: relative;
            overflow: hidden;
        }}
        .stat-card::before {{
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 3px;
            background: var(--card-accent, var(--text-muted));
            border-radius: var(--radius-md) var(--radius-md) 0 0;
        }}
        .stat-card:hover {{
            transform: translateY(-2px);
            box-shadow: var(--shadow-md);
            border-color: var(--border-focus);
        }}
        .stat-card__value, .card-val {{
            font-family: var(--font-mono);
            font-size: 1.8em;
            font-weight: 600;
            line-height: 1.1;
            color: var(--text-primary);
            letter-spacing: -0.02em;
        }}
        .stat-card__label, .card-lbl {{
            font-size: 0.72em;
            font-weight: 600;
            color: var(--text-muted);
            margin-top: var(--sp-1);
            text-transform: uppercase;
            letter-spacing: 0.4px;
            display: flex;
            align-items: center;
            gap: 5px;
        }}
        .stat-card__label .icon {{
            font-size: 1.1em;
        }}
        .stat-card--highlight {{
            background: var(--brand-dark);
            border-color: var(--brand);
        }}
        .stat-card--highlight .stat-card__value {{
            color: var(--text-on-brand);
        }}
        .stat-card--highlight .stat-card__label {{
            color: rgba(255, 255, 255, 0.7);
        }}
        .stat-card--highlight::before {{
            background: var(--brand-light);
        }}

        /* ═══════════════════ SUMMARY SECTION ═══════════════════ */
        .summary-section {{
            padding: 0 var(--sp-6) var(--sp-5);
            max-width: 1440px;
            margin: 0 auto;
        }}
        .summary-card {{
            background: var(--bg-surface);
            border: 1px solid var(--border);
            border-radius: var(--radius-lg);
            padding: var(--sp-5) var(--sp-6);
            box-shadow: var(--shadow-sm);
            transition: border-color var(--transition), box-shadow var(--transition);
        }}
        .summary-card:hover {{
            border-color: var(--border-focus);
            box-shadow: var(--shadow-md);
        }}
        .summary-card__header {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            flex-wrap: wrap;
            gap: var(--sp-2);
            margin-bottom: var(--sp-4);
        }}
        .summary-card__header h2 {{
            font-family: var(--font-sans);
            font-size: 1.1em;
            font-weight: 700;
            color: var(--text-primary);
            display: flex;
            align-items: center;
            gap: var(--sp-2);
        }}
        .summary-card__header h2 .badge-count {{
            background: var(--brand-tint);
            color: var(--brand-dark);
            font-size: 0.7em;
            font-weight: 700;
            padding: 2px 12px;
            border-radius: 30px;
        }}
        .summary-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: var(--sp-4);
        }}
        .summary-grid__left, .summary-grid__right {{
            display: flex;
            flex-direction: column;
            gap: var(--sp-2);
        }}
        .summary-row {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: var(--sp-2) 0;
            border-bottom: 1px solid var(--border-light);
            font-size: 0.9em;
        }}
        .summary-row:last-child {{
            border-bottom: none;
        }}
        .summary-row__label {{
            color: var(--text-secondary);
        }}
        .summary-row__value {{
            font-family: var(--font-mono);
            font-weight: 500;
            color: var(--text-primary);
        }}
        .summary-row__value--highlight {{
            color: var(--brand-dark);
            font-weight: 600;
        }}
        .summary-row--total {{
            border-bottom: 2px solid var(--brand) !important;
            padding-top: var(--sp-3);
            margin-top: var(--sp-1);
        }}
        .summary-row--total .summary-row__label {{
            font-weight: 700;
            color: var(--text-primary);
        }}
        .summary-row--total .summary-row__value {{
            font-weight: 700;
            font-size: 1.05em;
            color: var(--brand-dark);
        }}

        .summary-divider {{
            border: none;
            border-top: 2px solid var(--border-light);
            margin: var(--sp-2) 0;
        }}

        /* mini chart */
        .mini-chart {{
            display: flex;
            align-items: center;
            gap: var(--sp-4);
            margin-top: var(--sp-3);
            flex-wrap: wrap;
        }}
        .mini-chart__bar-group {{
            display: flex;
            align-items: center;
            gap: var(--sp-2);
            flex: 1;
            min-width: 120px;
        }}
        .mini-chart__label {{
            font-size: 0.75em;
            font-weight: 600;
            color: var(--text-muted);
            width: 60px;
            flex-shrink: 0;
            text-align: right;
        }}
        .mini-chart__track {{
            flex: 1;
            height: 8px;
            background: var(--border-light);
            border-radius: 20px;
            overflow: hidden;
            min-width: 40px;
        }}
        .mini-chart__fill {{
            height: 100%;
            border-radius: 20px;
            transition: width 0.6s ease;
            background: var(--brand);
        }}
        .mini-chart__fill--amber {{ background: var(--amber); }}
        .mini-chart__fill--blue {{ background: var(--blue); }}
        .mini-chart__fill--orange {{ background: var(--orange); }}
        .mini-chart__fill--green {{ background: var(--green); }}
        .mini-chart__fill--red {{ background: var(--red); }}
        .mini-chart__value {{
            font-family: var(--font-mono);
            font-size: 0.8em;
            font-weight: 500;
            color: var(--text-secondary);
            width: 40px;
            flex-shrink: 0;
            text-align: right;
        }}

        .reasons-tbl {{
            width: 100%;
            border-collapse: collapse;
            margin-top: var(--sp-2);
            font-size: 0.88em;
        }}
        .reasons-tbl th {{
            text-align: left;
            padding: 6px 4px;
            font-size: 0.72em;
            font-weight: 700;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.4px;
            border-bottom: 2px solid var(--border-light);
        }}
        .reasons-tbl th.num, .reasons-tbl td.num {{
            text-align: right;
            font-family: var(--font-mono);
        }}
        .reasons-tbl td {{
            padding: 6px 4px;
            border-bottom: 1px solid var(--border-light);
            color: var(--text-primary);
            vertical-align: middle;
        }}
        .reasons-tbl tr:last-child td {{
            border-bottom: none;
        }}
        .reason-dot {{
            display: inline-block;
            width: 8px;
            height: 8px;
            border-radius: 50%;
            margin-right: 6px;
            vertical-align: middle;
        }}

        /* ═══════════════════ FILTER PANEL ═══════════════════ */
        .filter-panel {{
            background: var(--bg-surface);
            border: 1px solid var(--border);
            border-radius: var(--radius-md);
            padding: var(--sp-3) var(--sp-4);
            box-shadow: var(--shadow-xs);
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: var(--sp-3) var(--sp-4);
            margin-bottom: var(--sp-4);
            transition: border-color var(--transition), box-shadow var(--transition);
        }}
        .filter-panel:focus-within {{
            border-color: var(--border-focus);
            box-shadow: var(--shadow-focus);
        }}
        .filter-group {{
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: var(--sp-2);
        }}
        .filter-group__label {{
            font-size: 0.75em;
            font-weight: 700;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.4px;
            margin-right: var(--sp-1);
        }}
        .filter-btn, .filter-btn-qc {{
            background: var(--bg-body);
            border: 1px solid var(--border);
            color: var(--text-secondary);
            padding: 5px 14px;
            border-radius: 30px;
            font-size: 0.78em;
            font-weight: 600;
            cursor: pointer;
            font-family: inherit;
            transition: all var(--transition);
            white-space: nowrap;
        }}
        .filter-btn:hover, .filter-btn-qc:hover {{
            background: var(--border-light);
            border-color: var(--text-muted);
            color: var(--text-primary);
        }}
        .filter-btn.active, .filter-btn-qc.active {{
            background: var(--brand-dark);
            color: var(--text-inverse);
            border-color: var(--brand-dark);
            box-shadow: 0 2px 8px rgba(88, 129, 87, 0.25);
        }}
        .filter-btn .count-badge, .filter-btn-qc .count-badge {{
            background: rgba(255, 255, 255, 0.15);
            padding: 0 8px;
            border-radius: 20px;
            font-size: 0.7em;
            margin-left: 4px;
        }}
        .filter-btn.active .count-badge, .filter-btn-qc.active .count-badge {{
            background: rgba(255, 255, 255, 0.20);
        }}

        .filter-select {{
            padding: 6px 12px 6px 14px;
            border: 1px solid var(--border);
            border-radius: var(--radius-sm);
            font-size: 0.82em;
            background: var(--bg-surface);
            color: var(--text-primary);
            font-family: inherit;
            outline: none;
            transition: border-color var(--transition), box-shadow var(--transition);
            min-width: 150px;
            appearance: none;
            background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M1 1l4 4 4-4' stroke='%236b7d6e' stroke-width='1.5' fill='none' stroke-linecap='round'/%3E%3C/svg%3E");
            background-repeat: no-repeat;
            background-position: right 12px center;
        }}
        .filter-select:focus {{
            border-color: var(--border-focus);
            box-shadow: var(--shadow-focus);
        }}

        .search-input {{
            padding: 6px 12px 6px 36px;
            border: 1px solid var(--border);
            border-radius: var(--radius-sm);
            font-size: 0.82em;
            background: var(--bg-surface) url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='%236b7d6e' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Ccircle cx='11' cy='11' r='8'/%3E%3Cpath d='M21 21l-4.35-4.35'/%3E%3C/svg%3E") no-repeat 12px center;
            color: var(--text-primary);
            font-family: inherit;
            outline: none;
            transition: border-color var(--transition), box-shadow var(--transition), width var(--transition);
            min-width: 180px;
            width: 100%;
            max-width: 280px;
        }}
        .search-input:focus {{
            border-color: var(--border-focus);
            box-shadow: var(--shadow-focus);
            max-width: 340px;
        }}
        .search-input::placeholder {{
            color: var(--text-muted);
            opacity: 0.7;
        }}

        .filter-stats {{
            font-size: 0.82em;
            color: var(--text-muted);
            margin-left: auto;
            white-space: nowrap;
        }}
        .filter-stats strong {{
            color: var(--text-primary);
            font-weight: 700;
        }}

        .btn-reset {{
            background: none;
            border: none;
            color: var(--brand-dark);
            font-size: 0.78em;
            font-weight: 700;
            cursor: pointer;
            padding: 4px 8px;
            font-family: inherit;
            text-decoration: underline;
            text-underline-offset: 2px;
            transition: color var(--transition);
        }}
        .btn-reset:hover {{
            color: var(--brand);
        }}

        /* ═══════════════════ LEGEND ═══════════════════ */
        .legend {{
            display: flex;
            flex-wrap: wrap;
            gap: var(--sp-3);
            margin-bottom: var(--sp-3);
        }}
        .legend-item {{
            display: flex;
            align-items: center;
            gap: 6px;
            font-size: 0.78em;
            color: var(--text-secondary);
        }}

        /* ═══════════════════ TABLE ═══════════════════ */
        .table-wrap {{
            overflow-x: auto;
            border-radius: var(--radius-md);
            border: 1px solid var(--border);
            box-shadow: var(--shadow-xs);
            transition: border-color var(--transition);
        }}
        .table-wrap:focus-within {{
            border-color: var(--border-focus);
        }}

        table.det {{
            border-collapse: collapse;
            width: 100%;
            font-size: 0.8em;
            background: var(--bg-surface);
            min-width: 900px;
        }}
        table.det thead th {{
            background: var(--bg-surface-alt);
            color: var(--text-secondary);
            padding: 10px 12px;
            text-align: left;
            font-weight: 600;
            font-size: 0.72em;
            text-transform: uppercase;
            letter-spacing: 0.4px;
            border-bottom: 2px solid var(--border);
            position: sticky;
            top: 0;
            z-index: 2;
            white-space: nowrap;
        }}
        table.det thead th:first-child {{
            border-radius: var(--radius-md) 0 0 0;
        }}
        table.det thead th:last-child {{
            border-radius: 0 var(--radius-md) 0 0;
        }}
        table.det tbody td {{
            padding: 8px 12px;
            border-bottom: 1px solid var(--border-light);
            vertical-align: middle;
            transition: background var(--transition);
        }}
        table.det tbody tr {{
            transition: background var(--transition), opacity var(--transition);
        }}
        table.det tbody tr:nth-child(even) {{
            background: var(--bg-surface-alt);
        }}
        table.det tbody tr:hover {{
            background: var(--brand-tint) !important;
        }}
        table.det tbody tr.hidden-row {{
            display: none;
        }}
        td.num {{
            font-family: var(--font-mono);
            font-size: 0.85em;
            text-align: right;
            white-space: nowrap;
            color: var(--text-secondary);
        }}
        td.uid {{
            font-family: var(--font-mono);
            font-weight: 600;
            color: var(--text-primary);
            font-size: 0.85em;
        }}
        td.flds {{
            color: var(--text-muted);
            font-size: 0.8em;
            max-width: 120px;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }}
        td.json {{
            font-family: var(--font-mono);
            font-size: 0.75em;
            color: var(--text-muted);
            max-width: 160px;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            word-break: break-all;
        }}
        .no-results-row td {{
            text-align: center;
            padding: var(--sp-6) !important;
            color: var(--text-muted);
            font-style: italic;
            font-size: 0.95em;
        }}

        /* ═══════════════════ BADGES ═══════════════════ */
        .badge {{
            display: inline-block;
            padding: 2px 12px;
            border-radius: 30px;
            font-size: 0.7em;
            font-weight: 700;
            white-space: nowrap;
            border: 1px solid transparent;
            letter-spacing: 0.2px;
            text-transform: uppercase;
        }}
        .badge-geom {{
            background: var(--amber-tint);
            color: var(--amber);
            border-color: #d4be9e;
        }}
        .badge-attr {{
            background: var(--blue-tint);
            color: var(--blue);
            border-color: #b6cdd2;
        }}
        .badge-both {{
            background: var(--orange-tint);
            color: var(--orange);
            border-color: #dbbf9e;
        }}
        .badge-added {{
            background: var(--green-tint);
            color: var(--green);
            border-color: #a8c9ae;
        }}
        .badge-deleted {{
            background: var(--red-tint);
            color: var(--red);
            border-color: #dbb5ae;
        }}
        .badge-ambiguous {{
            background: var(--purple-tint);
            color: var(--purple);
            border-color: #cbb5c9;
        }}
        .badge-qc-maybe {{
            background: var(--green-tint);
            color: var(--green);
            border-color: #a8c9ae;
            font-weight: 700;
        }}
        .badge-qc-not {{
            background: var(--bg-surface-alt);
            color: var(--text-secondary);
            border-color: var(--border);
        }}
        .badge-qc-review {{
            background: var(--amber-tint);
            color: var(--amber);
            border-color: #d4be9e;
        }}
        .badge-qc-missing {{
            background: var(--purple-tint);
            color: var(--purple);
            border-color: #cbb5c9;
        }}
        .badge-qc-deleted {{
            background: var(--red-tint);
            color: var(--red);
            border-color: #dbb5ae;
        }}

        .reason-tag {{
            display: inline-block;
            padding: 1px 10px;
            border-radius: 4px;
            background: var(--bg-body);
            color: var(--text-secondary);
            border: 1px solid var(--border);
            font-size: 0.7em;
            font-weight: 600;
            white-space: nowrap;
        }}

        /* ═══════════════════ SECTION CONTAINER ═══════════════════ */
        .section {{
            padding: var(--sp-5) var(--sp-6);
            max-width: 1440px;
            margin: 0 auto;
        }}
        .section__title {{
            font-family: var(--font-sans);
            font-size: 1.1em;
            font-weight: 700;
            color: var(--text-primary);
            margin-bottom: var(--sp-4);
            display: flex;
            align-items: center;
            gap: var(--sp-2);
            padding-left: var(--sp-3);
            border-left: 4px solid var(--brand);
        }}
        .section__title small {{
            font-weight: 400;
            color: var(--text-muted);
            font-size: 0.7em;
        }}

        /* ═══════════════════ FOOTER ═══════════════════ */
        .app-footer {{
            text-align: center;
            padding: var(--sp-5) var(--sp-6);
            color: var(--text-muted);
            font-size: 0.8em;
            border-top: 2px solid var(--brand);
            background: var(--bg-surface);
            margin-top: var(--sp-4);
        }}
        .app-footer strong {{
            color: var(--brand-dark);
        }}

        /* ═══════════════════ RESPONSIVE ═══════════════════ */
        @media (max-width: 900px) {{
            .summary-grid {{
                grid-template-columns: 1fr;
            }}
            .app-header__meta {{
                font-size: 0.75em;
            }}
            .app-header h1 {{
                font-size: 1.1em;
            }}
        }}

        @media (max-width: 720px) {{
            .app-header {{
                padding: var(--sp-4);
            }}
            .app-header__inner {{
                flex-direction: column;
                align-items: stretch;
                gap: var(--sp-2);
            }}
            .app-header__brand {{
                justify-content: space-between;
            }}
            .app-header__meta {{
                font-size: 0.7em;
                gap: var(--sp-1) var(--sp-2);
            }}
            .header-tags {{
                gap: var(--sp-1);
            }}
            .header-tag {{
                font-size: 0.65em;
                padding: 2px 10px;
            }}
            .stats-grid {{
                grid-template-columns: repeat(2, 1fr);
                padding: var(--sp-4);
                gap: var(--sp-2);
            }}
            .stat-card__value {{
                font-size: 1.4em;
            }}
            .section {{
                padding: var(--sp-4);
            }}
            .summary-section {{
                padding: 0 var(--sp-4) var(--sp-4);
            }}
            .summary-card {{
                padding: var(--sp-4);
            }}
            .filter-panel {{
                flex-direction: column;
                align-items: stretch;
                gap: var(--sp-2);
            }}
            .filter-group {{
                flex-wrap: wrap;
            }}
            .search-input {{
                max-width: 100%;
                min-width: unset;
            }}
            .filter-stats {{
                margin-left: 0;
                text-align: center;
            }}
            .mini-chart {{
                flex-direction: column;
                align-items: stretch;
                gap: var(--sp-2);
            }}
            .mini-chart__bar-group {{
                min-width: unset;
            }}
            .mini-chart__label {{
                width: 50px;
                font-size: 0.7em;
            }}
            table.det {{
                font-size: 0.72em;
                min-width: 700px;
            }}
            table.det thead th,
            table.det tbody td {{
                padding: 6px 8px;
            }}
            .app-footer {{
                padding: var(--sp-4);
                font-size: 0.7em;
            }}
            .theme-toggle {{
                width: 32px;
                height: 32px;
                font-size: 0.9em;
            }}
            .filter-btn, .filter-btn-qc {{
                font-size: 0.7em;
                padding: 4px 10px;
            }}
            .filter-select {{
                min-width: 120px;
                font-size: 0.75em;
            }}
        }}

        @media (max-width: 440px) {{
            .stats-grid {{
                grid-template-columns: 1fr 1fr;
                gap: var(--sp-2);
            }}
            .stat-card {{
                padding: var(--sp-2) var(--sp-3);
            }}
            .stat-card__value {{
                font-size: 1.2em;
            }}
            .stat-card__label {{
                font-size: 0.6em;
            }}
            .section__title {{
                font-size: 0.95em;
                padding-left: var(--sp-2);
            }}
            table.det {{
                font-size: 0.65em;
                min-width: 560px;
            }}
            table.det thead th,
            table.det tbody td {{
                padding: 4px 6px;
            }}
            .badge {{
                font-size: 0.6em;
                padding: 1px 8px;
            }}
            .reason-tag {{
                font-size: 0.6em;
                padding: 1px 6px;
            }}
        }}
    </style>
</head>
<body>

    <!-- ═══════════════════ HEADER ═══════════════════ -->
    <header class="app-header">
        <div class="app-header__inner">
            <div class="app-header__brand">
                <span class="dot">◆</span>
                <h1>
                    Geo Change Detection &amp; QC Review
                    <small>v5.0.0 Refined</small>
                </h1>
            </div>
            <div class="app-header__meta">
                <span><strong>{geom_type}</strong></span>
                <span class="sep">|</span>
                <span>{method_lbl} · tol {sp_tol}</span>
                <span class="sep">|</span>
                <span>{now_str}</span>
                <button class="theme-toggle" id="themeToggle" aria-label="Toggle dark mode">🌙</button>
            </div>
        </div>
        <div class="header-tags">
            <span class="header-tag">📅 {now_str}</span>
            <span class="header-tag">📄 Original: {orig_name}</span>
            <span class="header-tag">📄 Modified: {mod_name}</span>
            <span class="header-tag">🔗 v5.0.0 Refined</span>
        </div>
    </header>

    <!-- ═══════════════════ STAT CARDS ═══════════════════ -->
    <div class="stats-grid">
        {cards_html}
    </div>

    <!-- ═══════════════════ SUMMARY SECTION ═══════════════════ -->
    <div class="summary-section">
        <div class="summary-card">
            <div class="summary-card__header">
                <h2>
                    📊 Summary Statistics
                    <span class="badge-count">{len(results):,} total</span>
                </h2>
            </div>
            <div class="summary-grid">
                <div class="summary-grid__left">
                    {left_rows}
                </div>
                <div class="summary-grid__right">
                    {"".join(right_metrics)}
                    <hr class="summary-divider" />
                    <div style="font-size:0.75em;font-weight:700;color:var(--text-muted);margin-top:var(--sp-1);margin-bottom:var(--sp-2);text-transform:uppercase;letter-spacing:0.4px;">
                        Geometry Change Reasons
                    </div>
                    <table class="reasons-tbl">
                        <thead>
                            <tr>
                                <th>Reason</th>
                                <th class="num">Count</th>
                                <th style="width:40%;">Share</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr>
                                <td><span class="reason-dot" style="background:var(--amber);"></span> Area</td>
                                <td class="num">{r_area:,}</td>
                                <td>
                                    <div class="mini-chart__track">
                                        <div class="mini-chart__fill mini-chart__fill--amber" style="width:{p_area:.1f}%;"></div>
                                    </div>
                                </td>
                            </tr>
                            <tr>
                                <td><span class="reason-dot" style="background:var(--blue);"></span> Length</td>
                                <td class="num">{r_length:,}</td>
                                <td>
                                    <div class="mini-chart__track">
                                        <div class="mini-chart__fill mini-chart__fill--blue" style="width:{p_length:.1f}%;"></div>
                                    </div>
                                </td>
                            </tr>
                            <tr>
                                <td><span class="reason-dot" style="background:var(--orange);"></span> Vertex</td>
                                <td class="num">{r_vertex:,}</td>
                                <td>
                                    <div class="mini-chart__track">
                                        <div class="mini-chart__fill mini-chart__fill--orange" style="width:{p_vertex:.1f}%;"></div>
                                    </div>
                                </td>
                            </tr>
                            <tr>
                                <td><span class="reason-dot" style="background:var(--green);"></span> Position</td>
                                <td class="num">{r_pos:,}</td>
                                <td>
                                    <div class="mini-chart__track">
                                        <div class="mini-chart__fill mini-chart__fill--green" style="width:{p_pos:.1f}%;"></div>
                                    </div>
                                </td>
                            </tr>
                            <tr>
                                <td><span class="reason-dot" style="background:var(--red);"></span> Shape</td>
                                <td class="num">{r_shape:,}</td>
                                <td>
                                    <div class="mini-chart__track">
                                        <div class="mini-chart__fill mini-chart__fill--red" style="width:{p_shape:.1f}%;"></div>
                                    </div>
                                </td>
                            </tr>
                            <tr>
                                <td><span class="reason-dot" style="background:var(--purple);"></span> Z Coord</td>
                                <td class="num">{r_z:,}</td>
                                <td>
                                    <div class="mini-chart__track">
                                        <div class="mini-chart__fill" style="width:{p_z:.1f}%;background:var(--purple);"></div>
                                    </div>
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>

    <!-- ═══════════════════ QC REVIEW SECTION (OPTIONAL) ═══════════════════ -->
    {qc_section_html}

    <!-- ═══════════════════ DETAILED TABLE SECTION ═══════════════════ -->
    <div class="section">
        <div class="section__title">
            📋 Detailed Feature Change Report
            <small>({len(results):,} features)</small>
        </div>

        <!-- Filter Panel -->
        <div class="filter-panel" id="filterPanel">
            <div class="filter-group">
                <span class="filter-group__label">Change</span>
                <button type="button" class="filter-btn active" data-type="ALL">All <span class="count-badge">{len(results):,}</span></button>
                <button type="button" class="filter-btn" data-type="{self.CHANGE_GEOM}">Geom <span class="count-badge">{geom_only:,}</span></button>
                <button type="button" class="filter-btn" data-type="{self.CHANGE_ATTR}">Attr <span class="count-badge">{attr_only:,}</span></button>
                <button type="button" class="filter-btn" data-type="{self.CHANGE_GEOM_ATTR}">Geom+Attr <span class="count-badge">{geom_attr:,}</span></button>
                <button type="button" class="filter-btn" data-type="{self.CHANGE_ADDED}">Added <span class="count-badge">{added:,}</span></button>
                <button type="button" class="filter-btn" data-type="{self.CHANGE_DELETED}">Deleted <span class="count-badge">{deleted:,}</span></button>
                {f'<button type="button" class="filter-btn" data-type="{self.CHANGE_AMBIGUOUS}">Ambiguous <span class="count-badge">{ambiguous:,}</span></button>' if ambiguous > 0 else ""}
            </div>

            <div class="filter-group">
                <span class="filter-group__label">Reason</span>
                <select class="filter-select" id="reasonFilter">
                    <option value="">All Change Reasons</option>
                    <option value="Area Changed">Area Changed</option>
                    <option value="Length Changed">Length Changed</option>
                    <option value="Vertex Count Changed">Vertex / Point Count Changed</option>
                    <option value="Spatial Position Changed">Spatial Position Changed</option>
                    <option value="Shape Changed">Shape Changed</option>
                    <option value="Z Coordinate Changed">Z Coordinate Changed</option>
                    <option value="attribute">Attribute Changes</option>
                </select>
                <input class="search-input" id="tableSearch" type="text" placeholder="Search ID, reason, fields, values…" />
                <button type="button" class="btn-reset" id="resetFilters">Reset</button>
            </div>

            <div class="filter-stats">
                Showing <strong id="visibleCount">{len(results):,}</strong> of {len(results):,} features
            </div>
        </div>

        <!-- Legend -->
        <div class="legend">
            <span class="legend-item"><span class="badge badge-geom">Geometry</span></span>
            <span class="legend-item"><span class="badge badge-attr">Attribute</span></span>
            <span class="legend-item"><span class="badge badge-both">Geom + Attr</span></span>
            <span class="legend-item"><span class="badge badge-added">Added</span></span>
            <span class="legend-item"><span class="badge badge-deleted">Deleted</span></span>
            {f'<span class="legend-item"><span class="badge badge-ambiguous">Ambiguous</span></span>' if ambiguous > 0 else ""}
        </div>

        <!-- Table -->
        <div class="table-wrap">
            <table class="det" id="featureTable">
                <thead>
                    <tr>
                        <th>Unique ID</th>
                        <th>Change Type</th>
                        <th>Reason</th>
                        {geo_th}
                        <th>Changed Fields</th>
                        <th>Old Values</th>
                        <th>New Values</th>
                    </tr>
                </thead>
                <tbody>
                    {"".join(rows)}
                    <tr id="noResultsRow" class="no-results-row" style="display:none">
                        <td colspan="{col_span}">No features match the selected filters.</td>
                    </tr>
                </tbody>
            </table>
        </div>
    </div>

    <!-- ═══════════════════ FOOTER ═══════════════════ -->
    <footer class="app-footer">
        Geo Change Detection &amp; QC Review Tool <strong>v5.0.0 Refined</strong> &mdash; {now_str}
    </footer>

    <!-- ═══════════════════ SCRIPT ═══════════════════ -->
    <script>
        document.addEventListener('DOMContentLoaded', function() {{
            // ── Theme Toggle ──
            var themeBtn = document.getElementById('themeToggle');
            var currentTheme = localStorage.getItem('fccd_theme') || '';
            if (currentTheme === 'dark') {{
                document.documentElement.setAttribute('data-theme', 'dark');
                if (themeBtn) themeBtn.textContent = '☀️';
            }}
            if (themeBtn) {{
                themeBtn.addEventListener('click', function() {{
                    var isDark = document.documentElement.getAttribute('data-theme') === 'dark';
                    if (isDark) {{
                        document.documentElement.removeAttribute('data-theme');
                        this.textContent = '🌙';
                        localStorage.setItem('fccd_theme', 'light');
                    }} else {{
                        document.documentElement.setAttribute('data-theme', 'dark');
                        this.textContent = '☀️';
                        localStorage.setItem('fccd_theme', 'dark');
                    }}
                }});
            }}

            // ── Feature Table Filtering ──
            var typeButtons = document.querySelectorAll('.filter-btn');
            var reasonSelect = document.getElementById('reasonFilter');
            var searchInput = document.getElementById('tableSearch');
            var resetBtn = document.getElementById('resetFilters');
            var visibleCountElem = document.getElementById('visibleCount');
            var rows = document.querySelectorAll('#featureTable tbody tr:not(.no-results-row)');
            var noResultsRow = document.getElementById('noResultsRow');
            var activeType = 'ALL';

            function applyFilters() {{
                var selectedReason = reasonSelect ? reasonSelect.value.toLowerCase().trim() : '';
                var query = searchInput ? searchInput.value.toLowerCase().trim() : '';
                var visible = 0;

                rows.forEach(function(row) {{
                    var rowType = (row.getAttribute('data-change-type') || '').trim();
                    var rowReason = (row.getAttribute('data-reason') || '').toLowerCase();
                    var rowText = row.innerText.toLowerCase();

                    var typeMatch = (activeType === 'ALL' || rowType === activeType);
                    var reasonMatch = true;
                    if (selectedReason) {{
                        if (selectedReason === 'attribute') {{
                            reasonMatch = rowType.indexOf('Attribute') !== -1;
                        }} else {{
                            reasonMatch = rowReason.indexOf(selectedReason) !== -1;
                        }}
                    }}
                    var textMatch = (!query || rowText.indexOf(query) !== -1);

                    if (typeMatch && reasonMatch && textMatch) {{
                        row.style.display = '';
                        visible++;
                    }} else {{
                        row.style.display = 'none';
                    }}
                }});

                if (visibleCountElem) {{
                    visibleCountElem.textContent = visible.toLocaleString();
                }}
                if (noResultsRow) {{
                    noResultsRow.style.display = (visible === 0) ? '' : 'none';
                }}
            }}

            typeButtons.forEach(function(btn) {{
                btn.addEventListener('click', function() {{
                    typeButtons.forEach(function(b) {{ b.classList.remove('active'); }});
                    this.classList.add('active');
                    activeType = this.getAttribute('data-type');
                    applyFilters();
                }});
            }});

            if (reasonSelect) reasonSelect.addEventListener('change', applyFilters);
            if (searchInput) searchInput.addEventListener('input', applyFilters);

            if (resetBtn) {{
                resetBtn.addEventListener('click', function() {{
                    typeButtons.forEach(function(b) {{ b.classList.remove('active'); }});
                    var allBtn = document.querySelector('.filter-btn[data-type="ALL"]');
                    if (allBtn) allBtn.classList.add('active');
                    activeType = 'ALL';
                    if (reasonSelect) reasonSelect.value = '';
                    if (searchInput) searchInput.value = '';
                    applyFilters();
                }});
            }}

            // ── QC Review Table Filtering ──
            var qcButtons = document.querySelectorAll('.filter-btn-qc');
            var qcSearchInput = document.getElementById('qcTableSearch');
            var resetQcBtn = document.getElementById('resetQcFilters');
            var visibleQcCountElem = document.getElementById('visibleQcCount');
            var qcRows = document.querySelectorAll('#qcTable tbody tr:not(.no-results-row)');
            var noQcResultsRow = document.getElementById('noQcResultsRow');
            var activeQcType = 'ALL';

            function applyQcFilters() {{
                var query = qcSearchInput ? qcSearchInput.value.toLowerCase().trim() : '';
                var visible = 0;

                qcRows.forEach(function(row) {{
                    var rowQc = (row.getAttribute('data-qc-assessment') || '').trim();
                    var rowText = row.innerText.toLowerCase();

                    var qcMatch = (activeQcType === 'ALL' || rowQc === activeQcType);
                    var textMatch = (!query || rowText.indexOf(query) !== -1);

                    if (qcMatch && textMatch) {{
                        row.style.display = '';
                        visible++;
                    }} else {{
                        row.style.display = 'none';
                    }}
                }});

                if (visibleQcCountElem) {{
                    visibleQcCountElem.textContent = visible.toLocaleString();
                }}
                if (noQcResultsRow) {{
                    noQcResultsRow.style.display = (visible === 0) ? '' : 'none';
                }}
            }}

            qcButtons.forEach(function(btn) {{
                btn.addEventListener('click', function() {{
                    qcButtons.forEach(function(b) {{ b.classList.remove('active'); }});
                    this.classList.add('active');
                    activeQcType = this.getAttribute('data-qc');
                    applyQcFilters();
                }});
            }});

            if (qcSearchInput) qcSearchInput.addEventListener('input', applyQcFilters);

            if (resetQcBtn) {{
                resetQcBtn.addEventListener('click', function() {{
                    qcButtons.forEach(function(b) {{ b.classList.remove('active'); }});
                    var allQcBtn = document.querySelector('.filter-btn-qc[data-qc="ALL"]');
                    if (allQcBtn) allQcBtn.classList.add('active');
                    activeQcType = 'ALL';
                    if (qcSearchInput) qcSearchInput.value = '';
                    applyQcFilters();
                }});
            }}
        }});
    </script>
</body>
</html>"""

        with open(path, "w", encoding="utf-8") as fh:
            fh.write(html)


    # ------------------------------------------------------------------
    # Console summary
    # ------------------------------------------------------------------

    def _print_summary(self, cnt, geom_type, qc_stats=None):
        total_chg = (cnt["geom_only"] + cnt["attr_only"] +
                     cnt["geom_attr"] + cnt["added"] + cnt["deleted"])
        lines = [
            "=" * 60,
            "  GEO CHANGE DETECTION - SUMMARY  (v5.0.0 Refined)",
            "=" * 60,
            f"  Original features       : {cnt['total_orig']:>12,}",
            f"  Modified features       : {cnt['total_mod']:>12,}",
            "-" * 60,
            f"  Unchanged               : {cnt['unchanged']:>12,}",
            f"  Geometry Changed        : {cnt['geom_only']:>12,}",
            f"  Attribute Changed       : {cnt['attr_only']:>12,}",
            f"  Geom + Attr Changed     : {cnt['geom_attr']:>12,}",
            f"  Added                   : {cnt['added']:>12,}",
            f"  Deleted                 : {cnt['deleted']:>12,}",
            f"  Ambiguous Matches       : {cnt.get('ambiguous', 0):>12,}",
            f"  Total Changed           : {total_chg:>12,}",
            "-" * 60,
            f"  Geometry Change Breakdown:",
            f"    - Area Changes        : {cnt['reason_area']:>12,}",
            f"    - Length Changes      : {cnt['reason_length']:>12,}",
            f"    - Vertex Count Changes: {cnt['reason_vertex']:>12,}",
            f"    - Spatial Pos Changes : {cnt['reason_spatial']:>12,}",
            f"    - Shape Changes       : {cnt['reason_shape']:>12,}",
            f"    - Z Coordinate Changes: {cnt['reason_z']:>12,}",
            "-" * 60,
        ]
        if geom_type == "Polygon":
            lines.append(f"  Total changed area      : {cnt['total_area_diff']:>15.4f}")
            lines.append(f"  Max area difference     : {cnt['max_area_diff']:>15.4f}")
        elif geom_type == "Polyline":
            lines.append(f"  Max length difference   : {cnt['max_len_diff']:>15.4f}")
        lines.append(f"  Max spatial displacement: {cnt['max_spatial_dist']:>15.4f}")
        lines.append(f"  Attribute field changes : {cnt['total_attr_changes']:>12,}")

        if qc_stats:
            lines.extend([
                "-" * 60,
                "  QC REVIEW & ISSUE TRACKING SUMMARY:",
                f"    - Total QC Issues     : {qc_stats['total']:>12,}",
                f"    - Maybe Changed       : {qc_stats['maybe_changed']:>12,}",
                f"    - Not Changed         : {qc_stats['not_changed']:>12,}",
                f"    - Needs Review        : {qc_stats['needs_review']:>12,}",
                f"    - Feature Not Found   : {qc_stats['not_found']:>12,}",
                f"    - Feature Deleted     : {qc_stats['deleted']:>12,}",
            ])

        lines.append("=" * 60)

        for line in lines:
            self.msg.addMessage(line)


# ---------------------------------------------------------------------------
# ArcGIS Pro Tool class
# ---------------------------------------------------------------------------

class ChangeDetectionTool:
    """
    ArcGIS Pro Python Toolbox Tool — Geo Change Detection v5.0.0 Refined.
    """

    def __init__(self):
        self.label       = "Geo Change Detection"
        self.description = (
            "Enterprise-grade tool (v5.0.0 Refined) for comparing two Feature Classes "
            "and detecting geometry and attribute changes with an Advanced Multi-Level "
            "Geometry Comparison Engine, and an optional QC Review & Issue Tracking correlation module. "
            "Supports Spatial Location (Spatial Join), Attribute Field, and OBJECTID matching modes. "
            "Generates comprehensive GDB feature classes, an executive Excel workbook (5 sheets), "
            "and a standalone interactive HTML Dashboard with dark mode."
        )
        self.canRunInBackground = True
        self._out_fc     = None
        self._qc_review_fc = None
        self._add_to_map = True

    # ----------------------------------------------------------------
    # Parameters
    # ----------------------------------------------------------------

    def getParameterInfo(self):
        params = []

        # ============================================================
        # Category: Basic Comparison
        # ============================================================

        # [0] Original FC / Layer
        p0 = arcpy.Parameter(
            displayName="Original Feature Class / Layer",
            name="orig_fc",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input",
            category="Basic Comparison"
        )
        params.append(p0)

        # [1] Modified FC / Layer
        p1 = arcpy.Parameter(
            displayName="Modified Feature Class / Layer",
            name="mod_fc",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input",
            category="Basic Comparison"
        )
        params.append(p1)

        # [2] Unique ID Field
        p2 = arcpy.Parameter(
            displayName="Unique ID Field (not needed for OBJECTID / Spatial modes)",
            name="uid_field",
            datatype="Field",
            parameterType="Optional",
            direction="Input",
            category="Basic Comparison"
        )
        p2.parameterDependencies = ["orig_fc"]
        p2.enabled = False
        params.append(p2)

        # [3] Output Workspace
        p3 = arcpy.Parameter(
            displayName="Output Workspace",
            name="out_ws",
            datatype="DEWorkspace",
            parameterType="Required",
            direction="Input",
            category="Basic Comparison"
        )
        try:
            aprx = arcpy.mp.ArcGISProject("CURRENT")
            p3.value = aprx.defaultGeodatabase
        except Exception:
            try:
                p3.value = arcpy.env.workspace or arcpy.env.scratchGDB
            except Exception:
                pass
        params.append(p3)

        # [4] Output FC Name
        p4 = arcpy.Parameter(
            displayName="Output Feature Class Name",
            name="out_name",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
            category="Basic Comparison"
        )
        p4.value = "ChangeDetection_Result"
        params.append(p4)

        # ============================================================
        # Category: Attribute Comparison
        # ============================================================

        # [5] Compare Attributes
        p5 = arcpy.Parameter(
            displayName="Compare Attributes",
            name="compare_attrs",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input",
            category="Attribute Comparison"
        )
        p5.value = True
        params.append(p5)

        # ============================================================
        # Category: Geometry Comparison
        # ============================================================

        # [6] Compare Geometry
        p6 = arcpy.Parameter(
            displayName="Compare Geometry",
            name="compare_geom",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input",
            category="Geometry Comparison"
        )
        p6.value = True
        params.append(p6)

        # [7] Geometry Tolerance (Legacy)
        p7 = arcpy.Parameter(
            displayName="General Geometry Tolerance (Legacy floor)",
            name="geom_tol",
            datatype="GPDouble",
            parameterType="Optional",
            direction="Input",
            category="Geometry Comparison"
        )
        p7.value = 0.0
        params.append(p7)

        # ============================================================
        # Category: Attribute Comparison (Cont.)
        # ============================================================

        # [8] Ignore Case
        p8 = arcpy.Parameter(
            displayName="Ignore Case Sensitivity in Text Fields",
            name="ignore_case",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input",
            category="Attribute Comparison"
        )
        p8.value = False
        params.append(p8)

        # [9] Treat NULL = Empty String
        p9 = arcpy.Parameter(
            displayName="Treat NULL and Empty String as Equal",
            name="null_empty_eq",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input",
            category="Attribute Comparison"
        )
        p9.value = False
        params.append(p9)

        # [10] Fields to Compare — Same Schema
        p10 = arcpy.Parameter(
            displayName="Fields to Compare (Same Schema)",
            name="same_schema_fields",
            datatype="Field",
            parameterType="Optional",
            direction="Input",
            multiValue=True,
            category="Attribute Comparison"
        )
        p10.parameterDependencies = ["orig_fc"]
        p10.filter.list = _FIELD_TYPE_FILTER
        p10.enabled = False
        params.append(p10)

        # [11] Field Mapping — Different Schema
        p11 = arcpy.Parameter(
            displayName="Field Mapping (Different Schema)",
            name="field_mapping",
            datatype="GPValueTable",
            parameterType="Optional",
            direction="Input",
            category="Attribute Comparison"
        )
        p11.columns        = [["GPString", "Original Field"],
                               ["GPString", "Modified Field"],
                               ["GPString", "Compare As"]]
        p11.filters[0].type = "ValueList"
        p11.filters[1].type = "ValueList"
        p11.filters[2].type = "ValueList"
        p11.filters[2].list = ["text", "numeric", "date"]
        p11.enabled = False
        params.append(p11)

        # ============================================================
        # Category: Output / Reports
        # ============================================================

        # [12] Export Added Separately
        p12 = arcpy.Parameter(
            displayName="Export Added Features Separately",
            name="export_added",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input",
            category="Output / Reports"
        )
        p12.value = False
        params.append(p12)

        # [13] Export Deleted Separately
        p13 = arcpy.Parameter(
            displayName="Export Deleted Features Separately",
            name="export_deleted",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input",
            category="Output / Reports"
        )
        p13.value = False
        params.append(p13)

        # [14] Save Settings
        p14 = arcpy.Parameter(
            displayName="Save Comparison Settings to JSON",
            name="save_settings",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input",
            category="Settings"
        )
        p14.value = False
        params.append(p14)

        # [15] Settings File (output)
        p15 = arcpy.Parameter(
            displayName="Settings File Path (JSON output)",
            name="settings_file",
            datatype="DEFile",
            parameterType="Optional",
            direction="Output",
            category="Settings"
        )
        p15.filter.list = ["json"]
        p15.enabled = False
        params.append(p15)

        # [16] Load Settings
        p16 = arcpy.Parameter(
            displayName="Load Settings from JSON File",
            name="load_settings_file",
            datatype="DEFile",
            parameterType="Optional",
            direction="Input",
            category="Settings"
        )
        p16.filter.list = ["json"]
        params.append(p16)

        # [17] Filter Output by Change Type
        p17 = arcpy.Parameter(
            displayName="Filter Output FC by Change Type (empty = all)",
            name="filter_change_types",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
            multiValue=True,
            category="Output / Reports"
        )
        p17.filter.type = "ValueList"
        p17.filter.list = [
            ChangeEngine.CHANGE_GEOM,
            ChangeEngine.CHANGE_ATTR,
            ChangeEngine.CHANGE_GEOM_ATTR,
            ChangeEngine.CHANGE_ADDED,
            ChangeEngine.CHANGE_DELETED,
        ]
        params.append(p17)

        # [18] Generate HTML Report
        p18 = arcpy.Parameter(
            displayName="Generate HTML Report",
            name="gen_html",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input",
            category="Output / Reports"
        )
        p18.value = True
        params.append(p18)

        # [19] Add Result to Map
        p19 = arcpy.Parameter(
            displayName="Add Result to Current Map",
            name="add_to_map",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input",
            category="Output / Reports"
        )
        p19.value = True
        params.append(p19)

        # ============================================================
        # Category: Basic Comparison (Cont.)
        # ============================================================

        # [20] Match Features By
        p20 = arcpy.Parameter(
            displayName="Match Features By",
            name="match_method",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
            category="Basic Comparison"
        )
        p20.filter.type = "ValueList"
        p20.filter.list = [_MATCH_BY_SPATIAL, _MATCH_BY_ATTR, _MATCH_BY_ATTR_ALT, _MATCH_BY_OID]
        p20.value       = _MATCH_BY_SPATIAL
        params.append(p20)

        # ============================================================
        # Category: Geometry Comparison (Cont.)
        # ============================================================

        # [21] Area Decimal Places
        p21 = arcpy.Parameter(
            displayName="Area Decimal Places",
            name="area_decimal_places",
            datatype="GPLong",
            parameterType="Optional",
            direction="Input",
            category="Geometry Comparison"
        )
        p21.value = 3
        params.append(p21)

        # [22] Length Decimal Places
        p22 = arcpy.Parameter(
            displayName="Length Decimal Places",
            name="length_decimal_places",
            datatype="GPLong",
            parameterType="Optional",
            direction="Input",
            category="Geometry Comparison"
        )
        p22.value = 3
        params.append(p22)

        # [23] Vertex Count Tolerance
        p23 = arcpy.Parameter(
            displayName="Vertex Count Tolerance",
            name="vertex_count_tolerance",
            datatype="GPLong",
            parameterType="Optional",
            direction="Input",
            category="Geometry Comparison"
        )
        p23.value = 0
        params.append(p23)

        # [24] Spatial Tolerance
        p24 = arcpy.Parameter(
            displayName="Spatial Tolerance (dataset linear units)",
            name="spatial_tolerance",
            datatype="GPDouble",
            parameterType="Optional",
            direction="Input",
            category="Geometry Comparison"
        )
        p24.value = 0.03
        params.append(p24)

        # [25] Compare Spatial Position
        p25 = arcpy.Parameter(
            displayName="Compare Spatial Position",
            name="compare_spatial_position",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input",
            category="Geometry Comparison"
        )
        p25.value = True
        params.append(p25)

        # [26] Compare Vertex Count
        p26 = arcpy.Parameter(
            displayName="Compare Vertex Count",
            name="compare_vertex_count",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input",
            category="Geometry Comparison"
        )
        p26.value = True
        params.append(p26)

        # [27] Compare Geometry Shape
        p27 = arcpy.Parameter(
            displayName="Compare Geometry Shape",
            name="compare_geometry_shape",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input",
            category="Geometry Comparison"
        )
        p27.value = True
        params.append(p27)

        # [28] Compare Z
        p28 = arcpy.Parameter(
            displayName="Compare Z Coordinates",
            name="compare_z",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input",
            category="Geometry Comparison"
        )
        p28.value = False
        params.append(p28)

        # [29] Z Tolerance
        p29 = arcpy.Parameter(
            displayName="Z Tolerance (dataset units)",
            name="z_tolerance",
            datatype="GPDouble",
            parameterType="Optional",
            direction="Input",
            category="Geometry Comparison"
        )
        p29.value = 0.001
        params.append(p29)

        # ============================================================
        # Category: Output / Reports (Cont.)
        # ============================================================

        # [30] Report Output Folder
        p30 = arcpy.Parameter(
            displayName="Report Output Folder (Excel & HTML)",
            name="report_folder",
            datatype="DEFolder",
            parameterType="Optional",
            direction="Input",
            category="Output / Reports"
        )
        try:
            aprx = arcpy.mp.ArcGISProject("CURRENT")
            p30.value = aprx.homeFolder
        except Exception:
            pass
        params.append(p30)

        # ============================================================
        # Category: QC Review / Issue Tracking (New Module)
        # ============================================================

        # [31] Enable QC Review
        p31 = arcpy.Parameter(
            displayName="Enable QC Review / Issue Tracking",
            name="enable_qc_review",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input",
            category="QC Review / Issue Tracking"
        )
        p31.value = False
        params.append(p31)

        # [32] Create QC Issues Feature Class
        p32 = arcpy.Parameter(
            displayName="Create QC Issues Feature Class (Template)",
            name="create_qc_issues",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input",
            category="QC Review / Issue Tracking"
        )
        p32.value = False
        p32.enabled = False
        params.append(p32)

        # [33] Existing QC Issues
        p33 = arcpy.Parameter(
            displayName="Existing QC Issues (Feature Class / Layer)",
            name="existing_qc_issues",
            datatype="GPFeatureLayer",
            parameterType="Optional",
            direction="Input",
            category="QC Review / Issue Tracking"
        )
        p33.enabled = False
        params.append(p33)

        # [34] QC Output Feature Class Name
        p34 = arcpy.Parameter(
            displayName="QC Review Result Feature Class Name",
            name="qc_output_name",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
            category="QC Review / Issue Tracking"
        )
        p34.value = "QC_Review_Result"
        p34.enabled = False
        params.append(p34)

        # ============================================================
        # Category: Basic Comparison (Ambiguity Tie-Break)
        # ============================================================

        # [35] Ambiguity Tolerance
        p35 = arcpy.Parameter(
            displayName="Ambiguity Tolerance (Spatial Join Tie-Break Fraction)",
            name="ambiguity_tolerance",
            datatype="GPDouble",
            parameterType="Optional",
            direction="Input",
            category="Basic Comparison"
        )
        p35.value = 0.02
        params.append(p35)

        # ============================================================
        # Category: Settings & Execution Mode
        # ============================================================

        # [36] Validate Only (Dry-Run Mode)
        p36 = arcpy.Parameter(
            displayName="Validation / Dry-Run Only (No outputs written)",
            name="validate_only",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input",
            category="Settings"
        )
        p36.value = False
        params.append(p36)

        return params

    # ----------------------------------------------------------------
    # updateParameters
    # ----------------------------------------------------------------

    def updateParameters(self, params):
        """
        Dynamic UI behaviour:
        - Enable/disable UID field based on match method.
        - Enable/disable field comparison params based on schema match.
        - Enable/disable geometry comparison params based on feature class geometry type.
        - Enable/disable QC review params based on enable toggle.
        - Show/hide settings file path based on save toggle.
        """
        # Default Output Workspace to default GDB if empty
        if not params[3].value:
            try:
                aprx = arcpy.mp.ArcGISProject("CURRENT")
                params[3].value = aprx.defaultGeodatabase
            except Exception:
                try:
                    params[3].value = arcpy.env.workspace or arcpy.env.scratchGDB
                except Exception:
                    pass

        # Default Report Folder to project home folder if empty
        if len(params) > 30 and not params[30].value:
            try:
                aprx = arcpy.mp.ArcGISProject("CURRENT")
                params[30].value = aprx.homeFolder
            except Exception:
                pass

        match_method = params[20].valueAsText or _MATCH_BY_SPATIAL

        uid_needed = match_method in (_MATCH_BY_ATTR, _MATCH_BY_ATTR_ALT)
        params[2].enabled = uid_needed
        if not uid_needed and not params[2].altered:
            params[2].value = None

        orig_fc = params[0].valueAsText
        mod_fc  = params[1].valueAsText

        geom_type = None
        if orig_fc:
            try:
                if arcpy.Exists(orig_fc):
                    geom_type = _geom_type(orig_fc)
                    sr = _spatial_ref(orig_fc)
                    unit_name = getattr(sr, "linearUnitName", "dataset units") or "dataset units"
                    params[24].displayName = f"Spatial Tolerance ({unit_name})"
            except Exception:
                pass

        if orig_fc and mod_fc:
            try:
                if arcpy.Exists(orig_fc) and arcpy.Exists(mod_fc):
                    same = _schema_matches(orig_fc, mod_fc)
                    if same:
                        params[10].enabled = True
                        params[11].enabled = False
                        if not params[10].altered:
                            names = [f[0] for f in _get_fields(orig_fc)]
                            params[10].value = ";".join(names)
                    else:
                        params[10].enabled = False
                        params[11].enabled = True
                        params[11].filters[0].list = [f[0] for f in _get_fields(orig_fc)]
                        params[11].filters[1].list = [f[0] for f in _get_fields(mod_fc)]
            except Exception:
                pass

        # Advanced geometry parameters dynamic activation
        compare_geom_enabled = bool(params[6].value)
        if not compare_geom_enabled:
            for idx in [7, 21, 22, 23, 24, 25, 26, 27, 28, 29]:
                params[idx].enabled = False
        else:
            params[7].enabled  = True
            params[24].enabled = True  # spatial_tol
            params[25].enabled = True  # compare_spatial

            if geom_type == "Polygon":
                params[21].enabled = True   # area_decimals
                params[22].enabled = False  # length_decimals
                params[23].enabled = True   # vertex_count_tol
                params[26].enabled = True   # compare_vertex_count
                params[27].enabled = True   # compare_shape
                params[28].enabled = False  # compare_z
                params[29].enabled = False  # z_tol
            elif geom_type == "Polyline":
                params[21].enabled = False  # area_decimals
                params[22].enabled = True   # length_decimals
                params[23].enabled = True   # vertex_count_tol
                params[26].enabled = True   # compare_vertex_count
                params[27].enabled = True   # compare_shape
                params[28].enabled = False  # compare_z
                params[29].enabled = False  # z_tol
            elif geom_type == "Point":
                params[21].enabled = False  # area_decimals
                params[22].enabled = False  # length_decimals
                params[23].enabled = False  # vertex_count_tol
                params[26].enabled = False  # compare_vertex_count
                params[27].enabled = False  # compare_shape
                params[28].enabled = True   # compare_z
                params[29].enabled = bool(params[28].value)  # z_tol
            elif geom_type == "Multipoint":
                params[21].enabled = False  # area_decimals
                params[22].enabled = False  # length_decimals
                params[23].enabled = True   # vertex_count_tol
                params[26].enabled = True   # compare_vertex_count
                params[27].enabled = True   # compare_shape
                params[28].enabled = False  # compare_z
                params[29].enabled = False  # z_tol
            else:
                for idx in [21, 22, 23, 26, 27, 28, 29]:
                    params[idx].enabled = True

        params[15].enabled = bool(params[14].value)

        # QC Review parameters dynamic activation
        if len(params) > 31:
            enable_qc = bool(params[31].value)
            params[32].enabled = enable_qc  # create_qc_issues
            params[33].enabled = enable_qc  # existing_qc_issues
            params[34].enabled = enable_qc  # qc_output_name

    # ----------------------------------------------------------------
    # updateMessages
    # ----------------------------------------------------------------

    def updateMessages(self, params):
        """
        Validate geometry type compatibility, tolerance constraints, and QC inputs.
        """
        orig_fc = params[0].valueAsText
        mod_fc  = params[1].valueAsText

        if orig_fc and mod_fc:
            try:
                if arcpy.Exists(orig_fc) and arcpy.Exists(mod_fc):
                    t1 = _geom_type(orig_fc)
                    t2 = _geom_type(mod_fc)
                    if t1 != t2:
                        params[1].setErrorMessage(
                            f"Geometry type mismatch: "
                            f"original is '{t1}', modified is '{t2}'."
                        )
            except Exception:
                pass

        # Output workspace validation constraint (§8)
        out_ws = params[3].valueAsText
        if out_ws:
            ws_clean = str(out_ws).rstrip("\\/").lower()
            if ws_clean.endswith(".shp"):
                params[3].setErrorMessage(
                    "Output workspace must be a File Geodatabase (.gdb) or Enterprise Geodatabase (.sde), never a shapefile."
                )
            elif arcpy.Exists(out_ws):
                try:
                    desc = arcpy.Describe(out_ws)
                    ws_type = getattr(desc, "workspaceType", "")
                    if ws_type not in ("LocalDatabase", "RemoteDatabase") and not ws_clean.endswith((".gdb", ".sde")):
                        params[3].setErrorMessage(
                            "Output workspace must be a File Geodatabase (.gdb) or Enterprise Geodatabase (.sde), never a shapefile folder."
                        )
                except Exception:
                    pass

        match_method = params[20].valueAsText or _MATCH_BY_SPATIAL
        uid          = params[2].valueAsText

        if match_method in (_MATCH_BY_ATTR, _MATCH_BY_ATTR_ALT):
            if orig_fc and uid and arcpy.Exists(orig_fc):
                try:
                    total = int(arcpy.management.GetCount(orig_fc)[0])
                    if 0 < total <= 50000:
                        distinct = len(set(
                            row[0]
                            for row in arcpy.da.SearchCursor(orig_fc, [uid])
                        ))
                        if distinct < total:
                            params[2].setErrorMessage(
                                f"Rule 2 (Unique ID Validation) Violation: UID field '{uid}' has {total - distinct} "
                                f"duplicate value(s) in the original FC. The Unique ID field must contain strictly unique values."
                            )
                except Exception:
                    pass

        elif match_method == _MATCH_BY_OID:
            params[20].setWarningMessage(
                "OBJECTID matching is reliable only when both FCs originate from "
                "the same geodatabase and OIDs have not been reassigned. "
                "For independently exported datasets, use 'By Spatial Location'."
            )

        elif match_method == _MATCH_BY_SPATIAL:
            params[20].setWarningMessage(
                "Spatial matching uses 1-to-1 greedy resolution with tie-breaking by largest overlap / closest distance. "
                "Tied candidates within the ambiguity tolerance are flagged as Ambiguous Matches."
            )

        if len(params) > 35 and params[35].value is not None:
            try:
                at_val = float(params[35].value)
                if at_val < 0.0 or at_val > 1.0:
                    params[35].setErrorMessage("Ambiguity tolerance must be a fraction between 0.0 and 1.0 (default 0.02).")
            except Exception:
                pass

        # Validate numeric parameters (>= 0)
        try:
            if params[7].value is not None and float(params[7].value) < 0:
                params[7].setErrorMessage("General Geometry Tolerance must be >= 0.")
            if params[21].value is not None and int(params[21].value) < 0:
                params[21].setErrorMessage("Area Decimal Places must be >= 0.")
            if params[22].value is not None and int(params[22].value) < 0:
                params[22].setErrorMessage("Length Decimal Places must be >= 0.")
            if params[23].value is not None and int(params[23].value) < 0:
                params[23].setErrorMessage("Vertex Count Tolerance must be >= 0.")
            if params[24].value is not None and float(params[24].value) < 0:
                params[24].setErrorMessage("Spatial Tolerance must be >= 0.")
            if params[29].value is not None and float(params[29].value) < 0:
                params[29].setErrorMessage("Z Tolerance must be >= 0.")
        except Exception:
            pass

        # Validate QC Review parameters
        if len(params) > 31 and bool(params[31].value):
            create_qc   = bool(params[32].value)
            existing_qc = params[33].valueAsText

            if not create_qc and not existing_qc:
                params[31].setWarningMessage(
                    "QC Review is enabled. Either check 'Create QC Issues Feature Class' to generate a template, "
                    "or specify an 'Existing QC Issues' dataset to correlate."
                )

            if existing_qc:
                try:
                    if arcpy.Exists(existing_qc):
                        q_type = _geom_type(existing_qc)
                        if q_type != "Point":
                            params[33].setErrorMessage(
                                f"QC Issues dataset must be a Point Feature Class (found '{q_type}')."
                            )
                except Exception:
                    pass

    # ----------------------------------------------------------------
    # execute
    # ----------------------------------------------------------------

    def execute(self, parameters, messages):
        try:
            orig_fc        = parameters[0].valueAsText
            mod_fc         = parameters[1].valueAsText
            uid_field      = parameters[2].valueAsText or ""
            out_ws         = parameters[3].valueAsText
            out_name       = (parameters[4].valueAsText or "ChangeDetection_Result").strip()
            match_method   = parameters[20].valueAsText or _MATCH_BY_SPATIAL

            def _bool(p, default=False):
                return p.value if p.value is not None else default

            def _int(p, default=0):
                return int(p.value) if p.value is not None else default

            def _float(p, default=0.0):
                return float(p.value) if p.value is not None else default

            compare_attrs        = _bool(parameters[5],  True)
            compare_geom         = _bool(parameters[6],  True)
            geom_tol             = _float(parameters[7], 0.0)
            ignore_case          = _bool(parameters[8],  False)
            null_empty_eq        = _bool(parameters[9],  False)
            export_added         = _bool(parameters[12], False)
            export_deleted       = _bool(parameters[13], False)
            save_settings        = _bool(parameters[14], False)
            settings_file        = parameters[15].valueAsText
            add_to_map           = _bool(parameters[19], True)
            gen_html             = _bool(parameters[18], True)
            report_folder        = parameters[30].valueAsText if len(parameters) > 30 else None

            area_decimals        = _int(parameters[21], 3)
            length_decimals      = _int(parameters[22], 3)
            vertex_count_tol     = _int(parameters[23], 0)
            spatial_tol          = _float(parameters[24], 0.03)
            compare_spatial      = _bool(parameters[25], True)
            compare_vertex_count = _bool(parameters[26], True)
            compare_shape        = _bool(parameters[27], True)
            compare_z            = _bool(parameters[28], False)
            z_tol                = _float(parameters[29], 0.001)

            # QC Parameters
            enable_qc_review     = _bool(parameters[31], False) if len(parameters) > 31 else False
            create_qc_issues     = _bool(parameters[32], False) if len(parameters) > 32 else False
            existing_qc_issues   = parameters[33].valueAsText if len(parameters) > 33 else None
            qc_output_name       = (parameters[34].valueAsText or "QC_Review_Result").strip() if len(parameters) > 34 else "QC_Review_Result"

            # v5.0 Parameters
            ambiguity_tol        = _float(parameters[35], 0.02) if len(parameters) > 35 else 0.02
            validate_only        = _bool(parameters[36], False) if len(parameters) > 36 else False

            filter_raw   = parameters[17].valueAsText or ""
            filter_types = [
                t.strip().strip("'\"")
                for t in filter_raw.split(";") if t.strip()
            ] if filter_raw else []

            # Load settings from JSON (optional override)
            load_file    = parameters[16].valueAsText
            loaded_pairs = []
            if load_file and os.path.isfile(load_file):
                try:
                    with open(load_file, "r", encoding="utf-8") as jf:
                        saved = json.load(jf)
                    messages.addMessage(f"Settings loaded from: {load_file}")
                    orig_fc              = saved.get("orig_fc",                  orig_fc)
                    mod_fc               = saved.get("mod_fc",                   mod_fc)
                    uid_field            = saved.get("uid_field",                uid_field)
                    match_method         = saved.get("match_method",             match_method)
                    ambiguity_tol        = float(saved.get("ambiguity_tolerance", ambiguity_tol))
                    compare_attrs        = saved.get("compare_attrs",            compare_attrs)
                    compare_geom         = saved.get("compare_geom",             compare_geom)
                    geom_tol             = float(saved.get("geom_tol",           geom_tol))
                    ignore_case          = saved.get("ignore_case",              ignore_case)
                    null_empty_eq        = saved.get("null_empty_eq",            null_empty_eq)
                    loaded_pairs         = saved.get("field_pairs",              [])
                    area_decimals        = int(saved.get("area_decimal_places",  area_decimals))
                    length_decimals      = int(saved.get("length_decimal_places",length_decimals))
                    vertex_count_tol     = int(saved.get("vertex_count_tolerance",vertex_count_tol))
                    spatial_tol          = float(saved.get("spatial_tolerance",  spatial_tol))
                    compare_spatial      = bool(saved.get("compare_spatial_position", compare_spatial))
                    compare_vertex_count = bool(saved.get("compare_vertex_count",compare_vertex_count))
                    compare_shape        = bool(saved.get("compare_geometry_shape",compare_shape))
                    compare_z            = bool(saved.get("compare_z",           compare_z))
                    z_tol                = float(saved.get("z_tolerance",        z_tol))
                    report_folder        = saved.get("report_folder",            report_folder)

                    if "qc_review" in saved:
                        qc_saved = saved["qc_review"]
                        enable_qc_review   = bool(qc_saved.get("enabled", enable_qc_review))
                        create_qc_issues   = bool(qc_saved.get("create_qc_issues", create_qc_issues))
                        existing_qc_issues = qc_saved.get("existing_qc_issues", existing_qc_issues)
                        qc_output_name     = qc_saved.get("qc_output", qc_output_name)

                except Exception as ex:
                    messages.addWarning(f"Could not load settings: {ex}")

            # Validate UID field requirement
            if match_method in (_MATCH_BY_ATTR, _MATCH_BY_ATTR_ALT) and not uid_field:
                raise ValueError(
                    f"A Unique ID Field is required when Match Method is '{match_method}'. "
                    f"Select a unique ID field, or change Match Method to "
                    f"'{_MATCH_BY_OID}' or '{_MATCH_BY_SPATIAL}'."
                )

            # Resolve field pairs
            same_schema = _schema_matches(orig_fc, mod_fc)
            field_pairs = []

            if loaded_pairs:
                field_pairs = [tuple(p) for p in loaded_pairs]
            elif same_schema:
                selected_raw = parameters[10].valueAsText or ""
                if selected_raw:
                    for tok in selected_raw.split(";"):
                        fn = tok.strip().strip("'\"")
                        if fn:
                            field_pairs.append((fn, fn))
                if not field_pairs:
                    field_pairs = [(f[0], f[0]) for f in _get_fields(orig_fc)]
            else:
                vt = parameters[11].value
                if vt:
                    for row in vt:
                        of = str(row[0]).strip() if row[0] else ""
                        mf = str(row[1]).strip() if row[1] else ""
                        cas = str(row[2]).strip().lower() if len(row) > 2 and row[2] else None
                        if of and mf:
                            field_pairs.append((of, mf, cas))

            # Validate field pairs against actual fields
            if field_pairs:
                orig_fnames = {f.name for f in arcpy.ListFields(orig_fc)}
                mod_fnames  = {f.name for f in arcpy.ListFields(mod_fc)}
                for item in field_pairs:
                    of, mf = item[0], item[1]
                    if of not in orig_fnames:
                        raise ValueError(f"Field '{of}' not found in original FC.")
                    if mf not in mod_fnames:
                        raise ValueError(f"Field '{mf}' not found in modified FC.")

            # Validate output workspace
            if not arcpy.Exists(out_ws):
                raise ValueError(f"Output workspace not found: {out_ws}")
            if not out_name:
                raise ValueError("Output Feature Class Name cannot be empty.")

            messages.addMessage(f"Match method    : {match_method}")
            messages.addMessage(f"Field pairs     : {len(field_pairs)} field(s) to compare")
            if field_pairs:
                for item in field_pairs[:5]:
                    of, mf = item[0], item[1]
                    cas = item[2] if len(item) > 2 and item[2] else None
                    cas_str = f" [compare as {cas}]" if cas else ""
                    messages.addMessage(f"  {of} -> {mf}{cas_str}" if of != mf else f"  {of}{cas_str}")
                if len(field_pairs) > 5:
                    messages.addMessage(f"  … and {len(field_pairs)-5} more.")

            # Run the engine
            engine = ChangeEngine({
                "orig_fc":              orig_fc,
                "mod_fc":               mod_fc,
                "uid_field":            uid_field,
                "out_ws":               out_ws,
                "out_name":             out_name,
                "compare_attrs":        compare_attrs,
                "compare_geom":         compare_geom,
                "geom_tol":             geom_tol,
                "ignore_case":          ignore_case,
                "null_empty_eq":        null_empty_eq,
                "field_pairs":          field_pairs,
                "same_schema":          same_schema,
                "export_added":         export_added,
                "export_deleted":       export_deleted,
                "save_settings":        save_settings,
                "settings_file":        settings_file,
                "filter_types":         filter_types,
                "gen_html":             gen_html,
                "match_method":         match_method,
                "area_decimals":        area_decimals,
                "length_decimals":      length_decimals,
                "vertex_count_tol":     vertex_count_tol,
                "spatial_tol":          spatial_tol,
                "compare_spatial":      compare_spatial,
                "compare_vertex_count": compare_vertex_count,
                "compare_shape":        compare_shape,
                "compare_z":            compare_z,
                "z_tol":                z_tol,
                "report_folder":        report_folder,
                "enable_qc_review":     enable_qc_review,
                "create_qc_issues":     create_qc_issues,
                "existing_qc_issues":   existing_qc_issues,
                "qc_output_name":       qc_output_name,
                "ambiguity_tolerance":  ambiguity_tol,
                "validate_only":        validate_only,
            }, messages)

            out_fc, excel_path, html_path, qc_review_fc = engine.run()

            if validate_only:
                messages.addMessage("-" * 60)
                messages.addMessage("[OK] Dry-run schema validation completed successfully.")
                messages.addMessage("-" * 60)
                return

            self._out_fc       = out_fc
            self._qc_review_fc = qc_review_fc
            self._add_to_map   = add_to_map

            messages.addMessage("-" * 60)
            messages.addMessage("[OK] Change detection completed successfully.")
            messages.addMessage(f"   Output FC    : {out_fc}")
            if qc_review_fc:
                messages.addMessage(f"   QC Result FC : {qc_review_fc}")
            messages.addMessage(f"   Excel report : {excel_path}")
            if html_path:
                messages.addMessage(f"   HTML report  : {html_path}")
            messages.addMessage("-" * 60)

        except Exception as ex:
            messages.addErrorMessage(str(ex))
            messages.addErrorMessage(traceback.format_exc())
            raise

    # ----------------------------------------------------------------
    # postExecute
    # ----------------------------------------------------------------

    def postExecute(self, parameters):
        """
        Add output FCs to the active map with unique-values symbology:
        1. Result FC colored by Change_Type.
        2. QC Review Result FC colored by QC_Assessment_Desc.
        """
        try:
            if not getattr(self, "_add_to_map", True):
                return

            out_fc = getattr(self, "_out_fc", None)
            if not out_fc or not arcpy.Exists(out_fc):
                return

            aprx    = arcpy.mp.ArcGISProject("CURRENT")
            map_obj = aprx.activeMap
            if map_obj is None:
                return

            # 1. Add Main Output FC
            out_fc = getattr(self, "_out_fc", None)
            if out_fc and arcpy.Exists(out_fc):
                fc_name = os.path.splitext(os.path.basename(out_fc))[0]
                for lyr in map_obj.listLayers(fc_name):
                    try:
                        map_obj.removeLayer(lyr)
                    except Exception:
                        pass

                added_lyr = map_obj.addDataFromPath(out_fc)
                if added_lyr is not None:
                    try:
                        sym = added_lyr.symbology
                        if hasattr(sym, "renderer"):
                            sym.updateRenderer("UniqueValueRenderer")
                            sym.renderer.fields = ["Change_Type"]
                            added_lyr.symbology = sym
                    except Exception:
                        pass

            # 2. Add QC Review Result FC
            qc_fc = getattr(self, "_qc_review_fc", None)
            if qc_fc and arcpy.Exists(qc_fc):
                qc_name = os.path.splitext(os.path.basename(qc_fc))[0]
                for lyr in map_obj.listLayers(qc_name):
                    try:
                        map_obj.removeLayer(lyr)
                    except Exception:
                        pass

                qc_lyr = map_obj.addDataFromPath(qc_fc)
                if qc_lyr is not None:
                    try:
                        sym = qc_lyr.symbology
                        if hasattr(sym, "renderer"):
                            sym.updateRenderer("UniqueValueRenderer")
                            sym.renderer.fields = ["QC_Assessment_Desc"]
                            qc_lyr.symbology = sym
                    except Exception:
                        pass

        except Exception:
            pass

# ---------------------------------------------------------------------------
# End of FeatureClassChangeDetection.pyt
# ---------------------------------------------------------------------------
