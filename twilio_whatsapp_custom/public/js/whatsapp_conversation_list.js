frappe.listview_settings["WhatsApp Conversation"] = {
	onload(listview) {
		listview.page.add_inner_button("Start New Conversation", () => {
			frappe.prompt(
				[
					{
						fieldname: "customer",
						label: "Customer",
						fieldtype: "Link",
						options: "Customer"
					},
					{
						fieldname: "customer_phone",
						label: "Customer Phone",
						fieldtype: "Data",
						reqd: 1
					},
					{
						fieldname: "customer_name",
						label: "Customer Name",
						fieldtype: "Data",
						reqd: 1
					},
					// {
					// 	fieldname: "invoice_no",
					// 	label: "Invoice No",
					// 	fieldtype: "Data",
					// 	reqd: 1
					// }
				],
				(values) => {
					frappe.call({
						method: "twilio_whatsapp_custom.api.start_template_conversation",
						args: {
							customer: values.customer || null,
							customer_phone: values.customer_phone,
							content_sid: "HX94e8b82b9bbcdbecdf328ad25b2b711f",
							content_variables: {
								"1": values.customer_name,
								
							}
						},
						freeze: true,
						freeze_message: "Starting conversation..."
					}).then((r) => {
						const conv = r.message && r.message.conversation;
						if (conv) {
							frappe.set_route("Form", "WhatsApp Conversation", conv);
						}
					});
				},
				"Start New Conversation",
				"Send Template"
			);
		});
	}
};