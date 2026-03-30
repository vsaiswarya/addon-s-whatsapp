import frappe
from frappe.model.document import Document
from frappe.utils import get_url


class TwilioWhatsAppSettings(Document):
    def validate(self):
        self.incoming_webhook_url = get_url(
            "/api/method/twilio_whatsapp_custom.api.incoming_webhook"
        )
        self.status_callback_url = get_url(
            "/api/method/twilio_whatsapp_custom.api.status_callback"
        )