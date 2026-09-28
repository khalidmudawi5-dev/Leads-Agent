"""All Odoo DOM selectors in one place.

Edit this file when Odoo's UI changes. Every entry is an ordered list of
fallbacks: the first selector that matches wins. Selectors prefer stable hooks
(``name=`` field attributes, ``aria-label``/``title``, visible text in English
and Arabic, ``tel:`` links) over generated CSS classes.

``{field}`` placeholders are replaced with the technical field name.
"""
from __future__ import annotations

# ----------------------------------------------------------------- login page
LOGIN_FORM = [
    "form.oe_login_form",
    "form[action*='/web/login']",
    "input[name='login'][type='text'], input[name='login'][type='email']",
]

# ------------------------------------------------------------------ form view
FORM_VIEW = [
    ".o_form_view .o_form_sheet",
    ".o_form_view",
    "div.o_form_view_container",
]

# Technical field names per logical field (first existing one wins).
FIELD_NAMES: dict[str, list[str]] = {
    "lead_name": ["name"],
    "company_name": ["partner_name", "partner_id"],
    "contact_name": ["contact_name"],
    "phone": ["phone"],
    "mobile": ["mobile"],
    "email": ["email_from"],
    "salesperson": ["user_id"],
    "stage": ["stage_id"],
    "source": ["source_id"],
    "medium": ["medium_id"],
    "campaign": ["campaign_id"],
}

# Labels used when a field has no stable ``name`` attribute (EN / AR).
FIELD_LABELS: dict[str, list[str]] = {
    "company_name": ["Company Name", "Company", "اسم الشركة", "الشركة"],
    "contact_name": ["Contact Name", "Contact", "اسم جهة الاتصال", "جهة الاتصال"],
    "phone": ["Phone", "الهاتف", "رقم الهاتف"],
    "mobile": ["Mobile", "الجوال", "الهاتف المحمول"],
    "email": ["Email", "البريد الإلكتروني"],
    "salesperson": ["Salesperson", "مندوب المبيعات", "البائع"],
    "source": ["Source", "المصدر"],
    "medium": ["Medium", "الوسيط", "الوسيلة"],
    "campaign": ["Campaign", "الحملة"],
    "service_type": ["Service Type", "Service", "نوع الخدمة", "الخدمة"],
}

# Strategies to read the value of a field widget (``{field}`` = technical name).
FIELD_VALUE_SELECTORS = [
    "div[name='{field}'] input",
    ".o_field_widget[name='{field}'] input",
    "div[name='{field}'] textarea",
    "div[name='{field}'] a.o_form_uri",
    "div[name='{field}'] span",
    "div[name='{field}']",
    "[name='{field}']",
]

STAGE_SELECTORS = [
    ".o_statusbar_status button.o_arrow_button_current",
    ".o_statusbar_status button[aria-checked='true']",
    ".o_statusbar_status .o_arrow_button_current",
]

# -------------------------------------------------------------------- calling
# Existing Odoo call link/button inside the phone widget. We only click it; the
# OS ``tel:`` handler (Windows → Phone Link) does the rest.
CALL_BUTTON_SELECTORS = [
    "div[name='{field}'] a.o_phone_form_link",
    "div[name='{field}'] a[href^='tel:']",
    ".o_field_widget[name='{field}'] a[href^='tel:']",
    "div[name='{field}'] button[title*='Call']",
    "div[name='{field}'] a[title*='Call']",
    "div[name='{field}'] [aria-label*='Call']",
    "div[name='{field}'] a:has-text('Call')",
    "div[name='{field}'] a:has-text('اتصال')",
    "div[name='{field}'] button:has-text('اتصال')",
]
CALL_BUTTON_GENERIC = [
    ".o_form_view a[href^='tel:']",
    ".o_form_view button[title*='Call']",
    ".o_form_view [aria-label*='Call']",
]

# ------------------------------------------------------------------- chatter
LOG_NOTE_BUTTON = [
    "button.o-mail-Chatter-logNote",
    "button.o_ChatterTopbar_buttonLogNote",
    ".o-mail-Chatter button:has-text('Log note')",
    ".o-mail-Chatter button:has-text('تسجيل ملاحظة')",
    "button:has-text('Log note')",
    "button:has-text('تسجيل ملاحظة')",
]
COMPOSER_INPUT = [
    ".o-mail-Composer-input",
    ".o-mail-Composer textarea",
    ".o_ComposerTextInput_textArea",
    ".o-mail-Composer [contenteditable='true']",
]
COMPOSER_SEND = [
    ".o-mail-Composer-send",
    ".o-mail-Composer button:has-text('Log')",
    ".o-mail-Composer button:has-text('تسجيل')",
    ".o_Composer_buttonSend",
]
CHATTER_MESSAGE = [
    ".o-mail-Message-body",
    ".o-mail-Message",
    ".o_Message_content",
]
ACTIVITY_BUTTON = [
    "button.o-mail-Chatter-activity",
    "button.o_ChatterTopbar_buttonScheduleActivity",
    ".o-mail-Chatter button:has-text('Activit')",
    "button:has-text('Activities')",
    "button:has-text('الأنشطة')",
    "button:has-text('نشاط')",
]

# --------------------------------------------------------------- list search
SEARCH_INPUT = [
    ".o_searchview_input",
    "input[role='searchbox']",
    ".o_searchview input",
]
LIST_ROWS = [
    ".o_list_renderer tr.o_data_row",
    ".o_kanban_renderer .o_kanban_record:not(.o_kanban_ghost)",
]
