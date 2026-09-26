# =============================================================
# برنامج إدارة ومتابعة الطلبيات بين قسم المحاسبة والمخزن
# =============================================================
# هذا البرنامج بسيط ومكتوب لطالب يتعلم بايثون.
# يستخدم: import - متغيرات - قوائم - قواميس - دوال - if/elif/else - for - while
# لا يستخدم برمجة كائنية (OOP) إلا بالحد الأدنى جداً (لا شيء تقريباً هنا).
# =============================================================

import streamlit as st          # لإنشاء واجهة المستخدم
import sqlite3                  # لحفظ البيانات في قاعدة بيانات بسيطة
import os                       # للتعامل مع الملفات والمجلدات
import base64                   # لتحويل ملف PDF إلى نص لعرضه داخل الصفحة مباشرة
import unicodedata              # لتنظيف النصوص العربية من رموز الاتجاه الخفية
from datetime import datetime   # لتسجيل التاريخ والوقت

# محاولة استيراد مكتبات اختيارية (قد لا تكون مثبتة على كل جهاز)
# إذا لم تكن موجودة، سيتابع البرنامج العمل بدون ميزة OCR أو تحويل الصور
try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    import pytesseract
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False


# =============================================================
# إعدادات عامة (متغيرات ثابتة)
# =============================================================
DB_NAME = "orders.db"          # اسم ملف قاعدة البيانات
UPLOAD_FOLDER = "uploads"      # مجلد حفظ ملفات الطلبيات (PDF / صور)

# التأكد من وجود مجلد رفع الملفات
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)


# =============================================================
# دوال قاعدة البيانات
# =============================================================

def get_connection():
    """فتح اتصال جديد مع قاعدة البيانات"""
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    return conn


def clean_text_input(text):
    """
    تنظيف النص من رموز الاتجاه الخفية (Bidi control characters) التي قد تُضاف
    تلقائياً عند الكتابة بالعربية من بعض لوحات المفاتيح أو المتصفحات،
    والتي تجعل نصين يبدوان متطابقين للعين لكنهما مختلفان فعلياً عند المقارنة.
    """
    if text is None:
        return ""

    # الرموز الخفية الشائعة التي يجب إزالتها
    hidden_chars = [
        "\u200e", "\u200f",  # LRM, RLM
        "\u202a", "\u202b", "\u202c", "\u202d", "\u202e",  # embedding/override
        "\u2066", "\u2067", "\u2068", "\u2069",  # isolate
        "\ufeff",  # BOM
    ]
    for ch in hidden_chars:
        text = text.replace(ch, "")

    # توحيد شكل الأحرف (بعض الأحرف العربية لها أكثر من تمثيل Unicode لنفس الشكل)
    text = unicodedata.normalize("NFKC", text)

    return text.strip()


def init_database():
    """إنشاء الجداول إذا لم تكن موجودة، وإضافة حسابات افتراضية"""
    conn = get_connection()
    cursor = conn.cursor()

    # جدول المستخدمين (محاسبة / مخزن)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL
        )
    """)

    # جدول الطلبيات مع كل مراحلها وتواريخها في نفس الجدول (تبسيطاً للطالب)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_number TEXT UNIQUE NOT NULL,
            customer_name TEXT NOT NULL,
            order_type TEXT NOT NULL,          -- 'رئيسية' أو 'إضافة'
            parent_order_number TEXT,          -- يُستخدم فقط إذا كانت النوع إضافة
            items_count INTEGER,
            file_path TEXT,
            ocr_note TEXT,
            status TEXT NOT NULL,
            created_at TEXT,
            sent_at TEXT,
            received_at TEXT,
            prepared_at TEXT,
            delivered_at TEXT
        )
    """)

    # جدول إعدادات عامة بسيط (مفتاح / قيمة) - يُستخدم لتخزين مدة الاحتفاظ بالطلبيات
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            setting_key TEXT PRIMARY KEY,
            setting_value TEXT
        )
    """)

    conn.commit()

    # إضافة حسابين افتراضيين إذا كانت قاعدة البيانات فارغة من المستخدمين
    cursor.execute("SELECT COUNT(*) FROM users")
    users_count = cursor.fetchone()[0]

    if users_count == 0:
        default_users = [
            ("accounting", "1234", "محاسبة"),
            ("warehouse", "1234", "مخزن"),
        ]
        for user in default_users:
            cursor.execute(
                "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                user
            )

    # إضافة قيمة افتراضية لمدة الاحتفاظ بالطلبيات (30 يوماً) إذا لم تكن موجودة
    cursor.execute("SELECT COUNT(*) FROM settings WHERE setting_key = 'retention_days'")
    setting_exists = cursor.fetchone()[0]
    if setting_exists == 0:
        cursor.execute(
            "INSERT INTO settings (setting_key, setting_value) VALUES (?, ?)",
            ("retention_days", "30")
        )
        conn.commit()

    conn.close()


def check_login(username, password):
    """التحقق من اسم المستخدم وكلمة المرور، وإرجاع الدور (role) إذا كانا صحيحين"""
    # تنظيف النص من المسافات والرموز الخفية (مهم خصوصاً مع الكتابة بالعربية)
    username = clean_text_input(username)
    password = clean_text_input(password)

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT role FROM users WHERE username = ? AND password = ?",
        (username, password)
    )
    result = cursor.fetchone()
    conn.close()

    if result is not None:
        return result[0]   # إرجاع الدور: 'محاسبة' أو 'مخزن'
    else:
        return None


def create_user(username, password, role):
    """
    إنشاء حساب مستخدم جديد.
    ترجع (True, "رسالة نجاح") أو (False, "رسالة خطأ") حسب النتيجة.
    """
    username = clean_text_input(username)
    password = clean_text_input(password)

    if username == "" or password == "":
        return False, "الرجاء إدخال اسم مستخدم وكلمة مرور"

    conn = get_connection()
    cursor = conn.cursor()

    # التأكد من عدم تكرار اسم المستخدم
    cursor.execute("SELECT COUNT(*) FROM users WHERE username = ?", (username,))
    exists = cursor.fetchone()[0]

    if exists > 0:
        conn.close()
        return False, "اسم المستخدم موجود مسبقاً، الرجاء اختيار اسم آخر"

    cursor.execute(
        "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
        (username, password, role)
    )
    conn.commit()
    conn.close()
    return True, "تم إنشاء الحساب بنجاح"


def get_all_users():
    """إرجاع كل المستخدمين (بدون كلمات المرور) لعرضهم في الإعدادات"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT username, role FROM users ORDER BY id")
    rows = cursor.fetchall()
    conn.close()
    return rows


def delete_user(username):
    """حذف حساب مستخدم بالاسم (يُستخدم مثلاً لحذف حساب أُنشئ بالخطأ)"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM users WHERE username = ?", (username,))
    conn.commit()
    conn.close()


def get_setting(key, default_value):
    """قراءة قيمة إعداد معيّن من جدول settings"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT setting_value FROM settings WHERE setting_key = ?", (key,))
    result = cursor.fetchone()
    conn.close()

    if result is not None:
        return result[0]
    else:
        return default_value


def set_setting(key, value):
    """حفظ أو تحديث قيمة إعداد معيّن"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO settings (setting_key, setting_value) VALUES (?, ?)
        ON CONFLICT(setting_key) DO UPDATE SET setting_value = excluded.setting_value
    """, (key, str(value)))
    conn.commit()
    conn.close()


def get_retention_days():
    """إرجاع عدد الأيام المسموح بها قبل حذف الطلبيات المكتملة تلقائياً"""
    value = get_setting("retention_days", "30")
    return int(value)


def cleanup_old_orders():
    """
    حذف تلقائي للطلبيات المكتملة (تم التسليم للمحاسبة) فقط،
    والتي مضى على تسليمها أكثر من عدد الأيام المحدد في الإعدادات.
    لا يتم حذف أي طلبية ما زالت قيد التنفيذ حفاظاً على سلامة المتابعة.
    """
    retention_days = get_retention_days()

    conn = get_connection()
    cursor = conn.cursor()

    # جلب الطلبيات المكتملة فقط
    cursor.execute("""
        SELECT order_number, file_path, delivered_at FROM orders
        WHERE status = 'تم التسليم للمحاسبة'
    """)
    delivered_orders = cursor.fetchall()

    deleted_count = 0
    now = datetime.now()

    for order_number, file_path, delivered_at in delivered_orders:
        if delivered_at is None or delivered_at == "":
            continue

        # حساب عدد الأيام منذ تاريخ التسليم
        delivered_time = datetime.strptime(delivered_at, "%Y-%m-%d %H:%M:%S")
        days_passed = (now - delivered_time).days

        if days_passed >= retention_days:
            # حذف الملف المرفق إن وجد
            if file_path and os.path.exists(file_path):
                os.remove(file_path)

            # حذف السجل من قاعدة البيانات
            cursor.execute("DELETE FROM orders WHERE order_number = ?", (order_number,))
            deleted_count = deleted_count + 1

    conn.commit()
    conn.close()
    return deleted_count


def seed_demo_data():
    """
    إضافة طلبيات تجريبية بمراحل وتواريخ مختلفة، لتظهر واجهة البرنامج
    وهي معبّأة بشكل واقعي أثناء العرض التوضيحي (بدون ملفات حقيقية مرفقة).
    """
    from datetime import timedelta

    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.now()

    def t(days_ago, hours_ago=0):
        return (now - timedelta(days=days_ago, hours=hours_ago)).strftime("%Y-%m-%d %H:%M:%S")

    # كل عنصر: رقم، زبون، نوع، والد، عدد أصناف، تواريخ كل مرحلة (أو None إذا لم تحصل بعد)
    demo_orders = [
        ("DEMO-0001", "أحمد الحلبي", "رئيسية", None, 5,
         t(0, 2), None, None, None, None, "تم الإنشاء"),

        ("DEMO-0002", "سارة العلي", "رئيسية", None, 8,
         t(1), t(1, -1), None, None, None, "تم إرسالها إلى المخزن"),

        ("DEMO-0003", "محمد عودة", "رئيسية", None, 12,
         t(2), t(2, -1), t(2, -2), None, None, "تم الاستلام"),

        ("DEMO-0004", "محمد عودة", "إضافة", "DEMO-0003", 3,
         t(1), t(1, -1), t(1, -2), t(0, -3), None, "تم التجهيز"),

        ("DEMO-0005", "ليلى نمر", "رئيسية", None, 20,
         t(4), t(4, -1), t(4, -2), t(3), t(2), "تم التسليم للمحاسبة"),
    ]

    for order in demo_orders:
        (order_number, customer, order_type, parent, items,
         created_at, sent_at, received_at, prepared_at, delivered_at, status) = order

        cursor.execute("SELECT COUNT(*) FROM orders WHERE order_number = ?", (order_number,))
        already_exists = cursor.fetchone()[0]

        if already_exists == 0:
            cursor.execute("""
                INSERT INTO orders (
                    order_number, customer_name, order_type, parent_order_number,
                    items_count, file_path, ocr_note, status,
                    created_at, sent_at, received_at, prepared_at, delivered_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                order_number, customer, order_type, parent, items,
                None, "", status,
                created_at, sent_at, received_at, prepared_at, delivered_at
            ))

    conn.commit()
    conn.close()


def delete_all_demo_data():
    """حذف كل الطلبيات التي تبدأ برقم DEMO- فقط (لا تمس الطلبيات الحقيقية)"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM orders WHERE order_number LIKE 'DEMO-%'")
    conn.commit()
    conn.close()


def generate_order_number():
    """توليد رقم طلبية فريد تلقائياً بصيغة ORD-YYYY-XXXX"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM orders")
    count = cursor.fetchone()[0]
    conn.close()

    year = datetime.now().year
    new_number = count + 1
    # تنسيق الرقم ليكون بشكل 0001 - 0002 - ... الخ
    order_number = "ORD-" + str(year) + "-" + str(new_number).zfill(4)
    return order_number


def get_customer_main_orders(customer_name):
    """إرجاع قائمة بأرقام الطلبيات الرئيسية الخاصة بزبون معين"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT order_number FROM orders
        WHERE customer_name = ? AND order_type = 'رئيسية'
        ORDER BY created_at DESC
    """, (customer_name,))
    rows = cursor.fetchall()
    conn.close()

    order_numbers = []
    for row in rows:
        order_numbers.append(row[0])
    return order_numbers


def insert_order(order_number, customer_name, order_type, parent_order_number,
                  items_count, file_path, ocr_note):
    """إضافة طلبية جديدة إلى قاعدة البيانات"""
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute("""
        INSERT INTO orders (
            order_number, customer_name, order_type, parent_order_number,
            items_count, file_path, ocr_note, status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        order_number, customer_name, order_type, parent_order_number,
        items_count, file_path, ocr_note, "تم الإنشاء", now
    ))

    conn.commit()
    conn.close()


def update_order_status(order_number, new_status, time_column):
    """تحديث حالة الطلبية وتسجيل تاريخ ووقت المرحلة الجديدة"""
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # بناء الاستعلام حسب اسم عمود الوقت (sent_at, received_at, ...)
    query = "UPDATE orders SET status = ?, " + time_column + " = ? WHERE order_number = ?"
    cursor.execute(query, (new_status, now, order_number))

    conn.commit()
    conn.close()


def get_all_orders():
    """إرجاع جميع الطلبيات كقائمة قواميس (dict) لسهولة التعامل معها"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM orders ORDER BY created_at DESC")
    rows = cursor.fetchall()
    columns = [description[0] for description in cursor.description]
    conn.close()

    orders_list = []
    for row in rows:
        # تحويل كل صف (row) إلى قاموس باستخدام أسماء الأعمدة
        order_dict = dict(zip(columns, row))
        orders_list.append(order_dict)

    return orders_list


def get_orders_by_status(status_value):
    """إرجاع الطلبيات التي تطابق حالة معينة"""
    all_orders = get_all_orders()
    filtered = []
    for order in all_orders:
        if order["status"] == status_value:
            filtered.append(order)
    return filtered


def search_orders(search_text):
    """البحث برقم الطلبية أو باسم الزبون"""
    all_orders = get_all_orders()
    results = []
    search_text = search_text.strip().lower()

    for order in all_orders:
        order_number_lower = order["order_number"].lower()
        customer_lower = order["customer_name"].lower()
        if search_text in order_number_lower or search_text in customer_lower:
            results.append(order)

    return results


def get_order_by_number(order_number):
    """إرجاع طلبية واحدة برقمها"""
    all_orders = get_all_orders()
    for order in all_orders:
        if order["order_number"] == order_number:
            return order
    return None


def get_related_orders(main_order_number):
    """إرجاع الطلبية الرئيسية + كل الإضافات المرتبطة بها"""
    all_orders = get_all_orders()
    related = []
    for order in all_orders:
        is_main = order["order_number"] == main_order_number
        is_addition = order["parent_order_number"] == main_order_number
        if is_main or is_addition:
            related.append(order)
    return related


# =============================================================
# دوال معالجة الملفات (PDF / صور / OCR)
# =============================================================

def save_uploaded_pdf(uploaded_file, order_number):
    """حفظ ملف PDF تم رفعه مباشرة، وإرجاع مسار الملف"""
    file_path = os.path.join(UPLOAD_FOLDER, order_number + ".pdf")
    with open(file_path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return file_path


def convert_image_to_pdf(uploaded_image, order_number):
    """تحويل صورة مرفوعة إلى ملف PDF وحفظه"""
    file_path = os.path.join(UPLOAD_FOLDER, order_number + ".pdf")

    if not PIL_AVAILABLE:
        # إذا لم تكن مكتبة Pillow مثبتة، نحفظ الصورة كما هي بدون تحويل
        image_path = os.path.join(UPLOAD_FOLDER, order_number + ".png")
        with open(image_path, "wb") as f:
            f.write(uploaded_image.getbuffer())
        return image_path

    image = Image.open(uploaded_image)
    # تحويل الصورة لوضع RGB (مطلوب لحفظها كـ PDF)
    if image.mode != "RGB":
        image = image.convert("RGB")
    image.save(file_path, "PDF")
    return file_path


def try_ocr_count_items(uploaded_image):
    """
    محاولة استخراج عدد الأصناف تلقائياً من صورة باستخدام OCR بسيط.
    ملاحظة: OCR قد يخطئ إذا كانت الصورة غير واضحة أو مائلة.
    نعتبر كل سطر غير فارغ في النص المستخرج = صنف واحد تقريباً.
    """
    if not OCR_AVAILABLE or not PIL_AVAILABLE:
        return None, "ميزة OCR غير متوفرة على هذا الجهاز (المكتبات غير مثبتة)."

    try:
        image = Image.open(uploaded_image)
        extracted_text = pytesseract.image_to_string(image, lang="ara+eng")

        # تقسيم النص إلى أسطر وحساب الأسطر غير الفارغة فقط
        lines = extracted_text.split("\n")
        items_count = 0
        for line in lines:
            clean_line = line.strip()
            if clean_line != "":
                items_count = items_count + 1

        note = "تم استخراج العدد تلقائياً عبر OCR (قد يكون غير دقيق، الرجاء المراجعة)."
        return items_count, note

    except Exception as error:
        return None, "فشلت محاولة OCR: " + str(error)


# =============================================================
# دالة عرض الخط الزمني (Timeline) للطلبية
# =============================================================

def show_timeline(order):
    """عرض مراحل الطلبية بالتاريخ والوقت بشكل بسيط"""
    stages = [
        ("📝 إنشاء الطلبية", order["created_at"]),
        ("📤 الإرسال إلى المخزن", order["sent_at"]),
        ("📥 استلام المخزن", order["received_at"]),
        ("📦 تجهيز الطلبية", order["prepared_at"]),
        ("✅ تسليم الطلبية للمحاسبة", order["delivered_at"]),
    ]

    for stage_name, stage_time in stages:
        if stage_time:
            st.write(stage_name + "  —  " + stage_time)
        else:
            st.write(stage_name + "  —  ⏳ لم تتم بعد")


def show_pdf_preview(file_path):
    """
    عرض ملف الطلبية (PDF أو صورة) للقراءة اليدوية مباشرة داخل الصفحة،
    بدون الحاجة لتحميله على الجهاز.
    """
    if not file_path or not os.path.exists(file_path):
        st.warning("الملف غير موجود")
        return

    file_lower = file_path.lower()

    if file_lower.endswith(".pdf"):
        # قراءة الملف وتحويله إلى نص base64 لعرضه داخل إطار (iframe)
        with open(file_path, "rb") as f:
            file_bytes = f.read()
        base64_pdf = base64.b64encode(file_bytes).decode("utf-8")

        pdf_html = (
            '<iframe src="data:application/pdf;base64,' + base64_pdf +
            '" width="100%" height="500" style="border:1px solid #444;"></iframe>'
        )
        st.markdown(pdf_html, unsafe_allow_html=True)
        st.caption("💡 إذا لم يظهر الملف داخل المتصفح (يحدث أحياناً على بعض هواتف الجوال)، استخدم زر التحميل بالأسفل.")
    else:
        # إذا كان الملف صورة، نعرضها مباشرة
        st.image(file_path)


# =============================================================
# صفحة تسجيل الدخول
# =============================================================

def login_page():
    st.title("🔐 تسجيل الدخول")
    st.write("برنامج متابعة الطلبيات بين المحاسبة والمخزن")

    username = st.text_input("اسم المستخدم")
    password = st.text_input("كلمة المرور", type="password")

    if st.button("دخول"):
        role = check_login(username, password)
        if role is not None:
            st.session_state["logged_in"] = True
            st.session_state["username"] = username
            st.session_state["role"] = role
            st.rerun()
        else:
            st.error("اسم المستخدم أو كلمة المرور غير صحيحة")

    with st.expander("ℹ️ حسابات تجريبية جاهزة"):
        st.write("حساب المحاسبة: accounting / 1234")
        st.write("حساب المخزن: warehouse / 1234")


# =============================================================
# لوحة الإحصائيات المشتركة (تظهر لكلا الطرفين)
# =============================================================

def show_dashboard():
    all_orders = get_all_orders()

    # عدّ الطلبيات حسب الحالة باستخدام حلقة while بسيطة (لتلبية طلب استخدام while)
    counts = {
        "تم الإنشاء": 0,
        "تم إرسالها إلى المخزن": 0,
        "تم الاستلام": 0,
        "تم التجهيز": 0,
        "تم التسليم للمحاسبة": 0,
    }

    index = 0
    while index < len(all_orders):
        current_status = all_orders[index]["status"]
        if current_status in counts:
            counts[current_status] = counts[current_status] + 1
        index = index + 1

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("جديدة", counts["تم الإنشاء"])
    col2.metric("مرسلة للمخزن", counts["تم إرسالها إلى المخزن"])
    col3.metric("مستلمة", counts["تم الاستلام"])
    col4.metric("مجهزة", counts["تم التجهيز"])
    col5.metric("مسلمة", counts["تم التسليم للمحاسبة"])


# =============================================================
# واجهة المحاسبة
# =============================================================

def accounting_interface():
    st.title("📊 واجهة المحاسبة")
    show_dashboard()

    tab1, tab2, tab3 = st.tabs(["➕ إنشاء طلبية جديدة", "📋 متابعة الطلبيات", "🔍 بحث"])

    # ---------- تبويب إنشاء طلبية جديدة ----------
    with tab1:
        st.subheader("إنشاء طلبية جديدة")

        customer_name = st.text_input("اسم الزبون")

        order_type = st.radio("نوع الطلبية", ["رئيسية", "إضافة"])

        parent_order_number = None
        if order_type == "إضافة":
            if customer_name.strip() == "":
                st.info("الرجاء إدخال اسم الزبون أولاً لعرض طلبياته الرئيسية")
            else:
                main_orders = get_customer_main_orders(customer_name.strip())
                if len(main_orders) == 0:
                    st.warning("لا توجد طلبية رئيسية لهذا الزبون بعد. الرجاء إنشاء طلبية رئيسية أولاً.")
                else:
                    parent_order_number = st.selectbox(
                        "اختر الطلبية الرئيسية المرتبطة",
                        main_orders
                    )

        st.markdown("---")
        st.write("**رفع ملف الطلبية**")
        file_kind = st.radio("نوع الملف الذي سيتم رفعه", ["ملف PDF جاهز", "صورة (سيتم التعامل معها)"])

        uploaded_file = None
        convert_to_pdf = False
        run_ocr = False

        if file_kind == "ملف PDF جاهز":
            uploaded_file = st.file_uploader("ارفع ملف PDF", type=["pdf"])
        else:
            uploaded_file = st.file_uploader("ارفع صورة الطلبية", type=["png", "jpg", "jpeg"])
            convert_to_pdf = st.checkbox("تحويل الصورة إلى PDF تلقائياً", value=True)
            run_ocr = st.checkbox("محاولة استخراج عدد الأصناف تلقائياً (OCR)", value=True)
            st.caption("⚠️ ملاحظة: قد يخطئ OCR في حال كانت الصورة غير واضحة أو مائلة.")

        manual_items_count = st.number_input("عدد الأصناف (يمكن تعديله يدوياً)", min_value=0, step=1, value=0)

        if st.button("💾 حفظ وإنشاء الطلبية"):
            if customer_name.strip() == "":
                st.error("الرجاء إدخال اسم الزبون")
            elif order_type == "إضافة" and parent_order_number is None:
                st.error("الرجاء اختيار الطلبية الرئيسية المرتبطة")
            elif uploaded_file is None:
                st.error("الرجاء رفع ملف الطلبية (PDF أو صورة)")
            else:
                # توليد رقم طلبية فريد
                order_number = generate_order_number()

                ocr_note = ""
                final_items_count = manual_items_count

                # حفظ الملف حسب نوعه
                if file_kind == "ملف PDF جاهز":
                    file_path = save_uploaded_pdf(uploaded_file, order_number)
                else:
                    # محاولة OCR أولاً (قبل تحويل المؤشر داخل الملف)
                    if run_ocr:
                        extracted_count, note = try_ocr_count_items(uploaded_file)
                        ocr_note = note
                        if extracted_count is not None and manual_items_count == 0:
                            final_items_count = extracted_count
                        uploaded_file.seek(0)  # إعادة مؤشر القراءة بعد OCR

                    if convert_to_pdf:
                        file_path = convert_image_to_pdf(uploaded_file, order_number)
                    else:
                        file_path = os.path.join(UPLOAD_FOLDER, order_number + ".png")
                        with open(file_path, "wb") as f:
                            f.write(uploaded_file.getbuffer())

                insert_order(
                    order_number, customer_name.strip(), order_type,
                    parent_order_number, final_items_count, file_path, ocr_note
                )

                st.success("تم إنشاء الطلبية بنجاح! رقم الطلبية: " + order_number)
                if ocr_note:
                    st.info(ocr_note)
                st.rerun()

    # ---------- تبويب متابعة الطلبيات ----------
    with tab2:
        st.subheader("متابعة الطلبيات")
        all_orders = get_all_orders()

        if len(all_orders) == 0:
            st.info("لا توجد طلبيات حتى الآن")
        else:
            # عرض فقط الطلبيات الرئيسية، وتحتها الإضافات المرتبطة
            for order in all_orders:
                if order["order_type"] == "رئيسية":
                    with st.expander(
                        "📦 " + order["order_number"] + " — " + order["customer_name"] +
                        " — الحالة: " + order["status"]
                    ):
                        related_orders = get_related_orders(order["order_number"])
                        for related in related_orders:
                            st.write("---")
                            st.write("**نوع الطلبية:** " + related["order_type"])
                            st.write("**رقم الطلبية:** " + related["order_number"])
                            st.write("**عدد الأصناف:** " + str(related["items_count"]))
                            st.write("**الحالة الحالية:** " + related["status"])

                            if related["file_path"] and os.path.exists(related["file_path"]):
                                with st.expander("📖 معاينة وقراءة الملف يدوياً"):
                                    show_pdf_preview(related["file_path"])

                                with open(related["file_path"], "rb") as f:
                                    st.download_button(
                                        "⬇️ تحميل الملف",
                                        f,
                                        file_name=os.path.basename(related["file_path"]),
                                        key="download_" + related["order_number"]
                                    )

                            show_timeline(related)

                            # زر إرسال الطلبية إلى المخزن (فقط إذا لم تُرسل بعد)
                            if related["status"] == "تم الإنشاء":
                                if st.button(
                                    "📤 إرسال الطلبية إلى المخزن",
                                    key="send_" + related["order_number"]
                                ):
                                    update_order_status(related["order_number"], "تم إرسالها إلى المخزن", "sent_at")
                                    st.success("تم إرسال الطلبية إلى المخزن")
                                    st.rerun()

    # ---------- تبويب البحث ----------
    with tab3:
        st.subheader("البحث برقم الطلبية أو اسم الزبون")
        search_text = st.text_input("اكتب رقم الطلبية أو اسم الزبون")

        if search_text.strip() != "":
            results = search_orders(search_text)
            if len(results) == 0:
                st.warning("لا توجد نتائج مطابقة")
            else:
                for order in results:
                    st.write("---")
                    st.write("**رقم الطلبية:** " + order["order_number"])
                    st.write("**الزبون:** " + order["customer_name"])
                    st.write("**النوع:** " + order["order_type"])
                    st.write("**الحالة:** " + order["status"])
                    show_timeline(order)


# =============================================================
# واجهة المخزن
# =============================================================

def warehouse_interface():
    st.title("🏬 واجهة المخزن")
    show_dashboard()

    tab1, tab2, tab3 = st.tabs(["📥 الطلبيات الواردة", "⚙️ متابعة الحالة", "🔍 بحث"])

    # ---------- الطلبيات المرسلة حديثاً (بانتظار الاستلام) ----------
    with tab1:
        st.subheader("طلبيات بانتظار الاستلام")
        pending_orders = get_orders_by_status("تم إرسالها إلى المخزن")

        if len(pending_orders) == 0:
            st.info("لا توجد طلبيات جديدة حالياً")
        else:
            for order in pending_orders:
                st.write("---")
                st.write("**رقم الطلبية:** " + order["order_number"])
                st.write("**اسم الزبون:** " + order["customer_name"])
                st.write("**عدد الأصناف:** " + str(order["items_count"]))
                st.write("**تاريخ ووقت الإرسال من المحاسبة:** " + str(order["sent_at"]))

                if order["file_path"] and os.path.exists(order["file_path"]):
                    with st.expander("📖 معاينة وقراءة الملف يدوياً"):
                        show_pdf_preview(order["file_path"])

                    with open(order["file_path"], "rb") as f:
                        st.download_button(
                            "⬇️ تحميل ملف الطلبية",
                            f,
                            file_name=os.path.basename(order["file_path"]),
                            key="wh_download_" + order["order_number"]
                        )

                if st.button("✅ تأكيد استلام الطلبية", key="receive_" + order["order_number"]):
                    update_order_status(order["order_number"], "تم الاستلام", "received_at")
                    st.success("تم تسجيل استلام الطلبية")
                    st.rerun()

    # ---------- متابعة حالة الطلبيات المستلمة (تجهيز / تسليم) ----------
    with tab2:
        st.subheader("تجهيز وتسليم الطلبيات")

        received_orders = get_orders_by_status("تم الاستلام")
        prepared_orders = get_orders_by_status("تم التجهيز")

        st.write("### 🟡 طلبيات مستلمة بانتظار التجهيز")
        if len(received_orders) == 0:
            st.info("لا توجد طلبيات بانتظار التجهيز")
        else:
            for order in received_orders:
                st.write("---")
                st.write(order["order_number"] + " — " + order["customer_name"])
                if st.button("📦 تم تجهيز الطلبية", key="prep_" + order["order_number"]):
                    update_order_status(order["order_number"], "تم التجهيز", "prepared_at")
                    st.success("تم تسجيل تجهيز الطلبية")
                    st.rerun()

        st.write("### 🟢 طلبيات مجهزة بانتظار التسليم")
        if len(prepared_orders) == 0:
            st.info("لا توجد طلبيات بانتظار التسليم")
        else:
            for order in prepared_orders:
                st.write("---")
                st.write(order["order_number"] + " — " + order["customer_name"])
                if st.button("✅ تم تسليم الطلبية للمحاسبة", key="deliver_" + order["order_number"]):
                    update_order_status(order["order_number"], "تم التسليم للمحاسبة", "delivered_at")
                    st.success("تم تسجيل تسليم الطلبية")
                    st.rerun()

    # ---------- بحث ----------
    with tab3:
        st.subheader("البحث برقم الطلبية أو اسم الزبون")
        search_text = st.text_input("اكتب رقم الطلبية أو اسم الزبون", key="wh_search")

        if search_text.strip() != "":
            results = search_orders(search_text)
            if len(results) == 0:
                st.warning("لا توجد نتائج مطابقة")
            else:
                for order in results:
                    st.write("---")
                    st.write("**رقم الطلبية:** " + order["order_number"])
                    st.write("**الزبون:** " + order["customer_name"])
                    st.write("**الحالة:** " + order["status"])
                    show_timeline(order)


# =============================================================
# الدالة الرئيسية (Main) التي تشغّل البرنامج
# =============================================================

def main():
    st.set_page_config(page_title="متابعة الطلبيات", page_icon="📦", layout="centered")

    # إنشاء قاعدة البيانات عند أول تشغيل
    init_database()

    # تشغيل الحذف التلقائي للطلبيات القديمة المكتملة (مرة واحدة فقط في كل جلسة متصفح)
    if "cleanup_done" not in st.session_state:
        cleanup_old_orders()
        st.session_state["cleanup_done"] = True

    # تهيئة حالة الجلسة (session_state) إذا لم تكن موجودة
    if "logged_in" not in st.session_state:
        st.session_state["logged_in"] = False

    # إذا لم يسجل المستخدم الدخول بعد -> عرض صفحة تسجيل الدخول
    if st.session_state["logged_in"] == False:
        login_page()
    else:
        # عرض معلومات المستخدم وزر تسجيل الخروج في الشريط الجانبي
        st.sidebar.write("👤 المستخدم: " + st.session_state["username"])
        st.sidebar.write("🏷️ الدور: " + st.session_state["role"])
        if st.sidebar.button("🚪 تسجيل الخروج"):
            st.session_state["logged_in"] = False
            st.rerun()

        # قسم الإعدادات: إنشاء حسابات جديدة + مدة الاحتفاظ بالطلبيات
        with st.sidebar.expander("⚙️ الإعدادات"):

            st.write("**➕ إنشاء حساب جديد**")
            new_username = st.text_input("اسم المستخدم الجديد", key="new_username")
            new_password = st.text_input("كلمة المرور", type="password", key="new_password")
            new_role = st.selectbox("الدور", ["محاسبة", "مخزن"], key="new_role")

            if st.button("إنشاء الحساب", key="create_account_btn"):
                success, message = create_user(new_username, new_password, new_role)
                if success:
                    st.success(message)
                else:
                    st.error(message)

            st.write("**👥 الحسابات الحالية**")
            all_users = get_all_users()
            usernames_list = []
            for user_row in all_users:
                st.write("- " + user_row[0] + " (" + user_row[1] + ")")
                usernames_list.append(user_row[0])

            if len(usernames_list) > 0:
                user_to_delete = st.selectbox(
                    "اختر حساباً لحذفه (مثلاً حساب أُنشئ بالخطأ)",
                    usernames_list, key="user_to_delete"
                )
                if st.button("🗑️ حذف هذا الحساب", key="delete_user_btn"):
                    delete_user(user_to_delete)
                    st.success("تم حذف الحساب: " + user_to_delete)
                    st.rerun()

            st.write("---")
            st.write("**🗑️ الحذف التلقائي للطلبيات المكتملة**")
            current_retention = get_retention_days()
            st.caption(
                "يتم حذف الطلبيات المكتملة فقط (تم تسليمها للمحاسبة) "
                "بعد مرور المدة المحددة. الطلبيات قيد التنفيذ لا تُحذف أبداً."
            )
            new_retention = st.number_input(
                "عدد الأيام قبل الحذف (مثلاً 30 = شهر)",
                min_value=1, max_value=3650, value=current_retention, step=1
            )
            if st.button("💾 حفظ المدة", key="save_retention_btn"):
                set_setting("retention_days", new_retention)
                st.success("تم حفظ المدة: " + str(new_retention) + " يوم")

            if st.button("🧹 تشغيل الحذف الآن يدوياً", key="run_cleanup_btn"):
                deleted = cleanup_old_orders()
                st.success("تم حذف " + str(deleted) + " طلبية مكتملة قديمة")

            st.write("---")
            st.write("**🎬 بيانات تجريبية للعرض التوضيحي**")
            st.caption("يضيف عدة طلبيات وهمية بمراحل مختلفة (بدون ملفات حقيقية) لتجربة الواجهة أثناء العرض.")

            col_a, col_b = st.columns(2)
            with col_a:
                if st.button("➕ إضافة بيانات تجريبية", key="seed_demo_btn"):
                    seed_demo_data()
                    st.success("تمت إضافة الطلبيات التجريبية")
                    st.rerun()
            with col_b:
                if st.button("🗑️ حذف البيانات التجريبية", key="delete_demo_btn"):
                    delete_all_demo_data()
                    st.success("تم حذف الطلبيات التجريبية")
                    st.rerun()

        # توجيه المستخدم للواجهة المناسبة حسب دوره
        if st.session_state["role"] == "محاسبة":
            accounting_interface()
        elif st.session_state["role"] == "مخزن":
            warehouse_interface()
        else:
            st.error("دور غير معروف")


# نقطة بداية تشغيل البرنامج
if __name__ == "__main__":
    main()
