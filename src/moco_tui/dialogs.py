"""Small dialogs shared by offer and invoice screens."""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

from platformdirs import user_downloads_dir
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, OptionList, TextArea
from textual.widgets.option_list import Option

OFFER_STATUSES = ["created", "sent", "accepted", "partially_billed", "billed", "archived"]
# MOCO allows these for final invoices (not drafts); "paid" comes from payments
INVOICE_STATUSES_SETTABLE = ["created", "sent", "overdue", "ignored"]


def save_pdf(data: bytes, name: str) -> Path:
    """Save to the OS downloads folder (fallback: home). Never overwrites."""
    folder = Path(user_downloads_dir())
    if not folder.is_dir():
        folder = Path.home()
    safe = re.sub(r"[^\w.-]+", "_", name).strip("_") or "moco"
    path = folder / f"{safe}.pdf"
    n = 2
    while path.exists():
        path = folder / f"{safe}-{n}.pdf"
        n += 1
    path.write_bytes(data)
    return path


def parse_number(text: str) -> float | None:
    text = (text or "").strip().replace(" ", "")
    if not text:
        return None
    if "," in text and "." in text:  # 1.234,56
        text = text.replace(".", "").replace(",", ".")
    else:
        text = text.replace(",", ".")
    return float(text)


def valid_date(text: str) -> bool:
    try:
        date.fromisoformat(text)
        return True
    except ValueError:
        return False


class _Dialog(ModalScreen):
    BINDINGS = [Binding("ctrl+s", "ok", "OK"), Binding("escape", "cancel", "Cancel")]

    def buttons(self, ok: str = "OK") -> ComposeResult:
        with Horizontal(classes="btns"):
            yield Button(f"{ok}  (ctrl+s)", variant="success", id="ok")
            yield Button("Cancel  (esc)", id="cancel")

    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#ok")
    def _ok(self) -> None:
        self.action_ok()

    @on(Button.Pressed, "#cancel")
    def _cancel(self) -> None:
        self.action_cancel()


# --------------------------------------------------------------------------- status
class StatusPicker(_Dialog):
    """Pick a new status. Enter selects."""

    def __init__(self, title: str, current: str | None, options: list[str]):
        super().__init__()
        self.title_text, self.current, self.options = title, current, options

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="dialog"):
            yield Label(f"[b]{self.title_text}[/b]\nNow: [b]{self.current or '–'}[/b]")
            yield OptionList(
                *[Option(("● " if o == self.current else "  ") + o, id=o) for o in self.options],
                id="opts",
            )
            yield Label("[dim]↑↓ choose · enter set · esc cancel[/dim]")

    def on_mount(self) -> None:
        ol = self.query_one(OptionList)
        if self.current in self.options:
            ol.highlighted = self.options.index(self.current)
        ol.focus()

    @on(OptionList.OptionSelected)
    def chosen(self, e: OptionList.OptionSelected) -> None:
        self.dismiss(e.option.id)

    def action_ok(self) -> None:
        ol = self.query_one(OptionList)
        if ol.highlighted is not None:
            self.dismiss(self.options[ol.highlighted])


# --------------------------------------------------------------------------- email
class EmailDialog(_Dialog):
    """Send by email. Empty 'To' = MOCO's default recipients."""

    def __init__(self, what: str, subject: str):
        super().__init__()
        self.what, self.subject = what, subject

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="dialog wide"):
            yield Label(f"[b]Send {self.what} by email[/b]")
            yield Label("To  [dim](empty = default recipients from MOCO · several: a@x;b@y)[/dim]")
            yield Input(id="m_to")
            yield Label("CC")
            yield Input(id="m_cc")
            yield Label("Subject")
            yield Input(self.subject, id="m_subject")
            yield Label("Text")
            yield TextArea(
                "Guten Tag,\n\nanbei erhalten Sie die Unterlagen.\n\nViele Grüße", id="m_text"
            )
            yield from self.buttons("Send")

    def action_ok(self) -> None:
        q = self.query_one
        subject = q("#m_subject", Input).value.strip()
        text = q("#m_text", TextArea).text.strip()
        if not subject or not text:
            self.notify("Subject and text are required.", severity="error")
            return
        self.dismiss(
            {
                "emails_to": q("#m_to", Input).value.strip(),
                "emails_cc": q("#m_cc", Input).value.strip(),
                "subject": subject,
                "text": text,
            }
        )


# --------------------------------------------------------------------------- payment
class PaymentDialog(_Dialog):
    def __init__(self, open_amount: float, currency: str | None):
        super().__init__()
        self.open_amount, self.currency = open_amount, currency or ""

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="dialog"):
            yield Label("[b]Record payment[/b]")
            yield Label("Date")
            yield Input(date.today().isoformat(), id="p_date")
            yield Label(f"Amount ({self.currency})  [dim]default = open amount[/dim]")
            yield Input(f"{self.open_amount:.2f}", id="p_amount")
            yield Label("Note  [dim](optional)[/dim]")
            yield Input(id="p_desc")
            yield from self.buttons("Save payment")

    def action_ok(self) -> None:
        q = self.query_one
        d = q("#p_date", Input).value.strip()
        try:
            amount = parse_number(q("#p_amount", Input).value)
        except ValueError:
            amount = None
        if not valid_date(d):
            self.notify("Date must be YYYY-MM-DD.", severity="error")
            return
        if not amount or amount <= 0:
            self.notify("Amount must be a positive number.", severity="error")
            return
        self.dismiss({"date": d, "paid_total": amount, "description": q("#p_desc", Input).value})


# --------------------------------------------------------------------------- reminder
class ReminderDialog(_Dialog):
    def compose(self) -> ComposeResult:
        today = date.today()
        with VerticalScroll(classes="dialog wide"):
            yield Label("[b]Payment reminder[/b]  [dim]empty title/text = MOCO default[/dim]")
            with Horizontal(classes="row"):
                with VerticalScroll(classes="col"):
                    yield Label("Date")
                    yield Input(today.isoformat(), id="r_date")
                with VerticalScroll(classes="col"):
                    yield Label("Pay by")
                    yield Input((today + timedelta(days=7)).isoformat(), id="r_due")
                with VerticalScroll(classes="col"):
                    yield Label("Fee")
                    yield Input("0", id="r_fee")
            yield Label("Title")
            yield Input(id="r_title")
            yield Label("Text")
            yield TextArea("", id="r_text")
            yield from self.buttons("Create reminder")

    def action_ok(self) -> None:
        q = self.query_one
        d, due = q("#r_date", Input).value.strip(), q("#r_due", Input).value.strip()
        if not (valid_date(d) and valid_date(due)):
            self.notify("Dates must be YYYY-MM-DD.", severity="error")
            return
        try:
            fee = parse_number(q("#r_fee", Input).value) or 0
        except ValueError:
            self.notify("Fee must be a number.", severity="error")
            return
        self.dismiss(
            {
                "date": d,
                "due_date": due,
                "fee": fee,
                "title": q("#r_title", Input).value.strip(),
                "text": q("#r_text", TextArea).text.strip(),
            }
        )


# --------------------------------------------------------------------------- text prompt
class TextPrompt(_Dialog):
    """One required text field, e.g. a delete reason."""

    def __init__(self, title: str, label: str, ok: str = "OK"):
        super().__init__()
        self.title_text, self.label, self.ok = title, label, ok

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="dialog"):
            yield Label(f"[b]{self.title_text}[/b]")
            yield Label(self.label)
            yield Input(id="tp_value")
            yield from self.buttons(self.ok)

    def action_ok(self) -> None:
        v = self.query_one("#tp_value", Input).value.strip()
        if not v:
            self.notify("Required.", severity="error")
            return
        self.dismiss(v)

    @on(Input.Submitted)
    def submitted(self) -> None:
        self.action_ok()
