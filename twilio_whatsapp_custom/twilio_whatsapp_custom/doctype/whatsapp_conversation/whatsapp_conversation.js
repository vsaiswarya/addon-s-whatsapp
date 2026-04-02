frappe.ui.form.on("WhatsApp Conversation", {
	refresh(frm) {
		frm.__chat_state = frm.__chat_state || {
			start: 0,
			limit: 50,
			total: 0,
			loading: false
		};

		frm.__user_reading_old = frm.__user_reading_old || false;

		if (!frm.__chat_ui_built) {
			render_chat_shell(frm);
			frm.__chat_ui_built = true;
		}

		reload_latest(frm);

		if (frm.__wa_timer) clearInterval(frm.__wa_timer);
		frm.__wa_timer = setInterval(() => {
			if (cur_frm && cur_frm.doc && cur_frm.doc.name === frm.doc.name) {
				if (!frm.__user_reading_old) {
					reload_latest(frm);
				}
			}
		}, 5000);
	},

	on_unload(frm) {
		if (frm.__wa_timer) clearInterval(frm.__wa_timer);
		frm.__chat_ui_built = false;
		frm.__new_conversation_button_added = false;
	}
});

function escape_html(value) {
	return frappe.utils.escape_html(value == null ? "" : String(value));
}

function format_message_time(timestamp) {
	if (!timestamp) return "";
	try {
		return frappe.datetime.str_to_user(timestamp);
	} catch (e) {
		return timestamp || "";
	}
}

function extract_last_url(text) {
	if (!text) return null;
	const matches = String(text).match(/https?:\/\/[^\s<]+/g);
	return matches && matches.length ? matches[matches.length - 1] : null;
}

function strip_last_url_line(text) {
	if (!text) return "";
	const lines = String(text).split("\n");
	if (!lines.length) return text;

	const last = lines[lines.length - 1].trim();
	if (/^https?:\/\//i.test(last)) {
		lines.pop();
	}
	return lines.join("\n").trim();
}

function is_template_placeholder_message(m) {
	const body = String(m.body || "").trim();
	return body.startsWith("Template sent (HX") && body.endsWith(")");
}

function render_link_card(url, label = "Open Link") {
	return `
		<div style="
			margin-top:8px;
			border:1px solid rgba(0,0,0,.08);
			border-radius:10px;
			padding:8px 10px;
			background:rgba(255,255,255,.55);
			max-width:100%;
		">
			<div style="
				font-size:12px;
				font-weight:600;
				color:#54656f;
				margin-bottom:4px;
			">
				${escape_html(label)}
			</div>
			<a href="${escape_html(url)}"
				target="_blank"
				style="
					color:#0b57d0;
					text-decoration:underline;
					word-break:break-word;
					overflow-wrap:anywhere;
					display:block;
					line-height:1.35;
					font-size:13px;
				">
				${escape_html(url)}
			</a>
		</div>
	`;
}

function render_pdf_card(url, title) {
	return `
		<div style="
			margin-top:8px;
			border:1px solid rgba(0,0,0,.08);
			border-radius:10px;
			padding:10px 12px;
			background:rgba(255,255,255,.55);
			max-width:100%;
		">
			<div style="
				font-size:13px;
				font-weight:600;
				color:#111b21;
				margin-bottom:6px;
				word-break:break-word;
			">
				📄 ${escape_html(title || "PDF Document")}
			</div>
			<a href="${escape_html(url)}"
				target="_blank"
				style="
					color:#0b57d0;
					text-decoration:underline;
					word-break:break-word;
					overflow-wrap:anywhere;
					display:block;
					line-height:1.35;
					font-size:13px;
				">
				Open PDF
			</a>
		</div>
	`;
}

function render_chat_shell(frm) {
	const wrap = frm.fields_dict.chat_html?.$wrapper;
	if (!wrap) return;

	if (!frm.doc.customer_phone) {
		wrap.html(`<div style="padding:12px; opacity:.7;">Set Customer Phone to view chat.</div>`);
		return;
	}

	const customer_label = frm.doc.customer || frm.doc.customer_name || "Customer";
	const phone_label = frm.doc.customer_phone || "";

	wrap.html(`
		<div style="display:flex; flex-direction:column; gap:10px;">

			<div style="
				padding:12px 14px;
				border:1px solid #e5e7eb;
				border-radius:12px;
				background:#ffffff;
			">
				<div style="font-weight:600; font-size:14px; color:#111b21;">
					${escape_html(customer_label)}
				</div>
				<div style="font-size:12px; color:#667781; margin-top:2px;">
					${escape_html(phone_label)}
				</div>
			</div>

			<div id="wa_box" style="
				padding:14px;
				background:#efeae2;
				border-radius:12px;
				max-height:520px;
				min-height:420px;
				overflow:auto;
				border:1px solid #dfe5e7;
				display:flex;
				flex-direction:column;
				gap:8px;
			">
				<div style="padding:10px; opacity:.7; text-align:center;">Loading…</div>
			</div>

			<div style="display:flex; gap:8px; align-items:flex-end;">
				<textarea id="wa_input" rows="2" style="
					flex:1;
					resize:none;
					padding:10px 12px;
					border:1px solid #d1d7db;
					border-radius:12px;
					background:#fff;
					outline:none;
				" placeholder="Type a message…"></textarea>

				<button class="btn btn-default" id="wa_pdf">PDF</button>
				<button class="btn btn-primary" id="wa_send">Send</button>
			</div>

			<div style="display:flex; justify-content:space-between; align-items:center;">
				<button class="btn btn-default btn-sm" id="wa_load_more">Load older</button>
				<div id="wa_meta" style="font-size:12px; color:#667781;"></div>
			</div>
		</div>
	`);

	const box = wrap.find("#wa_box");

	box.off("scroll").on("scroll", function () {
		const el = this;
		const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
		frm.__user_reading_old = distanceFromBottom > 120;
	});

	wrap.find("#wa_send").off("click").on("click", () => send_from_ui(frm));
	wrap.find("#wa_pdf").off("click").on("click", () => open_pdf_dialog(frm));

	wrap.find("#wa_input").off("keydown").on("keydown", (e) => {
		if (e.key === "Enter" && !e.shiftKey) {
			e.preventDefault();
			send_from_ui(frm);
		}
	});

	wrap.find("#wa_load_more").off("click").on("click", () => {
		load_messages(frm, { append_older: true });
	});
}

function reload_latest(frm) {
	const wrap = frm.fields_dict.chat_html?.$wrapper;
	if (!wrap) return;

	frm.__chat_state.start = 0;
	wrap.find("#wa_box").data("rendered", false);

	load_messages(frm, { append_older: false });
}

function load_messages(frm, { append_older }) {
	const wrap = frm.fields_dict.chat_html?.$wrapper;
	if (!wrap) return;

	const box = wrap.find("#wa_box");
	const meta = wrap.find("#wa_meta");
	const state = frm.__chat_state;

	if (state.loading) return;
	state.loading = true;

	frappe.call({
		method: "twilio_whatsapp_custom.api.get_messages_by_phone",
		args: {
			customer_phone: frm.doc.customer_phone || frm.doc.name,
			conversation: frm.doc.name,
			limit: state.limit,
			start: state.start
		},
		callback: (r) => {
			const resp = r.message || {};
			const msgs = resp.data || [];
			state.total = resp.total || 0;

			const oldScrollHeight = box[0]?.scrollHeight || 0;
			const oldScrollTop = box[0]?.scrollTop || 0;
			const existing = box.data("rendered") ? box.html() : "";

			let html = "";

			if (!msgs.length && !box.data("rendered")) {
				html = `<div style="padding:16px; opacity:.7; text-align:center;">No messages</div>`;
			} else {
				const ordered = msgs.slice().reverse();

				ordered.forEach((m) => {
					const inbound = (m.direction || "").toLowerCase().includes("inbound");
					const timeValue = m.timestamp || m.creation || "";
					const time = format_message_time(timeValue);

					const rowJustify = inbound ? "flex-start" : "flex-end";
					const bubbleBg = inbound ? "#ffffff" : "#d9fdd3";
					const bubbleRadius = inbound
						? "12px 12px 12px 4px"
						: "12px 12px 4px 12px";

					const senderName = inbound
						? (frm.doc.customer || frm.doc.customer_name || "Customer")
						: "You";

					let content_html = "";
					const body = String(m.body || "").trim();
					const mediaUrl = m.media_url ? String(m.media_url).trim() : "";

					// nicer display for template sends
					if (is_template_placeholder_message(m)) {
						content_html += `
							<div style="
								font-size:13px;
								font-weight:600;
								color:#54656f;
							">
								Template message sent
							</div>
						`;
					} else if (body) {
						const pdfFromBody = extract_last_url(body);
						const cleanText = strip_last_url_line(body);

						if (pdfFromBody && /\.pdf(\?|$)/i.test(pdfFromBody)) {
							if (cleanText) {
								content_html += `
									<div style="
										white-space:pre-wrap;
										word-break:break-word;
										overflow-wrap:anywhere;
									">
										${escape_html(cleanText)}
									</div>
								`;
							}
							content_html += render_pdf_card(pdfFromBody, cleanText || "PDF Document");
						} else if (pdfFromBody && /^https?:\/\//i.test(pdfFromBody)) {
							if (cleanText) {
								content_html += `
									<div style="
										white-space:pre-wrap;
										word-break:break-word;
										overflow-wrap:anywhere;
									">
										${escape_html(cleanText)}
									</div>
								`;
							}
							content_html += render_link_card(pdfFromBody, "Link");
						} else {
							content_html += `
								<div style="
									white-space:pre-wrap;
									word-break:break-word;
									overflow-wrap:anywhere;
								">
									${escape_html(body)}
								</div>
							`;
						}
					}

					if (mediaUrl) {
						if (/\.pdf(\?|$)/i.test(mediaUrl)) {
							content_html += render_pdf_card(mediaUrl, body || "PDF Document");
						} else {
							content_html += render_link_card(mediaUrl, "Attachment");
						}
					}

					if (!body && !mediaUrl) {
						content_html += `<div style="opacity:.7;">(empty message)</div>`;
					}

					html += `
						<div style="
							display:flex;
							justify-content:${rowJustify};
							width:100%;
							margin:4px 0;
						">
							<div style="
								display:inline-flex;
								flex-direction:column;
								align-items:flex-start;
								background:${bubbleBg};
								border-radius:${bubbleRadius};
								padding:7px 10px 6px;
								box-shadow:0 1px 1px rgba(0,0,0,.08);
								font-size:14px;
								line-height:1.42;
								color:#111b21;
								width:auto;
								max-width:62%;
								min-width:0;
							">
								<div style="
									font-size:12px;
									font-weight:600;
									color:${inbound ? "#0b57d0" : "#128c7e"};
									margin-bottom:4px;
								">
									${escape_html(senderName)}
								</div>

								<div style="max-width:100%;">
									${content_html}
								</div>

								<div style="
									font-size:11px;
									color:#667781;
									align-self:flex-end;
									margin-top:4px;
									white-space:nowrap;
								">
									${escape_html(time)}
								</div>
							</div>
						</div>
					`;
				});
			}

			if (!box.data("rendered")) {
				box.html(html);
				box.data("rendered", true);
			} else if (append_older) {
				box.html(html + existing);
			} else {
				box.html(html);
			}

			state.start += msgs.length;
			meta.text(`Showing ${Math.min(state.start, state.total)} of ${state.total}`);
			wrap.find("#wa_load_more").prop("disabled", state.start >= state.total);

			if (!append_older) {
				if (!frm.__user_reading_old) {
					box[0].scrollTop = box[0].scrollHeight;
				}
			} else {
				const newScrollHeight = box[0].scrollHeight;
				box[0].scrollTop = oldScrollTop + (newScrollHeight - oldScrollHeight);
			}
		},
		always: () => {
			state.loading = false;
		}
	});
}

function send_from_ui(frm) {
	const wrap = frm.fields_dict.chat_html?.$wrapper;
	if (!wrap) return;

	const input = wrap.find("#wa_input");
	const msg = (input.val() || "").trim();

	if (!msg) return;

	input.val("");

	frappe.call({
		method: "twilio_whatsapp_custom.api.send_message_ui",
		args: {
			phone: frm.doc.customer_phone,
			message: msg
		},
		callback: () => {
			frappe.show_alert({
				message: "Sent",
				indicator: "green"
			});
			frm.__user_reading_old = false;
			reload_latest(frm);
		}
	});
}

function open_pdf_dialog(frm) {
	frappe.prompt(
		[
			{
				fieldname: "file_name",
				label: "PDF File",
				fieldtype: "Link",
				options: "File",
				reqd: 1
			},
			{
				fieldname: "caption",
				label: "Caption",
				fieldtype: "Data"
			}
		],
		(values) => {
			frappe.call({
				method: "twilio_whatsapp_custom.api.send_pdf_file_from_chat",
				args: {
					conversation: frm.doc.name,
					file_name: values.file_name,
					caption: values.caption
				},
				freeze: true,
				freeze_message: "Sending PDF..."
			}).then(() => {
				frappe.show_alert({ message: "PDF sent", indicator: "green" });
				reload_latest(frm);
			});
		},
		"Send PDF",
		"Send"
	);
}

function open_new_conversation_dialog() {
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
			}
		],
		(values) => {
			frappe.call({
				method: "twilio_whatsapp_custom.api.start_template_conversation",
				args: {
					customer: values.customer || null,
					customer_phone: values.customer_phone,
					content_sid: "YOUR_REAL_HX_SID",
					content_variables: {
						"1": values.customer_name
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
}