# دليل تشغيل واستخدام أداة Geo Change Detection — راصد التغيرات الجغرافية (الإصدار v5.0.0 Refined)

أداة متقدمة لمقارنة وتتبع التغييرات المكانية (الهندسية) والوصفية بين طبقتين جغرافيتين في **ArcGIS Pro**، مع محرك مقارنة هندسي متعدد المستويات، ونظام متكامل اختياري لـ **مراجعة الجودة وتتبع الملاحظات (QC Review & Issue Tracking)**، وتقارير تفاعلية شاملة (HTML Dashboard & Excel 5 Sheets).

> 📘 **مرجع المعاملات الشامل:** للاطلاع على شرح تفصيلي ومحدد لكل معامل من المعاملات الـ 37 وفائدته وأثره وسيناريوهات استخدامه، راجع ملف: [TOOL_PARAMETERS_GUIDE_AR.md](file:///d:/Learning/RER/main/Compeare%20FeatureClassChangeDetection/TOOL_PARAMETERS_GUIDE_AR.md).

---

## 📑 الفهرس
1. [متطلبات التشغيل](#-متطلبات-التشغيل)
2. [كيفية إضافة الأداة في ArcGIS Pro](#-كيفية-إضافة-الأداة-في-arcgis-pro)
3. [دليل التشغيل السريع (Quick Start)](#-دليل-التشغيل-السريع-quick-start)
4. [شرح إعدادات ومجموعات الأداة بالتفصيل](#-شرح-إعدادات-ومجموعات-الأداة-بالتفصيل)
   - [1. المقارنة الأساسية (Basic Comparison)](#1-المقارنة-الأساسية-basic-comparison)
   - [2. مقارنة البيانات الوصفية (Attribute Comparison)](#2-مقارنة-البيانات-الوصفية-attribute-comparison)
   - [3. المقارنة المكانية المتقدمة (Geometry Comparison)](#3-المقارنة-المكانية-المتقدمة-geometry-comparison)
   - [4. مراجعة الجودة وتتبع الملاحظات (QC Review & Issue Tracking)](#4-مراجعة-الجودة-وتتبع-الملاحظات-qc-review--issue-tracking)
   - [5. المخرجات والتقارير (Output / Reports)](#5-المخرجات-والتقارير-output--reports)
   - [6. الإعدادات المحفوظة (Settings)](#6-الإعدادات-المحفوظة-settings)
5. [منظومة مراجعة الجودة (QC Review & Issue Tracking)](#-منظومة-مراجعة-الجودة-qc-review--issue-tracking)
   - [سير العمل (QC Workflow)](#سير-العمل-qc-workflow)
   - [فلسفة التقييم ومصطلح Maybe Changed](#فلسفة-التقييم-ومصطلح-maybe-changed)
   - [مصفوفة اتخاذ القرار للـ QC](#مصفوفة-اتخاذ-القرار-للـ-qc)
   - [هيكل طبقة QC_Issues والـ Domains](#هيكل-طبقة-qc_issues-والـ-domains)
   - [طبقة نتائج المراجعة QC_Review_Result](#طبقة-نتائج-المراجعة-qc_review_result)
6. [شرح المخرجات والنتائج](#-شرح-المخرجات-والنتائج)
   - [طبقة نتائج المقارنة (Output Feature Class)](#طبقة-نتائج-المقارنة-output-feature-class)
   - [تقرير الإكسل (Excel 5-Sheet Report)](#تقرير-الإكسل-excel-5-sheet-report)
   - [لوحة تقرير HTML التفاعلية المباشرة](#لوحة-تقرير-html-التفاعلية-المباشرة)
7. [حفظ واسترجاع الإعدادات (Settings JSON)](#-حفظ-واسترجاع-الإعدادات-settings-json)
8. [التشغيل عبر سكريبت بايثون (Python Scripting / Standalone)](#-التشغيل-عبر-سكريبت-بايثون-python-scripting--standalone)

---

## 💻 متطلبات التشغيل
- **ArcGIS Pro**: الإصدار 3.0 أو أحدث (تم اختباره بنجاح على 3.4+).
- **Python**: البيئة الافتراضية المدمجة مع ArcGIS Pro (`arcgispro-py3`).
- **المكتبات**: `arcpy` و `openpyxl` (تأتي افتراضيًا مع ArcGIS Pro).

---

## 🛠 كيفية إضافة الأداة في ArcGIS Pro

1. افتح مشروعك في **ArcGIS Pro**.
2. من الشريط الجانبي، افتح لوحة **Catalog Pane** (`View` -> `Catalog Pane`).
3. انقر بزر الفأرة الأيمن على **Toolboxes** واختر **Add Toolbox**.
4. استعرض المجلد وحدد الملف:
   ```
   GeoChangeDetection.pyt
   ```
5. ستظهر الأداة باسم **Geo Change Detection** داخل الـ Toolbox.
6. انقر نقرًا مزدوجًا على الأداة لفتح واجهة المستخدم الرسومية (Geoprocessing Tool).

---

## 🚀 دليل التشغيل السريع (Quick Start)

### السيناريو 1: مقارنة طبقتين (Change Detection فقط)
1. **Original Feature Class / Layer**: اختر طبقة الأساس (الحالة السابقة / Master Layer).
2. **Modified Feature Class / Layer**: اختر الطبقة المعدلة (الحالة الحالية / Drawing Layer).
3. **Output Workspace**: يتم ملؤه افتراضيًا بقاعدة بيانات المشروع (`Default.gdb`).
4. **Match Features By**: محدد افتراضيًا على `By Spatial Location (Spatial Join)` أو اختر `By Attribute ID Field`.
5. انقر على **Run**.

### السيناريو 2: مقارنة البيانات مع التحقق من ملاحظات الـ QC القديمة
1. اتبع نفس خطوات السيناريو 1 أعلاه.
2. افتح مجموعة **QC Review / Issue Tracking**.
3. فعّل خيار **Enable QC Review / Issue Tracking**.
4. حدد طبقة الملاحظات في خانة **Existing QC Issues** (أو فعّل **Create QC Issues Feature Class** إذا أردت إنشاء قالب جديد فارغ).
5. انقر على **Run**.

---

## ⚙ شرح إعدادات ومجموعات الأداة بالتفصيل

تم تنظيم معاملات الأداة في 6 مجموعات منطقية قابلة للطي:

```
┌────────────────────────────────────────────────────────┐
│ ▼ Basic Comparison                                    │
│ ▼ Attribute Comparison                                │
│ ▼ Geometry Comparison                                 │
│ ▼ QC Review / Issue Tracking                          │
│ ▼ Output / Reports                                    │
│ ▼ Settings                                            │
└────────────────────────────────────────────────────────┘
```

---

### 1. المقارنة الأساسية (Basic Comparison)

| المعامل | الوصف | القيمة الافتراضية |
|---|---|---|
| **Original Feature Class / Layer** | الطبقة الأصلية (قبل التعديل). تقبل طبقات الخريطة أو ملفات من الـ GDB. | *مطلوب* |
| **Modified Feature Class / Layer** | الطبقة المعدلة (بعد التعديل). تقبل طبقات الخريطة أو ملفات من الـ GDB. | *مطلوب* |
| **Match Features By** | طريقة مطابقة العناصر بين الطبقتين: <br>• `By Spatial Location (Spatial Join)`: مطابقة مكانية عبر تداخل المعالم (الأسهل والأسرع).<br>• `By Attribute ID Field`: مطابقة بواسطة حقل المعرف الفريد.<br>• `By OBJECTID (Automatic)`: مطابقة عبر رقم الـ OBJECTID. | `By Spatial Location` |
| **Unique ID Field** | حقل المعرف الفريد (يظهر فقط ويُطلب عند اختيار `By Attribute ID Field`). | — |
| **Output Workspace** | قاعدة البيانات الجغرافية أو المجلد لحفظ النتائج. | `Default.gdb` |
| **Output Feature Class Name** | اسم الطبقة الناتجة. | `ChangeDetection_Result` |

---

### 2. مقارنة البيانات الوصفية (Attribute Comparison)

| المعامل | الوصف | القيمة الافتراضية |
|---|---|---|
| **Compare Attributes** | تفعيل أو تعطيل مقارنة الحقول الوصفية. | `True` (مفعل) |
| **Ignore Case Sensitivity** | تجاهل حالة الأحرف الإنجليزية (مثل `Residential` = `residential`). | `False` |
| **Treat NULL = Empty String** | اعتبار القيمة الفارغة `NULL` والنص الفارغ `""` متساويين. | `False` |
| **Fields to Compare** | اختيار حقول محددة للمقارنة (في حال تطابق هيكل الحقول بين الطبقتين). | جميع الحقول |
| **Field Mapping** | جدول ربط الحقول عند اختلاف أسماء الحقول بين الطبقتين (مثل ربط `Type` مع `Landuse`). | — |

---

### 3. المقارنة المكانية المتقدمة (Geometry Comparison)

محرك مقارنة هندسي ذكي يفصل بين دقة المقارنة والقيمة المخزنة الأصلية:

| المعامل | الوصف | القيمة الافتراضية | التأثير |
|---|---|---|---|
| **Area Decimal Places** | عدد الخانات العشرية لمقارنة المساحة (Polygon). | `3` | لا تُحتسب الفروق التي تقل عن $0.001$ كتغيير مساحة. |
| **Length Decimal Places** | عدد الخانات العشرية لمقارنة الطول (Polyline). | `3` | لا تُحتسب الفروق التي تقل عن $0.001$ كتغيير طول. |
| **Vertex Count Tolerance** | التسامح في عدد نقاط الرسم (Vertices). | `0` | إذا زاد أو قل عدد النقاط بمقدار يتجاوز هذا الرقم يتم تسجيل تغيير في النقاط. |
| **Spatial Tolerance** | أقصى إزاحة مكانية مسموحة (بوحدة الإحداثيات). | `0.03` متر | إذا تحركت النقطة/المعلم أكثر من هذه المسافة يتم رصد `Spatial Position Changed`. |
| **Compare Spatial Position** | مقارنة حركة المركز (Centroid) وبداية ونهاية الخطوط. | `True` | يكتشف تحرك المعلم حتى لو لم تتغير مساحته أو شكله. |
| **Compare Vertex Count** | فحص زيادة أو حذف نقاط من المعلم. | `True` | يكتشف تبسيط أو تعقيد الرسم. |
| **Compare Geometry Shape** | فحص تشوه الشكل الهندسي وتطابقه التوبولوجي. | `True` | يكتشف تغير الشكل حتى لو تساوت المساحة والمركز. |
| **Compare Z Coordinates** | مقارنة الارتفاعات والمناسيب ثلاثية الأبعاد (3D). | `False` | مخصص للطبقات ثلاثية الأبعاد والنقاط المساحية. |
| **Z Tolerance** | سماحية فرق المنسوب الرأسي. | `0.001` | حد رصد تغير الارتفاع. |

---

### 4. مراجعة الجودة وتتبع الملاحظات (QC Review & Issue Tracking)

مجموعة اختيارية بالكامل لدعم Workflow تدقيق ومراجعة البيانات ومطابقة الملاحظات القديمة بالتعديلات الجديدة:

| المعامل | النوع | الوصف | القيمة الافتراضية |
|---|---|---|---|
| **Enable QC Review / Issue Tracking** | Boolean | تفعيل أو تعطيل وحدة الـ QC بالكامل (اختياري 100%). | `False` |
| **Create QC Issues Feature Class** | Boolean | إنشاء طبقة قالب جاهزة للمراجعة (`QC_Issues`) مع الـ Domains. | `False` |
| **Existing QC Issues** | Layer / FC | اختيار طبقة نقاط الملاحظات المسجلة مسبقًا لمطابقتها مع التغييرات. | — |
| **QC Review Result FC Name** | String | اسم طبقة مخرجات تقييم المراجعة الناتجة. | `QC_Review_Result` |

---

### 5. المخرجات والتقارير (Output / Reports)

| المعامل | الوصف | القيمة الافتراضية |
|---|---|---|
| **Report Output Folder** | مجلد حفظ تقارير الإكسل والـ HTML. | مجلد المشروع (`Home Folder`) |
| **Generate HTML Report** | استخراج لوحة تقارير تفاعلية HTML. | `True` (مفعل) |
| **Export Added Features Separately** | تصدير المعالم المضافة فقط في طبقة مستقلة `_Added`. | `False` |
| **Export Deleted Features Separately** | تصدير المعالم المحذوفة فقط في طبقة مستقلة `_Deleted`. | `False` |
| **Filter Output FC by Change Type** | تصفية الطبقة الناتجة لعرض أنواع معينة من التغييرات فقط. | الكل |
| **Add Result to Current Map** | إضافة الطبقة الناتجة تلقائيًا للخريطة بتصنيف رمزي ملون. | `True` |

---

### 6. الإعدادات المحفوظة (Settings)

| المعامل | الوصف |
|---|---|
| **Save Comparison Settings to JSON** | حفظ كافة إعدادات المقارنة والـ QC في ملف JSON. |
| **Settings File Path (JSON output)** | مسار حفظ ملف الإعدادات. |
| **Load Settings from JSON File** | تحميل وتطبيق إعدادات سابقة بضغطة زر واحدة. |

---

## 🎯 منظومة مراجعة الجودة (QC Review & Issue Tracking)

### سير العمل (QC Workflow)
```text
بيانات المشروع الأصلية (Master Data)
        ↓
مراجعة وتدقيق المراجع (QC Reviewer)
        ↓
تسجيل الملاحظات في طبقة QC_Issues (Point FC)
        ↓
إرسال البيانات لفريق التعديل والتصحيح
        ↓
استلام النسخة المعدلة (Modified Feature Class)
        ↓
تشغيل Geo Change Detection مع تفعيل QC Review
        ↓
ربط الملاحظات بالمعالم عبر Feature_ID ومقارنة نوع الملاحظة بنوع التغيير الفعلي
        ↓
إصدار تقييم QC_Assessment (احتمالي لمساعدة المراجع)
```

---

### فلسفة التقييم ومصطلح Maybe Changed
> [!IMPORTANT]
> **قاعدة أساسية صارمة:**  
> الأداة **لا تعتبر المشكلة تم حلها تلقائيًا** ولا تستخدم مطلقًا استنتاج `Resolved` أو `Potentially Resolved`.  
> أقصى نتيجة استنتاجية تصدرها الأداة هي **`Maybe Changed`** ("احتمالية أنها عُدّلت")، وتعني:
> *"تم رصد تعديل على نفس المعلم يتوافق مع نوع المشكلة المسجلة، ويجب على المراجع البشري فتح المعلم والتحقق منه للتأكد من صحة التعديل واعتماد حله يدوياً."*

---

### مصفوفة اتخاذ القرار للـ QC

| نوع المشكلة المسجل (`Issue_Type`) | التغيير المكتشف في الأداة (`Change_Type`) | سبب التغيير الهندسي | تقييم الأداة (`QC_Assessment`) | المعنى الإجرائي |
|---|---|---|---|---|
| **Geometry Issue** | `Geometry Changed` أو `Geom + Attr Changed` | تغيّر في المساحة/النقاط/الموقع/الشكل | **`Maybe Changed`** | تم تعديل الرسم؛ يجب على المراجع التحقق. |
| **Geometry Issue** | `Attribute Changed` | لا يوجد تغيير هندسي | **`Needs Review`** | تم تعديل البيانات الوصفية فقط والمشكلة الهندسية لم تُعالج. |
| **Geometry Issue** | `Unchanged` | — | **`Not Changed`** | لم يتم رصد أي تعديل على المعلم. |
| **Attribute Issue** | `Attribute Changed` أو `Geom + Attr Changed` | تعديل في قيم الحقول | **`Maybe Changed`** | تم تعديل الحقول؛ تحقق من صحة القيم الجديدة. |
| **Attribute Issue** | `Geometry Changed` | لا يوجد تغيير في الحقول | **`Needs Review`** | عُدّل الرسم بدلاً من تعديل الحقول المطلوبة. |
| **Attribute Issue** | `Unchanged` | — | **`Not Changed`** | لم يتم رصد أي تعديل. |
| **Geometry & Attr Issue** | `Geometry and Attribute Changed` | تعديل هندسي ووصفي معًا | **`Maybe Changed`** | تم رصد تعديل في الهندسة والبيانات معًا. |
| **Missing Feature** | `Added` | معلم جديد تمت إضافته | **`Maybe Changed`** | تم رصد إضافة المعلم المفقود. |
| **Extra Feature** | `Deleted` | معلم تم حذفه | **`Maybe Changed`** | تم حذف المعلم الزائد. |
| *أي نوع* | المعلم غير موجود في الطبقة المعدلة | — | **`Feature Deleted`** | تم حذف المعلم المرتبط بالملاحظة. |
| *أي نوع* | المعلم غير موجود في الطبقتين | — | **`Feature Not Found`** | رقم المعلم غير مطابق لأي عنصر في البيانات. |

---

### هيكل طبقة QC_Issues والـ Domains

طبقة من نوع **Point Feature Class** تحتوي على الحقول والـ Domains التالية:

```text
QC_Issues (Point)
 ├── Issue_ID (Long Integer)           -> المعرف الفريد للملاحظة
 ├── Feature_ID (Text)                 -> رقم المعلم الأساسي للربط (Unique ID)
 ├── Issue_Type (Short / Domain)       -> 1=Geometry, 2=Attribute, 3=Both, 4=Missing, 5=Extra, 6=Topology, 7=Other
 ├── Reviewer_Note (Text 2000)         -> نص ملاحظة المراجع الأصلية (تُحفظ كما هي دون أي تعديل)
 ├── Reviewer (Text 100)               -> اسم المراجع
 ├── Created_Date (Date)               -> تاريخ الملاحظة
 ├── QC_Status (Short / Domain)        -> 1=Open, 2=In Review, 3=Resolved, 4=Not Resolved (تعديل يدوي فقط)
 ├── Last_Check_Status (Short / Domain)-> 0=Not Checked, 1=Changed, 2=Not Changed, 3=Added, 4=Deleted, 5=Not Found
 ├── Change_Type (Text)                -> نوع التغيير المرصود آليًا
 ├── Geometry_Change_Reason (Text)     -> سبب التغيير الهندسي المرصود
 └── QC_Assessment (Short / Domain)    -> 1=Maybe Changed, 2=Not Changed, 3=Needs Review, 4=Not Found, 5=Deleted
```

---

### طبقة نتائج المراجعة QC_Review_Result

عند تشغيل الأداة، يتم توليد طبقة **`QC_Review_Result`** (Point) بنفس إحداثيات ومواقع الملاحظات الأصلية دون تحريكها، وتتضمن:
- نقل نص الملاحظة الأصلية للمراجع بالكامل (`Reviewer_Note`).
- تقييم التغيير (`QC_Assessment` و `QC_Assessment_Desc`).
- إحداثيات مركز المعلم الحالي في النسخة المعدلة (`Current_Feature_X`, `Current_Feature_Y`).
- المسافة المكانية بين نقطة الملاحظة وموقع المعلم المعدل (`Distance_To_Current_Feature`).
- رقم وتاريخ دورة المراجعة (`Review_Run_ID`, `Review_Date`) لدعم مراجعة عدة دورات (Review Cycles).

---

## 📊 شرح المخرجات والنتائج

### تقرير الإكسل (Excel 5-Sheet Report)

يتم إنشاء ملف إكسل منسق باحترافية مكون من 5 أوراق عمل:
1. **Summary**: إحصائيات عامة، وتوزيع أسباب التغيير الهندسي، وقسم ملخص **QC Review & Issue Tracking Summary**.
2. **Detailed Report**: السجل الكامل لجميع المعالم مع الحقول الهندسية والوصفية وأسباب التغيير.
3. **Geometry Changes**: مخصص للمعالم التي طرأ عليها تعديل هندسي أو إضافة أو حذف فقط.
4. **Attribute Changes**: سجل تدقيق تفصيلي لكل حقل وصفي تغير وقيمته قبل وبعد (`Old_Value` vs `New_Value`).
5. **QC Review**: ورقة عمل مخصصة لجميع ملاحظات الـ QC مع تصنيفها اللوني وفق `QC_Assessment` وبيانات المسافة والتعديل.

---

### لوحة تقرير HTML التفاعلية المباشرة

ملف HTML قائم بذاته بتصميم عصري راقٍ، يحتوي على:
- **بطاقات المؤشرات الرقمية (KPI Cards)** للتغييرات العامة ولـ تقييمات الـ QC.
- **قسم تفاعلي خاص بـ QC Review & Issue Tracking** مع أزرار تصفية فورية (`Maybe Changed`, `Needs Review`, `Not Changed`, `Not Found`, `Deleted`).
- **محرك بحث فوري** لتصفية المعالم والملاحظات مباشرة حسب المعرف أو الملاحظة أو المراجع.
- **جدول التغييرات الهندسية والوصفية التفصيلي** مع أوسمة الأسباب والـ Badges الملونة.

---

## 💾 حفظ واسترجاع الإعدادات (Settings JSON)

يمكن حفظ كافة معايير المقارنة والـ QC في ملف `JSON`:
```json
{
  "orig_fc": "Parcels_Master",
  "mod_fc": "Parcels_Updated",
  "uid_field": "PARCEL_ID",
  "match_method": "By Attribute ID Field",
  "compare_attrs": true,
  "compare_geom": true,
  "area_decimal_places": 3,
  "spatial_tolerance": 0.3,
  "compare_spatial_position": true,
  "compare_vertex_count": true,
  "compare_geometry_shape": true,
  "qc_review": {
    "enabled": true,
    "create_qc_issues": false,
    "existing_qc_issues": "C:\\GIS_Data\\QC_Issues.shp",
    "qc_output": "QC_Review_Result"
  }
}
```

---

## 🐍 التشغيل عبر سكريبت بايثون (Python Scripting / Standalone)

يمكنك استدعاء الأداة مباشرة من بايثون:

```python
import arcpy

# تحميل صندوق الأدوات
toolbox_path = r"D:\Learning\RER\main\Compeare FeatureClassChangeDetection\GeoChangeDetection.pyt"
arcpy.ImportToolbox(toolbox_path, "FCChangeDetection")

# تشغيل المقارنة مع تفعيل مراجعة الجودة
arcpy.FCChangeDetection.ChangeDetectionTool(
    orig_fc          = r"C:\Data\Cadastre.gdb\Parcels_Old",
    mod_fc           = r"C:\Data\Cadastre.gdb\Parcels_New",
    uid_field        = "PARCEL_ID",
    out_ws           = r"C:\Data\Cadastre.gdb",
    out_name         = "Parcels_ChangeResult",
    compare_attrs    = True,
    compare_geom     = True,
    match_method     = "By Attribute ID Field",
    enable_qc_review = True,
    existing_qc_issues = r"C:\Data\Cadastre.gdb\QC_Issues",
    qc_output_name   = "Parcels_QC_Result",
    gen_html         = True,
    add_to_map       = True
)

print("تمت المقارنة والمراجعة بنجاح!")
```
