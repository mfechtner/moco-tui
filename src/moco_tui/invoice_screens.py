"""Invoice screens: list, detail, draft editor, item editor."""

from __future__ import annotations

import copy
import webbrowser

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    Select,
    Static,
    Switch,
    TabbedContent,
    TabPane,
    TextArea,
)

from moco_tui.invoices import (
    INVOICE_STATUSES,
    ITEM_TYPES,
    InvoiceService,
    item_amount,
    net_total,
    plain,
    rich,
)

STATUS_STYLE = {
    "draft": "yellow",
    "created": "white",
    "sent": "cyan",
    "overdue": "bold red",
    "partially_paid": "magenta",
    "paid": "green",
    "ignored": "grey50",
}


def money(v, cur) -> str:
    try:
        s = f"{float(v):,.2f}"
    except (TypeError, ValueError):
        return "–"
    return s.replace(",", "X").replace(".", ",").replace("X", ".") + f" {cur or ''}"


def esc(text) -> str:
    return str(text or "").replace("[", "\\[")


def status_cell(status: str | None) -> str:
    return f"[{STATUS_STYLE.get(status or '', 'white')}]{status or '–'}[/]"


def item_cells(i: int, it: dict, cur: str | None) -> list[str]:
    typ = it.get("type") or ""
    title = it.get("title") or plain(it.get("description"))[:60] or ""
    style = "b" if typ == "title" else ("dim" if typ in ("description", "separator") else "")
    if typ == "item":
        qty = f"{it['quantity']:g}" if isinstance(it.get("quantity"), (int, float)) else ""
        price = money(it.get("unit_price"), "") if it.get("unit_price") is not None else ""
        total = money(item_amount(it) if not it.get("optional") else it.get("net_total"), cur)
    else:
        qty = price = total = ""
    flags = []
    if it.get("optional"):
        flags.append("[yellow]optional[/]")
    if it.get("additional") or it.get("service_type") == "expense":
        flags.append("[cyan]expense[/]")
    shown = f"[{style}]{esc(title)}[/]" if style else esc(title)
    return [str(i), typ, shown, qty, it.get("unit") or "", price, total, " ".join(flags)]


ITEM_COLUMNS = [
    ("#", "i"),
    ("Type", "type"),
    ("Title", "title"),
    ("Qty", "qty"),
    ("Unit", "unit"),
    ("Price", "price"),
    ("Total", "total"),
    ("", "flags"),
]


# --------------------------------------------------------------------------- list
class InvoicesScreen(Screen):
    """All invoices by status. Enter = details."""

    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("enter", "details", "Details", show=True),
        Binding("slash", "filter", "Filter"),
        Binding("o", "open", "Open in MOCO"),
        Binding("r", "reload", "Reload"),
    ]

    def __init__(self, svc: InvoiceService):
        super().__init__()
        self.svc = svc
        self.rows: list[dict] = []
        self.gen = 0

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="top"):
            yield Label("Invoices:")
            yield Select(
                [(s, s) for s in INVOICE_STATUSES], value="draft", allow_blank=False, id="istatus"
            )
            yield Input(placeholder="/ filter …", id="ifilter")
            yield Static("", id="isummary")
        yield DataTable(id="invoices", cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        t = self.query_one("#invoices", DataTable)
        for label, key in [
            ("No.", "no"),
            ("Customer", "cust"),
            ("Title", "title"),
            ("Date", "date"),
            ("Due", "due"),
            ("Net", "net"),
            ("Status", "status"),
        ]:
            t.add_column(label, key=key)
        t.focus()
        self.action_reload()

    @on(Select.Changed, "#istatus")
    def status_changed(self) -> None:
        self.action_reload()

    @on(Input.Changed, "#ifilter")
    def filter_changed(self) -> None:
        self.fill()

    @on(Input.Submitted, "#ifilter")
    def filter_done(self) -> None:
        self.query_one("#invoices", DataTable).focus()

    def action_filter(self) -> None:
        self.query_one("#ifilter", Input).focus()

    def action_reload(self) -> None:
        self.gen += 1
        self.query_one("#isummary", Static).update("Loading …")
        self.load(self.query_one("#istatus", Select).value, self.gen)

    @work(thread=True, exclusive=True)
    def load(self, status: str, gen: int) -> None:
        try:
            rows = self.svc.api.invoices(status)
        except Exception as e:  # noqa: BLE001
            self.app.call_from_thread(
                self.query_one("#isummary", Static).update, f"[red]{esc(e)}[/]"
            )
            return
        if gen == self.gen:
            self.rows = rows
            self.app.call_from_thread(self.fill)

    def fill(self) -> None:
        q = self.query_one("#ifilter", Input).value.strip().lower()
        t = self.query_one("#invoices", DataTable)
        t.clear()
        shown = 0
        for inv in self.rows:
            cust = (inv.get("customer") or {}).get("name") or ""
            hay = f"{inv.get('identifier') or ''} {inv.get('title') or ''} {cust}".lower()
            if q and not all(p in hay for p in q.split()):
                continue
            shown += 1
            t.add_row(
                esc(inv.get("identifier") or "[draft]"),
                esc(cust or "–"),
                esc(inv.get("title")),
                inv.get("date") or "",
                inv.get("due_date") or "",
                money(inv.get("net_total"), inv.get("currency")),
                status_cell(inv.get("status")),
                key=str(inv["id"]),
            )
        total = sum(float(i.get("net_total") or 0) for i in self.rows)
        cur = self.rows[0].get("currency") if self.rows else ""
        self.query_one("#isummary", Static).update(
            f"{shown} of {len(self.rows)} invoices · net {money(total, cur)}"
        )

    def current_id(self) -> int | None:
        t = self.query_one("#invoices", DataTable)
        if not t.row_count:
            return None
        return int(t.coordinate_to_cell_key(t.cursor_coordinate).row_key.value)

    @on(DataTable.RowSelected, "#invoices")
    def selected(self, e: DataTable.RowSelected) -> None:
        self.action_details()

    def action_details(self) -> None:
        iid = self.current_id()
        if iid is not None:
            self.app.push_screen(
                InvoiceScreen(iid, self.svc), lambda changed: changed and self.action_reload()
            )

    def action_open(self) -> None:
        iid = self.current_id()
        if iid is not None:
            webbrowser.open(self.svc.web_url(iid))

    def action_back(self) -> None:
        self.app.pop_screen()


# --------------------------------------------------------------------------- detail
class InvoiceScreen(Screen[bool]):
    """One invoice. Dismisses True if it was changed."""

    BINDINGS = [
        Binding("escape,backspace", "back", "Back"),
        Binding("1", "tab('i_over')", "Overview"),
        Binding("2", "tab('i_items')", "Items"),
        Binding("e", "edit", "Edit draft"),
        Binding("o", "open", "Open in MOCO"),
    ]

    def __init__(self, invoice_id: int, svc: InvoiceService):
        super().__init__()
        self.iid, self.svc = invoice_id, svc
        self.inv: dict | None = None
        self.edit_ok = None
        self.changed = False

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Loading invoice …", id="i_head")
        with TabbedContent(initial="i_over"):
            with TabPane("1 Overview", id="i_over"), VerticalScroll():
                yield Static("", id="i_overview")
            with TabPane("2 Items", id="i_items"):
                yield DataTable(id="i_table", cursor_type="row", zebra_stripes=True)
                yield Static("", id="i_desc", classes="desc")
        yield Footer()

    def on_mount(self) -> None:
        t = self.query_one("#i_table", DataTable)
        for label, key in ITEM_COLUMNS:
            t.add_column(label, key=key)
        self.load()

    @work(thread=True, exclusive=True)
    def load(self) -> None:
        try:
            inv = self.svc.api.invoice(self.iid)
            edit = self.svc.editability(inv)
        except Exception as e:  # noqa: BLE001
            self.app.call_from_thread(
                self.query_one("#i_head", Static).update, f"[red]Could not load: {esc(e)}[/]"
            )
            return
        self.inv, self.edit_ok = inv, edit
        self.app.call_from_thread(self.render_invoice)

    def render_invoice(self) -> None:
        inv, cur = self.inv, self.inv.get("currency")
        hint = (
            "[green]e = edit draft[/]"
            if self.edit_ok.ok
            else f"[dim]read-only: {esc(self.edit_ok.reason)}[/dim]"
        )
        self.query_one("#i_head", Static).update(
            f"[b]{esc(inv.get('identifier') or 'Draft')}[/b]  {esc(inv.get('title'))}   "
            f"{status_cell(inv.get('status'))}   {hint}"
        )
        cust = (inv.get("customer") or {}).get("name") or inv.get("customer_id")
        rows = [
            ("Customer", esc(cust)),
            ("Project", esc((inv.get("project") or {}).get("name") or inv.get("project_id"))),
            ("Date", inv.get("date")),
            ("Due", inv.get("due_date")),
            (
                "Service",
                f"{inv.get('service_period_from') or ''} → {inv.get('service_period_to') or ''}"
                if inv.get("service_period_from")
                else None,
            ),
            ("", ""),
            ("Net", money(inv.get("net_total"), cur)),
            ("VAT", f"{inv.get('tax', '–')} %"),
            ("Discount", f"{inv.get('discount') or 0} %"),
            ("Gross", f"[b]{money(inv.get('gross_total'), cur)}[/b]"),
            ("Tags", esc(", ".join(inv.get("tags") or []))),
        ]
        lines = [
            f"[dim]{k:<10}[/dim] {v if v not in (None, '') else '–'}" if k else "" for k, v in rows
        ]
        if inv.get("recipient_address"):
            lines += ["", "[b u]Recipient[/]", esc(inv["recipient_address"].replace("\r", ""))]
        if inv.get("salutation"):
            lines += ["", "[b u]Intro text[/]", esc(plain(inv["salutation"]))]
        if inv.get("footer"):
            lines += ["", "[b u]Footer text[/]", esc(plain(inv["footer"]))]
        payments = inv.get("payments") or []
        if payments:
            lines += ["", "[b u]Payments[/]"]
            lines += [f"{p.get('date')}  {money(p.get('paid_total'), cur)}" for p in payments]
        self.query_one("#i_overview", Static).update("\n".join(lines))
        t = self.query_one("#i_table", DataTable)
        t.clear()
        for i, it in enumerate(inv.get("items", [])):
            t.add_row(*item_cells(i, it, cur), key=str(i))

    @on(DataTable.RowHighlighted, "#i_table")
    def item_highlighted(self, e: DataTable.RowHighlighted) -> None:
        if e.row_key is None or not self.inv:
            return
        d = plain(self.inv["items"][int(e.row_key.value)].get("description"))
        self.query_one("#i_desc", Static).update(esc(d) if d else "[dim]No description[/dim]")

    def action_tab(self, tab: str) -> None:
        self.query_one(TabbedContent).active = tab

    def action_open(self) -> None:
        webbrowser.open(self.svc.web_url(self.iid))

    def action_back(self) -> None:
        self.dismiss(self.changed)

    def action_edit(self) -> None:
        if not self.inv:
            return
        if not self.edit_ok.ok:
            self.notify(self.edit_ok.reason, severity="warning")
            return
        self.app.push_screen(DraftEditor(self.inv), self.save_edit)

    def save_edit(self, edited: dict | None) -> None:
        if edited is not None:
            self.query_one("#i_head", Static).update("Saving …")
            self.do_save(edited)

    @work(thread=True, exclusive=True)
    def do_save(self, edited: dict) -> None:
        try:
            new, warning = self.svc.replace_draft(self.inv, edited)
        except Exception as e:  # noqa: BLE001
            self.app.call_from_thread(self.notify, f"Save failed: {e}", severity="error")
            self.app.call_from_thread(self.render_invoice)
            return
        self.changed = True
        self.iid = new["id"]
        if warning:
            self.app.call_from_thread(self.notify, warning, severity="warning", timeout=15)
        else:
            self.app.call_from_thread(self.notify, "Draft saved.")
        self.load()


# --------------------------------------------------------------------------- editor
class DraftEditor(Screen[dict | None]):
    """Edit an invoice draft locally. Dismisses with the edited invoice dict or None."""

    BINDINGS = [
        Binding("ctrl+s", "save", "Save"),
        Binding("escape", "cancel", "Cancel"),
        Binding("1", "tab('e_head')", "Header", show=False),
        Binding("2", "tab('e_items')", "Items", show=False),
        Binding("a", "add", "Add item"),
        Binding("e", "edit_item", "Edit item"),
        Binding("delete,d", "delete_item", "Delete"),
        Binding("shift+up,K", "move(-1)", "Move up"),
        Binding("shift+down,J", "move(1)", "Move down"),
    ]

    FIELDS = [
        ("title", "Title"),
        ("date", "Date (YYYY-MM-DD)"),
        ("due_date", "Due date"),
        ("service_period_from", "Service period from"),
        ("service_period_to", "Service period to"),
        ("discount", "Discount %"),
    ]

    def __init__(self, inv: dict):
        super().__init__()
        self.orig = inv
        self.inv = copy.deepcopy(inv)
        self.items: list[dict] = self.inv.get("items", [])
        self.dirty = False

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            "[b]Edit draft[/b]  ·  nothing changes in MOCO until you save (ctrl+s)",
            id="e_bar",
        )
        with TabbedContent(initial="e_items"):
            with TabPane("1 Header & texts", id="e_head"), VerticalScroll(classes="form"):
                for key, label in self.FIELDS:
                    yield Label(label)
                    v = self.inv.get(key)
                    yield Input("" if v is None else str(v), id=f"f_{key}")
                yield Label("Recipient address")
                yield TextArea(
                    (self.inv.get("recipient_address") or "").replace("\r", ""), id="f_recipient"
                )
                yield Label("Intro text")
                yield TextArea(plain(self.inv.get("salutation")), id="f_salutation")
                yield Label("Footer text")
                yield TextArea(plain(self.inv.get("footer")), id="f_footer")
            with TabPane("2 Items", id="e_items"):
                yield DataTable(id="e_table", cursor_type="row", zebra_stripes=True)
                yield Static("", id="e_total", classes="desc")
        yield Footer()

    def on_mount(self) -> None:
        t = self.query_one("#e_table", DataTable)
        for label, key in ITEM_COLUMNS:
            t.add_column(label, key=key)
        self.refill()
        t.focus()

    def check_action(self, action: str, parameters: tuple) -> bool | None:
        # item keys only on the items tab, so typing in header fields is safe
        if action in ("add", "edit_item", "delete_item", "move"):
            return self.query_one(TabbedContent).active == "e_items"
        return True

    @on(TabbedContent.TabActivated)
    def tab_changed(self) -> None:
        self.refresh_bindings()

    def refill(self, cursor: int | None = None) -> None:
        t = self.query_one("#e_table", DataTable)
        t.clear()
        cur = self.inv.get("currency")
        for i, it in enumerate(self.items):
            t.add_row(*item_cells(i, it, cur), key=str(i))
        if cursor is not None and self.items:
            t.move_cursor(row=max(0, min(cursor, len(self.items) - 1)))
        old = net_total(self.orig.get("items", []))
        new = net_total(self.items)
        diff = "" if abs(new - old) < 0.005 else f"   [yellow](was {money(old, cur)})[/]"
        self.query_one("#e_total", Static).update(
            f"Net before discount: [b]{money(new, cur)}[/b]{diff}   "
            "[dim]a add · e/enter edit · d delete · shift+↑↓ move[/dim]"
        )

    def current(self) -> int | None:
        t = self.query_one("#e_table", DataTable)
        return t.cursor_row if t.row_count else None

    # ---- item actions
    @on(DataTable.RowSelected, "#e_table")
    def row_selected(self) -> None:
        self.action_edit_item()

    def action_edit_item(self) -> None:
        n = self.current()
        if n is None:
            return

        def done(it: dict | None) -> None:
            if it is not None:
                self.items[n] = it
                self.dirty = True
                self.refill(n)

        self.app.push_screen(ItemEditor(self.items[n]), done)

    def action_add(self) -> None:
        n = self.current()
        pos = len(self.items) if n is None else n + 1

        def done(it: dict | None) -> None:
            if it is not None:
                self.items.insert(pos, it)
                self.dirty = True
                self.refill(pos)

        self.app.push_screen(ItemEditor({"type": "item", "quantity": 1, "unit": "h"}), done)

    def action_delete_item(self) -> None:
        n = self.current()
        if n is None:
            return
        del self.items[n]
        self.dirty = True
        self.refill(n)

    def action_move(self, step: int) -> None:
        n = self.current()
        if n is None:
            return
        m = n + step
        if 0 <= m < len(self.items):
            self.items[n], self.items[m] = self.items[m], self.items[n]
            self.dirty = True
            self.refill(m)

    def action_tab(self, tab: str) -> None:
        self.query_one(TabbedContent).active = tab

    # ---- save / cancel
    def collect(self) -> dict:
        out = self.inv
        for key, _ in self.FIELDS:
            v = self.query_one(f"#f_{key}", Input).value.strip()
            if key == "discount":
                out[key] = float(v.replace(",", ".")) if v else 0
            else:
                out[key] = v or None
        out["recipient_address"] = self.query_one("#f_recipient", TextArea).text
        for key in ("salutation", "footer"):
            text = self.query_one(f"#f_{key}", TextArea).text
            if text.strip() != plain(self.orig.get(key)).strip():
                out[key] = rich(text)  # only rewrite text that was changed
        out["items"] = self.items
        return out

    def action_save(self) -> None:
        try:
            edited = self.collect()
        except ValueError:
            self.notify("Discount must be a number.", severity="error")
            return
        if not edited.get("title") or not edited.get("date") or not edited.get("due_date"):
            self.notify("Title, date and due date are required.", severity="error")
            return
        if not edited.get("items"):
            self.notify("A draft needs at least one item.", severity="error")
            return
        self.app.push_screen(
            ConfirmBox(
                "Save draft?\n\nMOCO can't edit drafts directly: a new draft is created "
                "and the old one deleted.\nNew draft first, so nothing is lost on errors."
            ),
            lambda ok: ok and self.dismiss(edited),
        )

    def action_cancel(self) -> None:
        if not self.dirty:
            self.dismiss(None)
            return
        self.app.push_screen(
            ConfirmBox("Discard your changes?"), lambda ok: ok and self.dismiss(None)
        )


class ConfirmBox(ModalScreen[bool]):
    BINDINGS = [Binding("y", "yes", "Yes"), Binding("n,escape", "no", "No")]

    def __init__(self, text: str):
        super().__init__()
        self.text = text

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self.text, classes="q")
            with Horizontal(classes="btns"):
                yield Button("Yes  (y)", variant="success", id="yes")
                yield Button("No  (n)", variant="error", id="no")

    def action_yes(self) -> None:
        self.dismiss(True)

    def action_no(self) -> None:
        self.dismiss(False)

    @on(Button.Pressed)
    def pressed(self, e: Button.Pressed) -> None:
        self.dismiss(e.button.id == "yes")


class ItemEditor(ModalScreen[dict | None]):
    """Edit one item. Fields shown depend on the type."""

    BINDINGS = [Binding("ctrl+s", "save", "Save"), Binding("escape", "cancel", "Cancel")]

    def __init__(self, item: dict):
        super().__init__()
        self.item = dict(item)

    def compose(self) -> ComposeResult:
        it = self.item
        num = lambda v: "" if v is None else f"{v:g}" if isinstance(v, (int, float)) else str(v)  # noqa: E731
        with VerticalScroll(classes="dialog wide item-editor"):
            yield Label("[b]Item[/b]")
            yield Label("Type")
            yield Select(
                [(t, t) for t in ITEM_TYPES],
                value=it.get("type") or "item",
                allow_blank=False,
                id="t_type",
            )
            yield Label("Title", classes="f-title")
            yield Input(it.get("title") or "", id="t_title", classes="f-title")
            yield Label("Description  [dim](one line = one bullet)[/dim]", classes="f-desc")
            yield TextArea(plain(it.get("description")), id="t_desc", classes="f-desc")
            with Horizontal(classes="row f-item"):
                with Vertical():
                    yield Label("Quantity")
                    yield Input(num(it.get("quantity")), id="t_qty")
                with Vertical():
                    yield Label("Unit")
                    yield Input(it.get("unit") or "", id="t_unit")
                with Vertical():
                    yield Label("Unit price")
                    yield Input(num(it.get("unit_price")), id="t_price")
            yield Label("…or flat total (leave quantity empty)", classes="f-item")
            yield Input(num(it.get("net_total")), id="t_total", classes="f-item")
            with Horizontal(classes="sw f-item"):
                yield Switch(bool(it.get("optional")), id="t_optional")
                yield Label("Optional (not billed)")
            with Horizontal(classes="sw f-item"):
                yield Switch(
                    bool(it.get("additional") or it.get("service_type") == "expense"),
                    id="t_expense",
                )
                yield Label("Expense")
            with Horizontal(classes="btns"):
                yield Button("OK  (ctrl+s)", variant="success", id="ok")
                yield Button("Cancel  (esc)", id="cancel")

    def on_mount(self) -> None:
        self.show_fields()

    @on(Select.Changed, "#t_type")
    def show_fields(self) -> None:
        t = self.query_one("#t_type", Select).value
        for w in self.query(".f-title"):
            w.display = t in ("item", "title", "subtotal")
        for w in self.query(".f-desc"):
            w.display = t in ("item", "description")
        for w in self.query(".f-item"):
            w.display = t == "item"

    @staticmethod
    def _num(text: str) -> float | None:
        text = text.strip().replace(",", ".")
        return float(text) if text else None

    def action_save(self) -> None:
        q = self.query_one
        t = q("#t_type", Select).value
        it = {"type": t}
        if self.item.get("id"):
            it["id"] = self.item["id"]
        try:
            if t in ("item", "title", "subtotal"):
                it["title"] = q("#t_title", Input).value.strip()
            if t in ("item", "description"):
                text = q("#t_desc", TextArea).text
                same = text.strip() == plain(self.item.get("description")).strip()
                it["description"] = self.item.get("description") if same else rich(text)
            if t == "subtotal":
                it["subtotal_type"] = self.item.get("subtotal_type") or "sub_total"
            if t == "item":
                qty, price = (
                    self._num(q("#t_qty", Input).value),
                    self._num(q("#t_price", Input).value),
                )
                total = self._num(q("#t_total", Input).value)
                if qty is not None and price is not None:
                    it.update(
                        quantity=qty,
                        unit=q("#t_unit", Input).value.strip(),
                        unit_price=price,
                        net_total=round(qty * price, 2),
                    )
                elif total is not None:
                    it["net_total"] = total
                else:
                    self.notify("Set quantity + unit price, or a flat total.", severity="error")
                    return
                if not it["title"]:
                    self.notify("Title is required.", severity="error")
                    return
                it["optional"] = q("#t_optional", Switch).value
                if q("#t_expense", Switch).value:
                    it["additional"] = True
                for k in ("revenue_category", "revenue_category_id"):
                    if self.item.get(k):
                        it[k] = self.item[k]
        except ValueError:
            self.notify("Numbers only in quantity, price and total.", severity="error")
            return
        self.dismiss(it)

    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed)
    def pressed(self, e: Button.Pressed) -> None:
        self.action_save() if e.button.id == "ok" else self.action_cancel()
