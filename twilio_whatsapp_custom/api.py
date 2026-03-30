import frappe
from twilio.rest import Client
from frappe.utils import get_url
from frappe.utils.pdf import get_pdf
import json


from twilio_whatsapp_custom.utils import (
    get_settings,
    normalize_number,
    find_or_create_conversation,
    save_message,
    find_customer_by_mobile,
)


def get_client():
    settings = get_settings()

    if not settings.enabled:
        frappe.throw("Twilio WhatsApp Settings is disabled")

    account_sid = (settings.account_sid or "").strip()
    auth_token = settings.get_password("auth_token")
    from_number = (settings.from_whatsapp_number or "").strip()

    if not account_sid or not auth_token or not from_number:
        frappe.throw("Please fill Twilio WhatsApp Settings completely")

    client = Client(account_sid, auth_token)
    return client, settings


@frappe.whitelist()
def send_message(to_number, body=None, media_url=None, reference_doctype=None, reference_name=None):
    client, settings = get_client()

    to_number = normalize_number(to_number)
    from_number = normalize_number(settings.from_whatsapp_number)

    payload = {
        "from_": from_number,
        "to": to_number,
    }

    if body:
        payload["body"] = body

    if media_url:
        payload["media_url"] = [media_url]

    msg = client.messages.create(**payload)

    conversation = find_or_create_conversation(to_number)

    save_message({
        "conversation": conversation,
        "direction": "Outbound",
        "message_sid": msg.sid,
        "from_number": from_number,
        "to_number": to_number,
        "message_type": "Media" if media_url else "Text",
        "body": body,
        "media_url": media_url,
        "status": msg.status,
        "reference_doctype": reference_doctype,
        "reference_name": reference_name,
        "raw_payload": {
            "sid": msg.sid,
            "status": msg.status,
            "to": to_number,
            "from": from_number,
        },
    })

    return {
        "ok": True,
        "sid": msg.sid,
        "status": msg.status,
    }


@frappe.whitelist()
def send_sales_invoice_pdf(sales_invoice, to_number, print_format=None):
    try:
        doc = frappe.get_doc("Sales Invoice", sales_invoice)

        html = frappe.get_print(
            "Sales Invoice",
            sales_invoice,
            print_format=print_format or "Standard",
            doc=doc,
            no_letterhead=1,
        )

        pdf = get_pdf(html)

        file_doc = frappe.get_doc({
            "doctype": "File",
            "file_name": f"{sales_invoice}.pdf",
            "attached_to_doctype": "Sales Invoice",
            "attached_to_name": sales_invoice,
            "content": pdf,
            "is_private": 0,
        })
        file_doc.save(ignore_permissions=True)

        file_url = get_url(file_doc.file_url)

        return send_message(
            to_number=to_number,
            body=f"Invoice {sales_invoice}\nDownload PDF:\n{file_url}",
            media_url=None,
            reference_doctype="Sales Invoice",
            reference_name=sales_invoice,
        )

    except Exception:
        frappe.log_error(frappe.get_traceback(), "Twilio WhatsApp Invoice Error")
        raise


@frappe.whitelist(allow_guest=True)
def incoming_webhook():
    data = frappe.local.form_dict

    frappe.log_error(
        title="Twilio Incoming Webhook Hit",
        message=frappe.as_json(dict(data))
    )

    from_number = normalize_number(data.get("From"))
    to_number = normalize_number(data.get("To"))
    body = data.get("Body")
    sid = data.get("MessageSid")
    num_media = int(data.get("NumMedia") or 0)

    media_url = None
    media_content_type = None

    if num_media > 0:
        media_url = data.get("MediaUrl0")
        media_content_type = data.get("MediaContentType0")

    customer = find_customer_by_mobile(from_number)
    conv = find_or_create_conversation(from_number, party=customer)

    frappe.db.set_value(
        "WhatsApp Conversation",
        conv,
        {
            "customer": customer,
            "customer_phone": from_number,
            "twilio_phone": to_number,
            "last_message_at": frappe.utils.now(),
        },
    )

    save_message({
        "conversation": conv,
        "direction": "Inbound",
        "message_sid": sid,
        "from_number": from_number,
        "to_number": to_number,
        "message_type": "Media" if media_url else "Text",
        "body": body,
        "media_url": media_url,
        "media_content_type": media_content_type,
        "status": "received",
        "timestamp": frappe.utils.now(),
        "raw_payload": dict(data),
    })

    frappe.db.commit()
    frappe.local.response["type"] = "txt"
    return "OK"


@frappe.whitelist()
def send_message_ui(phone, message):
    phone = normalize_number(phone)
    result = send_message(to_number=phone, body=message)

    conv = frappe.db.get_value(
        "WhatsApp Conversation",
        {"customer_phone": phone},
        "name",
    )

    if conv:
        settings = get_settings()
        frappe.db.set_value(
            "WhatsApp Conversation",
            conv,
            {
                "customer_phone": phone,
                "twilio_phone": normalize_number(settings.from_whatsapp_number),
                "last_message_at": frappe.utils.now(),
            },
        )

    return result

@frappe.whitelist(allow_guest=True)
def status_callback():
    form = frappe.local.form_dict

    sid = form.get("MessageSid")
    status = form.get("MessageStatus")
    error_message = form.get("ErrorMessage")

    if sid:
        name = frappe.db.get_value("WhatsApp Message", {"message_sid": sid}, "name")
        if name:
            frappe.db.set_value(
                "WhatsApp Message",
                name,
                {
                    "status": status,
                    "error_message": error_message,
                },
            )

    frappe.local.response["type"] = "txt"
    return "OK"



@frappe.whitelist()
def get_messages_by_phone(customer_phone=None, limit=50, start=0, conversation=None):
    limit = int(limit or 50)
    start = int(start or 0)

    conv_name = None

    if conversation:
        conv_name = conversation
    elif customer_phone:
        customer_phone = normalize_number(customer_phone)
        conv_name = frappe.db.get_value(
            "WhatsApp Conversation",
            {"customer_phone": customer_phone},
            "name"
        )

        if not conv_name and frappe.db.exists("WhatsApp Conversation", customer_phone):
            conv_name = customer_phone

    if not conv_name:
        return {"data": [], "total": 0}

    total = frappe.db.count("WhatsApp Message", {"conversation": conv_name})

    data = frappe.get_all(
        "WhatsApp Message",
        filters={"conversation": conv_name},
        fields=[
            "name",
            "body",
            "direction",
            "timestamp",
            "creation",
            "status",
            "message_sid",
            "media_url",
            "media_content_type",
            "from_number",
            "to_number"
        ],
        order_by="creation desc",
        start=start,
        page_length=limit
    )

    return {"data": data, "total": total}


@frappe.whitelist()
def send_pdf_file_from_chat(conversation, file_name, caption=None):
    conversation_doc = frappe.get_doc("WhatsApp Conversation", conversation)
    to_number = conversation_doc.customer_phone

    file_doc = frappe.get_doc("File", file_name)

    if not file_doc.file_url:
        frappe.throw("Selected file has no file URL")

    if "/private/files/" in (file_doc.file_url or ""):
        frappe.throw("Selected file is private. Please choose a public PDF from /files/")

    if not (file_doc.file_name or "").lower().endswith(".pdf"):
        frappe.throw("Selected file is not a PDF")

    full_url = get_url(file_doc.file_url)

    return send_message(
        to_number=to_number,
        body=caption or (file_doc.file_name or "PDF Document"),
        media_url=full_url,
        reference_doctype=file_doc.attached_to_doctype,
        reference_name=file_doc.attached_to_name,
    )



@frappe.whitelist()
def send_template_message(to_number, content_sid, content_variables=None):
    settings = get_settings()

    if not settings.enabled:
        frappe.throw("Twilio WhatsApp Settings is disabled")

    account_sid = (settings.account_sid or "").strip()
    auth_token = settings.get_password("auth_token")
    from_number = normalize_number(settings.from_whatsapp_number)
    to_number = normalize_number(to_number)

    if not account_sid or not auth_token or not from_number:
        frappe.throw("Please fill Twilio WhatsApp Settings completely")

    client = Client(account_sid, auth_token)

    msg = client.messages.create(
        from_=from_number,
        to=to_number,
        content_sid=content_sid,
        content_variables=json.dumps(content_variables or {})
    )

    customer = find_customer_by_mobile(to_number)
    conv = find_or_create_conversation(to_number, party=customer)

    frappe.db.set_value(
        "WhatsApp Conversation",
        conv,
        {
            "customer": customer,
            "customer_phone": to_number,
            "twilio_phone": from_number,
            "last_message_at": frappe.utils.now(),
        },
    )

    save_message({
        "conversation": conv,
        "direction": "Outbound",
        "message_sid": msg.sid,
        "from_number": from_number,
        "to_number": to_number,
        "message_type": "Template",
        "body": f"Template sent ({content_sid})",
        "status": msg.status,
        "timestamp": frappe.utils.now(),
        "raw_payload": {
            "sid": msg.sid,
            "status": msg.status,
            "content_sid": content_sid,
            "content_variables": content_variables or {},
        },
    })

    frappe.db.commit()

    return {
        "ok": True,
        "sid": msg.sid,
        "status": msg.status,
    }

@frappe.whitelist()
def start_template_conversation(customer_phone, content_sid, customer=None, content_variables=None):
    import json

    settings = get_settings()

    if not settings.enabled:
        frappe.throw("Twilio WhatsApp Settings is disabled")

    account_sid = (settings.account_sid or "").strip()
    auth_token = settings.get_password("auth_token")
    from_number = normalize_number(settings.from_whatsapp_number)
    customer_phone = normalize_number(customer_phone)

    if not account_sid or not auth_token or not from_number:
        frappe.throw("Please fill Twilio WhatsApp Settings completely")

    if isinstance(content_variables, str):
        content_variables = json.loads(content_variables or "{}")

    if not customer:
        customer = find_customer_by_mobile(customer_phone)

    conv = find_or_create_conversation(customer_phone, party=customer)

    frappe.db.set_value(
        "WhatsApp Conversation",
        conv,
        {
            "customer": customer,
            "customer_phone": customer_phone,
            "twilio_phone": from_number,
            "last_message_at": frappe.utils.now(),
        },
    )

    client = Client(account_sid, auth_token)

    msg = client.messages.create(
        from_=from_number,
        to=customer_phone,
        content_sid=content_sid,
        content_variables=json.dumps(content_variables or {})
    )

    save_message({
        "conversation": conv,
        "direction": "Outbound",
        "message_sid": msg.sid,
        "from_number": from_number,
        "to_number": customer_phone,
        "message_type": "Template",
        "body": f"Template sent ({content_sid})",
        "status": msg.status,
        "timestamp": frappe.utils.now(),
        "raw_payload": {
            "sid": msg.sid,
            "status": msg.status,
            "content_sid": content_sid,
            "content_variables": content_variables or {},
        },
    })

    frappe.db.commit()

    return {
        "conversation": conv,
        "sid": msg.sid,
        "status": msg.status
    }