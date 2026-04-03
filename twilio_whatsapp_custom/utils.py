import json
import frappe
from frappe.utils import now_datetime


def get_settings():
    return frappe.get_single("Twilio WhatsApp Settings")


def normalize_number(number: str) -> str:
    if not number:
        return ""

    number = str(number).strip()
    number = number.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")

    if number.startswith("whatsapp:"):
        return number

    if not number.startswith("+"):
        number = f"+{number}"

    return f"whatsapp:{number}"


def find_customer_by_mobile(mobile_no: str):
    if not mobile_no:
        return None

    cleaned = mobile_no.replace("whatsapp:", "").replace("+", "")

    result = frappe.db.sql(
        """
        SELECT dl.link_name
        FROM `tabContact Phone` cp
        INNER JOIN `tabDynamic Link` dl
            ON dl.parent = cp.parent
        WHERE dl.link_doctype = 'Customer'
          AND REPLACE(REPLACE(REPLACE(REPLACE(cp.phone,'whatsapp:',''),'+',''),' ',''),'-','') LIKE %s
        LIMIT 1
        """,
        (f"%{cleaned}%",),
        as_dict=True,
    )

    return result[0].link_name if result else None


def find_or_create_conversation(mobile_no: str, party=None):
    mobile_no = normalize_number(mobile_no)

    existing = frappe.db.get_value(
        "WhatsApp Conversation",
        {"customer_phone": mobile_no},
        "name",
    )
    if existing:
        if party:
            frappe.db.set_value("WhatsApp Conversation", existing, "customer", party)
        return existing

    if not party:
        customer = find_customer_by_mobile(mobile_no)
        if customer:
            party = customer

    doc = frappe.get_doc({
        "doctype": "WhatsApp Conversation",
        "customer": party,
        "customer_phone": mobile_no,
    })
    doc.insert(ignore_permissions=True)
    frappe.db.commit()
    return doc.name


def save_message(data: dict):
    message_sid = data.get("message_sid")
    if message_sid:
        existing = frappe.db.get_value(
            "Twilio WhatsApp Message",
            {"message_sid": message_sid},
            "name",
        )
        if existing:
            return existing

    raw_payload = data.get("raw_payload", {})
    if not isinstance(raw_payload, str):
        raw_payload = json.dumps(raw_payload, default=str, indent=2)

    doc = frappe.get_doc({
        "doctype": "Twilio WhatsApp Message",
        "conversation": data.get("conversation"),
        "direction": data.get("direction"),
        "message_sid": message_sid,
        "from_number": data.get("from_number"),
        "to_number": data.get("to_number"),
        "message_type": data.get("message_type") or "Text",
        "body": data.get("body"),
        "media_url": data.get("media_url"),
        "media_content_type": data.get("media_content_type"),
        "status": data.get("status"),
        "reference_doctype": data.get("reference_doctype"),
        "reference_name": data.get("reference_name"),
        "error_message": data.get("error_message"),
        "timestamp": data.get("timestamp") or now_datetime(),
        "raw_payload": raw_payload,
    })
    doc.insert(ignore_permissions=True)

    if doc.conversation:
        frappe.db.set_value(
            "WhatsApp Conversation",
            doc.conversation,
            {
                "last_message_at": now_datetime(),
            },
        )

    frappe.db.commit()
    return doc.name