# 🌍 Geo Change Detection & QC Review Tool
### راصد التغيرات الجغرافية ومراجعة الجودة — ArcGIS Pro Python Toolbox (v5.0.0 Refined)

> **Enterprise ArcGIS Pro Python Toolbox for multi-level spatial change detection, QC issue auditing, and interactive dashboard reporting.**

---

### 📚 Documentation & Quick Links:
* 📖 **[User Guide (دليل المستخدم الشامل باللغة العربية)](USER_GUIDE.md)** — خطوات التثبيت والتشغيل بالتفصيل مع الأمثلة.
* ⚙️ **[Parameters Reference (دليل المعاملات الـ 37)](TOOL_PARAMETERS_GUIDE_AR.md)** — شرح تفصيلي لكل معامل وأثره وقيمه الافتراضية.
* 📋 **[Prompt & System Specification](prompts/MASTER_PROMPT.md)** — المواصفات المعمارية والبرمجية الكاملة للأداة.

---

## Overview

A production-grade, enterprise-ready ArcGIS Pro Python Toolbox (`.pyt`) designed for spatial and tabular comparison between an **Original Feature Class** ("Before" state) and a **Modified Feature Class** ("After" state). The tool identifies:

1. **Geometry Modifications** (Area, Length, Vertex Count, Spatial Centroid/Endpoint Movement, Topological Shape Differences, 3D Z coordinates)
2. **Attribute Edits** (Case sensitivity, NULL vs empty string handling, explicit 3-column field mappings with type coercion)
3. **Added Features** (Present in Modified, absent in Original)
4. **Deleted Features** (Present in Original, absent in Modified)
5. **QC Review & Issue Tracking** (Correlation module linking historical QA notes to detected changes)

> [!IMPORTANT]
> **Strict Non-Resolution Policy (قاعدة عدم افتراض الحل الصارمة):**
> The tool **never** automatically classifies any QC issue as `Resolved` or `Potentially Resolved`.
> The strongest automated indicator is strictly **`Maybe Changed` (QA-1)** (*احتمالية أنها عُدّلت*), preserving human reviewer authority for final issue closure.

---

## What's New in v5.0.0 (Refined Architecture)

| # | Feature / Rule | Specification & Implementation |
|---|---|---|
| 1 | **Rule 2: Unique ID Validation** | Validates that `uid_field` has strictly unique values in both Original and Modified before execution. Aborts immediately with a descriptive error listing the duplicate IDs if detected. |
| 2 | **Rule 5: Coordinate System Consistency** | Automatically verifies CRS compatibility. If coordinate systems differ or use geographic degrees, projects features on-the-fly into a common projected coordinate system for linear metric calculations and logs the reprojection. |
| 3 | **Rule 6 & Method B: Spatial Join with Ambiguity** | Global 1-to-1 greedy matching with deterministic tie-breaking (largest overlap area / shortest distance). Candidates tied within `ambiguity_tolerance` are flagged as `"Ambiguous Match — Manual Review Required"`. |
| 4 | **Rebuilt QC Decision Matrix (30 Combinations)** | Fully separated namespaces (`IT-1`..`IT-5` for Issue Types, `QA-1`..`QA-5` for QC Assessments), override rule for missing IDs (`QA-4`), and ambiguous match bypass. |
| 5 | **Output Workspace Constraint** | Output workspace **must** be a File Geodatabase (`.gdb`) or Enterprise Geodatabase (`.sde`). Shapefile workspaces and directories are strictly rejected to prevent 10-character field truncation. |
| 6 | **Compact JSON Output** | `Old_Values` and `New_Values` are serialized as compact, machine-parseable JSON strings (`{"FIELD":"val"}`) with zero extraneous whitespace. |
| 7 | **Validation / Dry-Run Mode** | Added `validate_only` boolean parameter to run pre-flight schema, CRS, Unique ID, and workspace validations without writing any feature classes or reports to disk. |
| 8 | **Execution Audit Run Log** | Automatically generates a timestamped execution audit run log (`{out_name}_{run_id}_audit.log`) capturing run parameters, row counts, reprojections, type mismatches, and elapsed runtime. |
| 9 | **3-Column Field Mapping** | Schema differences support `Orig_Field`, `Mod_Field`, and explicit `Compare_As` coercion (`text`, `numeric`, `date`) with automated `Field_Type_Mismatch` warnings. |
| 10 | **Versioned Settings Schema** | Versioned JSON settings persistence (`"schema_version": "5.0"`) with full backward compatibility for older configuration files. |
| 11 | **Strict Read-Only Guarantee** | Inputs (`orig_fc` and `mod_fc`) are strictly read-only (`arcpy.da.SearchCursor` only). Source data and schemas are 100% unaltered. Intermediate layers use temporary `memory\` and are automatically purged. |
| 12 | **Hardened Schema & Messaging Engine** | Normalized ArcGIS Pro messaging via `MessageWrapper` preventing `MessagesObject` attribute errors. Result schema expanded (`Geometry_Changed`, `Attributes_Changed`, `Spatially_Changed`, etc. to `TEXT(20)`, and `Geometry_Change_Reason` to `TEXT(500)`) preventing field length overflows on `"Ambiguous"` spatial matches. |

---

## Requirements

| Requirement | Details |
|---|---|
| **ArcGIS Pro** | **3.x or later** |
| **Python** | **Python 3.9+** (bundled with ArcGIS Pro) |
| **openpyxl** | `pip install openpyxl` (included with standard Pro environment; required for Excel) |
| **License** | ArcGIS Pro Basic, Standard, or Advanced |

---

## Tool Parameters Reference

Parameters are organized into 6 logical categories in ArcGIS Pro:

### 1. Basic Comparison
| # | Parameter | Type | Required | Default | Description |
|---|---|---|---|---|---|
| 0 | `orig_fc` | GPFeatureLayer | ✅ | — | Original Feature Class / Layer ("Before" state) |
| 1 | `mod_fc` | GPFeatureLayer | ✅ | — | Modified Feature Class / Layer ("After" state) |
| 20 | `match_method` | GPString | ✅ | `By Spatial Location (Spatial Join)` | `By Spatial Location (Spatial Join)`, `By Attribute ID Field`, `By Unique ID`, `By OBJECTID (Automatic)` |
| 2 | `uid_field` | Field | Optional | — | Unique ID field (strictly enforced unique per Rule 2) |
| 3 | `out_ws` | DEWorkspace | ✅ | *Default GDB* | Output workspace (**must be .gdb or .sde**) |
| 4 | `out_name` | GPString | ✅ | `ChangeDetection_Result` | Name of output result Feature Class |
| 35 | `ambiguity_tolerance` | GPDouble | Optional | `0.02` | Spatial join tie-breaking tolerance fraction (0.0 to 1.0) |

### 2. Attribute Comparison
| # | Parameter | Type | Required | Default | Description |
|---|---|---|---|---|---|
| 5 | `compare_attrs` | GPBoolean | Optional | `True` | Compare non-geometry attributes |
| 8 | `ignore_case` | GPBoolean | Optional | `False` | Case-insensitive text comparison |
| 9 | `null_empty_eq` | GPBoolean | Optional | `False` | Treat `NULL` and `""` as equal |
| 10 | `compare_fields` | GPMultiValue:Field | Optional | All common | Compared fields (defaults to all common non-system fields) |
| 11 | `field_mapping` | GPValueTable | Optional | — | 3-column table: `Orig_Field`, `Mod_Field`, `Compare_As` |

### 3. Geometry Comparison
| # | Parameter | Type | Required | Default | Description |
|---|---|---|---|---|---|
| 6 | `compare_geom` | GPBoolean | Optional | `True` | Enable advanced geometry comparison engine |
| 7 | `geom_tol` | GPDouble | Optional | `0.0` | Legacy delta floor (dataset units) |
| 21 | `area_decimal_places` | GPLong | Optional | `3` | Decimal precision for Polygon area comparison |
| 22 | `length_decimal_places` | GPLong | Optional | `3` | Decimal precision for Polyline length comparison |
| 23 | `vertex_count_tolerance`| GPLong | Optional | `0` | Vertex count difference threshold |
| 24 | `spatial_tolerance` | GPDouble | Optional | `0.3` | Maximum centroid/endpoint displacement (linear units) |
| 25 | `compare_spatial_position`| GPBoolean | Optional | `True` | Compare centroid / endpoint movement |
| 26 | `compare_vertex_count` | GPBoolean | Optional | `True` | Compare vertex count vs tolerance |
| 27 | `compare_geometry_shape` | GPBoolean | Optional | `True` | Compare topological shape & vertex deviation |
| 28 | `compare_z` | GPBoolean | Optional | `False` | Compare 3D Z coordinates |
| 29 | `z_tolerance` | GPDouble | Optional | `0.001` | Vertical Z difference threshold |

### 4. QC Review & Issue Tracking
| # | Parameter | Type | Required | Default | Description |
|---|---|---|---|---|---|
| 31 | `enable_qc_review` | GPBoolean | Optional | `False` | Enable QC Review correlation module |
| 32 | `create_qc_issues` | GPBoolean | Optional | `False` | Create empty `QC_Issues` Point FC template |
| 33 | `existing_qc_issues` | GPFeatureLayer | Optional | — | Input Point FC with historical QC notes |
| 34 | `qc_output_name` | GPString | Optional | `QC_Review_Result` | Name of output QC Point FC |

### 5. Output / Reports
| # | Parameter | Type | Required | Default | Description |
|---|---|---|---|---|---|
| 30 | `report_folder` | DEFolder | Optional | *Project Home* | Destination directory for Excel, HTML, and Log reports |
| 18 | `gen_html` | GPBoolean | Optional | `True` | Generate standalone interactive HTML dashboard |
| 12 | `export_added` | GPBoolean | Optional | `False` | Export added features as separate FC |
| 13 | `export_deleted` | GPBoolean | Optional | `False` | Export deleted features as separate FC |
| 17 | `filter_change_types` | GPMultiValue:String| Optional | All | Filter features written to output FC |
| 19 | `add_to_map` | GPBoolean | Optional | `True` | Add result layers to active map with symbology |

### 6. Settings & Execution Mode
| # | Parameter | Type | Required | Default | Description |
|---|---|---|---|---|---|
| 14 | `save_settings` | GPBoolean | Optional | `False` | Export run configuration to JSON |
| 15 | `settings_file_out` | DEFile | Optional | — | Destination JSON path |
| 16 | `load_settings_file` | DEFile | Optional | — | Load configuration from JSON |
| 36 | `validate_only` | GPBoolean | Optional | `False` | **Dry-Run Mode**: Validate schema without writing outputs |

---

## QC Review Decision Matrix (v5.0 Rebuilt)

The correlation engine uses two completely separate namespaces:
- **Issue Type Codes:** `IT-1` Geometry Issue · `IT-2` Attribute Issue · `IT-3` Geometry & Attribute Issue · `IT-4` Missing Feature · `IT-5` Extra Feature
- **QC Assessment Codes:** `QA-1` Maybe Changed · `QA-2` Not Changed · `QA-3` Needs Review · `QA-4` Feature Not Found · `QA-5` Feature Deleted

### Override Rule
If `Feature_ID` cannot be located in **either** Original or Modified dataset → **`QA-4 Feature Not Found`**, regardless of `Issue_Type`.

### Matrix Table (All 30 Combinations Defined)
| Issue Type | Detected Change Type | Assessment Code | Assessment Description |
|---|---|:---:|---|
| **IT-1 Geometry Issue** | Unchanged | **QA-2** | Not Changed |
| **IT-1 Geometry Issue** | Geometry Changed | **QA-1** | Maybe Changed |
| **IT-1 Geometry Issue** | Attribute Changed | **QA-3** | Needs Review |
| **IT-1 Geometry Issue** | Geometry and Attribute Changed | **QA-1** | Maybe Changed |
| **IT-1 Geometry Issue** | Added | **QA-3** | Needs Review |
| **IT-1 Geometry Issue** | Deleted | **QA-5** | Feature Deleted |
| **IT-2 Attribute Issue** | Unchanged | **QA-2** | Not Changed |
| **IT-2 Attribute Issue** | Attribute Changed | **QA-1** | Maybe Changed |
| **IT-2 Attribute Issue** | Geometry Changed | **QA-3** | Needs Review |
| **IT-2 Attribute Issue** | Geometry and Attribute Changed | **QA-1** | Maybe Changed |
| **IT-2 Attribute Issue** | Added | **QA-3** | Needs Review |
| **IT-2 Attribute Issue** | Deleted | **QA-5** | Feature Deleted |
| **IT-3 Geometry & Attr Issue** | Unchanged | **QA-2** | Not Changed |
| **IT-3 Geometry & Attr Issue** | Geometry Changed | **QA-1** | Maybe Changed |
| **IT-3 Geometry & Attr Issue** | Attribute Changed | **QA-1** | Maybe Changed |
| **IT-3 Geometry & Attr Issue** | Geometry and Attribute Changed | **QA-1** | Maybe Changed |
| **IT-3 Geometry & Attr Issue** | Added | **QA-3** | Needs Review |
| **IT-3 Geometry & Attr Issue** | Deleted | **QA-5** | Feature Deleted |
| **IT-4 Missing Feature** | Unchanged | **QA-3** | Needs Review |
| **IT-4 Missing Feature** | Added | **QA-1** | Maybe Changed |
| **IT-4 Missing Feature** | Geometry Changed | **QA-3** | Needs Review |
| **IT-4 Missing Feature** | Attribute Changed | **QA-3** | Needs Review |
| **IT-4 Missing Feature** | Geometry and Attribute Changed | **QA-3** | Needs Review |
| **IT-4 Missing Feature** | Deleted | **QA-3** | Needs Review |
| **IT-5 Extra Feature** | Deleted | **QA-1** | Maybe Changed |
| **IT-5 Extra Feature** | Unchanged | **QA-3** | Needs Review |
| **IT-5 Extra Feature** | Geometry Changed | **QA-3** | Needs Review |
| **IT-5 Extra Feature** | Attribute Changed | **QA-3** | Needs Review |
| **IT-5 Extra Feature** | Geometry and Attribute Changed | **QA-3** | Needs Review |
| **IT-5 Extra Feature** | Added | **QA-3** | Needs Review |

*(Ambiguous spatial matches bypass this table entirely and are reported as `"Ambiguous Match — Manual Review Required"`.)*

---

## Deliverables & Outputs

1. **Change Detection Feature Class (`ChangeDetection_Result`)**: Full inventory of compared features with `Change_Type`, explicit `Geometry_Change_Reason` (`TEXT 500`), change flag indicators (`Geometry_Changed`, `Attributes_Changed`, `Spatially_Changed`, `Shape_Changed`, `Area_Changed`, `Length_Changed`, `Vertex_Count_Changed` as `TEXT 20` supporting values like `"Ambiguous"`, `"Yes"`, `"No"`), metric deltas, and compact JSON `Old_Values` / `New_Values`.
2. **QC Review Result Feature Class (`QC_Review_Result`)**: Point feature class containing reviewer notes preserved verbatim, `QC_Assessment` (`QA-1`..`QA-5`), `Distance_To_Current_Feature`, `Review_Run_ID`, and `Review_Date`.
3. **Multi-Sheet Excel Report (5 Sheets)**:
   - `Summary`: Executive metrics, geometry reason breakdown, and QC KPI summary.
   - `Detailed Report`: Full feature inventory with metric deltas.
   - `Geometry Changes`: Filtered spatial/shape modifications.
   - `Attribute Changes`: Flattened field audit log.
   - `QC Review`: Color-coded evaluation table with QA codes.
4. **Interactive HTML Dashboard**: Standalone, responsive, zero external runtime dependencies. Features live KPI cards, search bar, and category filters.
5. **Execution Audit Run Log (`{out_name}_{run_id}_audit.log`)**: Text audit trail capturing parameter configuration, Rule 5 reprojections, row counts, field type mismatches, and elapsed execution time.

---

## Versioned Settings Schema (v5.0)

```json
{
  "schema_version": "5.0",
  "orig_fc": "Parcels_Before",
  "mod_fc": "Parcels_After",
  "uid_field": "PARCEL_ID",
  "match_method": "By Attribute ID Field",
  "ambiguity_tolerance": 0.02,
  "compare_attrs": true,
  "compare_geom": true,
  "geom_tol": 0.0,
  "ignore_case": false,
  "null_empty_eq": false,
  "field_pairs": [
    ["LANDUSE", "LANDUSE"],
    ["VALUE", "VALUE"]
  ],
  "area_decimal_places": 3,
  "length_decimal_places": 3,
  "vertex_count_tolerance": 0,
  "spatial_tolerance": 0.3,
  "compare_spatial_position": true,
  "compare_vertex_count": true,
  "compare_geometry_shape": true,
  "compare_z": false,
  "z_tolerance": 0.001,
  "report_folder": "C:\\Reports",
  "qc_review": {
    "enabled": true,
    "create_qc_issues": false,
    "existing_qc_issues": "C:\\Data\\QC_Issues.shp",
    "qc_output": "QC_Review_Result"
  }
}
```
