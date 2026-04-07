import re
import json
import frappe
from frappe.utils import get_url, now
from frappe.utils.pdf import get_pdf
from twilio_whatsapp_custom.utils import get_settings, normalize_number
from twilio.rest import Client


def send_sales_invoice_whatsapp(doc, method=None):
    try:
        if doc.docstatus != 1:
            return

        customer_number = get_customer_whatsapp_number(doc.customer)
        if not customer_number:
            frappe.log_error(
                title="Sales Invoice WhatsApp",
                message=f"No WhatsApp number found for Customer {doc.customer} / Invoice {doc.name}"
            )
            return

        file_doc = create_invoice_pdf_file(
                doc,
                print_format="Addon-S Tax Invoice",   
                no_letterhead=0,
                letterhead=None,
                lang="en"
            )

        if not file_doc or not file_doc.file_url:
            frappe.log_error(
                title="Sales Invoice WhatsApp",
                message=f"PDF file was not created for Sales Invoice {doc.name}"
            )
            return

        file_url = get_full_public_url(file_doc.file_url)

        send_whatsapp_with_pdf(
            to_number=customer_number,
            media_url=file_url,
            reference_doctype=doc.doctype,
            reference_name=doc.name,
            customer=doc.customer
        )

        frappe.logger().info(f"WhatsApp invoice sent for {doc.name} to {customer_number}")

    except Exception:
        frappe.log_error(
            title="Sales Invoice WhatsApp Error",
            message=frappe.get_traceback()
        )


def get_customer_whatsapp_number(customer):
    contacts = frappe.db.sql("""
        SELECT
            c.name,
            c.mobile_no,
            c.phone
        FROM `tabContact` c
        INNER JOIN `tabDynamic Link` dl
            ON dl.parent = c.name
        WHERE dl.link_doctype = 'Customer'
          AND dl.link_name = %s
        ORDER BY c.is_primary_contact DESC, c.modified DESC
    """, (customer,), as_dict=True)

    for c in contacts:
        if c.mobile_no:
            return normalize_number(c.mobile_no)
        if c.phone:
            return normalize_number(c.phone)

        phone_rows = frappe.get_all(
            "Contact Phone",
            filters={"parent": c.name},
            fields=["phone", "is_primary_mobile_no", "is_primary_phone"],
            order_by="is_primary_mobile_no desc, is_primary_phone desc"
        )
        for p in phone_rows:
            if p.phone:
                return normalize_number(p.phone)

    addresses = frappe.db.sql("""
        SELECT
            a.name,
            a.phone
        FROM `tabAddress` a
        INNER JOIN `tabDynamic Link` dl
            ON dl.parent = a.name
        WHERE dl.link_doctype = 'Customer'
          AND dl.link_name = %s
        ORDER BY a.modified DESC
    """, (customer,), as_dict=True)

    for a in addresses:
        if a.phone:
            return normalize_number(a.phone)

    return None


def create_invoice_pdf_file(doc, print_format=None, no_letterhead=0, letterhead=None, lang="en"):
    """
    Generate the exact Sales Invoice PDF at submit time
    using the same print format you want from ERPNext UI.
    """

    print_format = print_format or "Standard"

    pdf = frappe.get_print(
        doc.doctype,
        doc.name,
        print_format=print_format,
        as_pdf=True,
        no_letterhead=no_letterhead,
        letterhead=letterhead
    )

    file_name = f"{doc.name}.pdf"

    old_files = frappe.get_all(
        "File",
        filters={
            "attached_to_doctype": doc.doctype,
            "attached_to_name": doc.name,
            "file_name": file_name
        },
        fields=["name"]
    )
    for f in old_files:
        frappe.delete_doc("File", f.name, ignore_permissions=True, force=1)

    file_doc = frappe.get_doc({
        "doctype": "File",
        "file_name": file_name,
        "attached_to_doctype": doc.doctype,
        "attached_to_name": doc.name,
        "is_private": 0,
        "content": pdf
    })
    file_doc.save(ignore_permissions=True)

    return file_doc


def get_full_public_url(file_url):
    base_url = get_url().rstrip("/")
    public_base_url = frappe.conf.get("public_base_url")

    if public_base_url:
        base_url = public_base_url.rstrip("/")

    return f"{base_url}{file_url}"


def get_or_create_whatsapp_conversation(customer, customer_number, twilio_number):
    customer_number = normalize_number(customer_number)
    twilio_number = normalize_number(twilio_number) if twilio_number else ""

    existing = frappe.db.get_value(
        "WhatsApp Conversation",
        {"customer_phone": customer_number},
        "name"
    )

    if existing:
        if twilio_number:
            frappe.db.set_value(
                "WhatsApp Conversation",
                existing,
                "twilio_phone",
                twilio_number
            )
        return existing

    rows = frappe.get_all(
        "WhatsApp Conversation",
        fields=["name", "customer_phone"],
        limit=500
    )

    for row in rows:
        try:
            if normalize_number(row.customer_phone) == customer_number:
                if twilio_number:
                    frappe.db.set_value(
                        "WhatsApp Conversation",
                        row.name,
                        "twilio_phone",
                        twilio_number
                    )
                return row.name
        except Exception:
            pass

    try:
        conv = frappe.get_doc({
            "doctype": "WhatsApp Conversation",
            "customer": customer,
            "customer_phone": customer_number,
            "twilio_phone": twilio_number,
            "last_message_at": now()
        })
        conv.insert(ignore_permissions=True)
        return conv.name

    except frappe.UniqueValidationError:
        existing = frappe.db.get_value(
            "WhatsApp Conversation",
            {"customer_phone": customer_number},
            "name"
        )
        if existing and twilio_number:
            frappe.db.set_value(
                "WhatsApp Conversation",
                existing,
                "twilio_phone",
                twilio_number
            )
        if existing:
            return existing
        raise


def send_whatsapp_with_pdf(
    to_number,
    message=None,
    media_url=None,
    reference_doctype=None,
    reference_name=None,
    customer=None
):
    settings = get_settings()

    if not settings.enabled:
        frappe.throw("Twilio WhatsApp Settings is disabled")

    account_sid = (settings.account_sid or "").strip()
    auth_token = settings.get_password("auth_token")
    messaging_service_sid = "MG7c93133f83bbb334b0a6a9a195d37e14"
    content_sid = "HX5d9e10eeb08b249591c5b167ba2e1b8e"

    from_number = normalize_number(settings.from_whatsapp_number)
    if from_number and not from_number.startswith("whatsapp:"):
        from_number = f"whatsapp:{from_number}"

    client = Client(account_sid, auth_token)

    to_number = normalize_number(to_number)
    if not to_number.startswith("whatsapp:"):
        to_number = f"whatsapp:{to_number}"

    invoice_name = reference_name or ""
    public_pdf_url = media_url or ""

    msg = client.messages.create(
    from_=from_number,
    messaging_service_sid=messaging_service_sid,
    to=to_number,
    content_sid=content_sid,
    content_variables=json.dumps({
        "1": invoice_name,
        "2": public_pdf_url
    })
    )

    conversation = None
    if customer:
        conversation = get_or_create_whatsapp_conversation(
            customer=customer,
            customer_number=to_number,
            twilio_number=from_number
        )

    try:
        display_body = (
            f"Dear Customer, your Sales Invoice {invoice_name} is attached for your reference. "
            f"Please let us know if you need any assistance. "
            f"Thank you."
        )

        frappe.get_doc({
            "doctype": "Twilio WhatsApp Message",
            "conversation": conversation,
            "direction": "Outbound",
            "to_number": to_number,
            "from_number": msg.from_ or from_number or "",
            "body": display_body,
            "media_url": public_pdf_url,
            "message_sid": msg.sid,
            "status": msg.status,
            "timestamp": now(),
            "raw_payload": frappe.as_json({
                "sid": msg.sid,
                "status": msg.status,
                "from": msg.from_,
                "to": msg.to,
                "content_sid": content_sid,
                "content_variables": {
                    "1": invoice_name,
                    "2": public_pdf_url
                }
            })
        }).insert(ignore_permissions=True)
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Twilio WhatsApp Message Log Error")

    return msg