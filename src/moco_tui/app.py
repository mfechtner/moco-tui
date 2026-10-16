"""Textual app."""

from __future__ import annotations

import webbrowser

from textual import on, work
from textual.app import App, ComposeResult
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
    RichLog,
    Select,
    Static,
    Switch,
    TextArea,
)

from moco_tui import __version__, ai
from moco_tui.api import Moco
from moco_tui.service import HAS_DRAFT, INVOICED, NO_CUSTOMER, READY, Service, build_invoice
from moco_tui.store import Settings, Store

STATUSES = ["accepted", "sent", "created", "partially_billed", "billed"]

STATE = {  # key -> (label, style)
    "checking": ("…  checking", "grey50"),
    READY: ("●  READY", "green"),
    HAS_DRAFT: ("✓  has draft", "cyan"),
    INVOICED: ("✓  invoiced", "cyan"),
    NO_CUSTOMER: ("✗  no customer", "red"),
    "created": ("★  CREATED", "bold green"),
    "dry": ("◌  dry run ok", "yellow"),
    "error": ("✗  ERROR", "bold red"),
}


def money(v, cur) -> str:
    try:
        s = f"{float(v):,.2f}"
    except (TypeError, ValueError):
        return "–"
    return s.replace(",", "X").replace(".", ",").replace("X", ".") + f" {cur or ''}"


def open_url(url: str) -> None:
    webbrowser.open(url)


# --------------------------------------------------------------------------- dialogs
class Confirm(ModalScreen[bool]):
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


# --------------------------------------------------------------------------- settings
class SettingsScreen(Screen[Settings | None]):
    """Setup wizard (first run) and settings."""

    BINDINGS = [Binding("escape", "cancel", "Back"), Binding("ctrl+s", "save", "Save")]

    def __init__(self, cfg: Settings, first_run: bool = False):
        super().__init__()
        self.cfg = cfg
        self.first_run = first_run

    def compose(self) -> ComposeResult:
        c = self.cfg
        yield Header()
        with VerticalScroll(id="form"):
            if self.first_run:
                yield Static("[b]Welcome![/b] Connect your MOCO account.", classes="intro")
            yield Label("MOCO domain  [dim](yourcompany → yourcompany.mocoapp.com)[/dim]")
            yield Input(c.domain, placeholder="yourcompany", id="domain")
            yield Label("API key  [dim](MOCO → Profile → Integrations)[/dim]")
            yield Input(c.api_key, password=True, id="api_key")
            yield Button("Test connection", id="test")
            yield Static("", id="test_result")
            yield Label("Offer status to pick up")
            yield Select(
                [(s, s) for s in STATUSES],
                value=c.offer_status,
                allow_blank=False,
                id="offer_status",
            )
            yield Label("Days until due")
            yield Input(str(c.due_days), type="integer", id="due_days")
            yield Label("Invoice title prefix")
            yield Input(c.title_prefix, id="title_prefix")
            yield Label("Duplicate-check tag prefix")
            yield Input(c.tag_prefix, id="tag_prefix")
            with Horizontal(classes="sw"):
                yield Switch(c.include_optional, id="include_optional")
                yield Label("Copy optional items")
            with Horizontal(classes="sw"):
                yield Switch(c.mark_offer_billed, id="mark_offer_billed")
                yield Label("Set offer to 'billed' after draft")
            yield Static("\n[b]AI[/b]  [dim]optional[/dim]", classes="section")
            prov = ai.detect_provider(c.ai_provider, c.ai_base_url, c.ai_model)
            yield Label("Provider")
            yield Select(
                [(p.label, p.key) for p in ai.PROVIDERS.values()],
                value=prov or Select.NULL,
                prompt="Choose …",
                id="ai_provider",
            )
            yield Label("Endpoint URL  [dim](empty = provider default)[/dim]")
            yield Input(c.ai_base_url, placeholder="provider default", id="ai_base_url")
            yield Label("API key  [dim](empty for local models)[/dim]")
            yield Input(c.ai_api_key, password=True, id="ai_api_key")
            yield Label("Model")
            yield Input(c.ai_model, placeholder="model name", id="ai_model")
            yield Label("Language of invoice texts")
            yield Input(c.ai_language, id="ai_language")
            yield Button("Test AI", id="test_ai")
            yield Static("", id="test_ai_result")
            with Horizontal(classes="btns"):
                yield Button("Save  (ctrl+s)", variant="success", id="save")
                if not self.first_run:
                    yield Button("Cancel  (esc)", id="cancel")
        yield Footer()

    def read_form(self) -> Settings:
        q = self.query_one
        due = q("#due_days", Input).value
        return Settings(
            domain=q("#domain", Input).value.strip(),
            api_key=q("#api_key", Input).value.strip(),
            offer_status=q("#offer_status", Select).value,
            due_days=int(due) if due else 14,
            include_optional=q("#include_optional", Switch).value,
            mark_offer_billed=q("#mark_offer_billed", Switch).value,
            title_prefix=q("#title_prefix", Input).value,
            tag_prefix=q("#tag_prefix", Input).value or "Angebot",
            ai_provider=(
                "" if q("#ai_provider", Select).is_blank() else q("#ai_provider", Select).value
            ),
            ai_base_url=q("#ai_base_url", Input).value.strip(),
            ai_api_key=q("#ai_api_key", Input).value.strip(),
            ai_model=q("#ai_model", Input).value.strip(),
            ai_language=q("#ai_language", Input).value.strip() or "Deutsch",
            ai_lookback_days=self.cfg.ai_lookback_days,
        )

    @on(Button.Pressed, "#test")
    def test(self) -> None:
        self.query_one("#test_result", Static).update("[dim]Testing …[/dim]")
        self.run_test(self.read_form())

    @work(thread=True, exclusive=True)
    def run_test(self, cfg: Settings) -> None:
        out = self.query_one("#test_result", Static)
        try:
            p = Moco(cfg.domain, cfg.api_key).profile()
            msg = f"[green]✓ Connected as {p.get('firstname', '')} {p.get('lastname', '')}[/]"
        except Exception as e:  # noqa: BLE001
            msg = f"[red]✗ {e}[/]"
        self.app.call_from_thread(out.update, msg)

    @on(Select.Changed, "#ai_provider")
    def provider_changed(self, e: Select.Changed) -> None:
        p = (
            ai.PROVIDERS.get(e.value)
            if not self.query_one("#ai_provider", Select).is_blank()
            else None
        )
        if not p:
            return
        url = self.query_one("#ai_base_url", Input)
        url.placeholder = p.base_url or "https://…/v1"
        # clear a URL that belongs to another provider preset
        if url.value and any(url.value.rstrip("/") == x.base_url for x in ai.PROVIDERS.values()):
            url.value = ""
        model = self.query_one("#ai_model", Input)
        model.placeholder = p.model_hint
        if not model.value and p.key == "anthropic":
            model.value = p.model_hint

    @on(Button.Pressed, "#test_ai")
    def test_ai(self) -> None:
        self.query_one("#test_ai_result", Static).update("[dim]Asking the model …[/dim]")
        self.run_test_ai(self.read_form())

    @work(thread=True, exclusive=True, group="ai")
    def run_test_ai(self, cfg: Settings) -> None:
        out = self.query_one("#test_ai_result", Static)
        try:
            if not cfg.ai_ready:
                raise ai.AIError("Provider and model are required.")
            client = ai.AIClient(
                cfg.ai_base_url, cfg.ai_api_key, cfg.ai_model, timeout=30, provider=cfg.ai_provider
            )
            reply = client.chat("Reply with exactly: OK", "Ping")
            who = f"{client.provider.label} · {cfg.ai_model}"
            msg = f"[green]✓ {who} answered: {reply.strip()[:30]}[/]"
        except Exception as e:  # noqa: BLE001
            msg = f"[red]✗ {e}[/]"
        self.app.call_from_thread(out.update, msg)

    @on(Button.Pressed, "#save")
    def action_save(self) -> None:
        cfg = self.read_form()
        if not cfg.complete:
            self.notify("Domain and API key are required.", severity="error")
            return
        self.dismiss(cfg)

    @on(Button.Pressed, "#cancel")
    def action_cancel(self) -> None:
        if not self.first_run:
            self.dismiss(None)


# --------------------------------------------------------------------------- history
class HistoryScreen(Screen):
    """Drafts created by this tool (local SQLite)."""

    BINDINGS = [Binding("escape,h", "app.pop_screen", "Back"), Binding("o", "open", "Open in MOCO")]

    def __init__(self, store: Store, svc: Service):
        super().__init__()
        self.store, self.svc = store, svc

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("[b]History[/b]  ·  drafts created with this tool", classes="bar")
        yield DataTable(id="hist", cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        t = self.query_one(DataTable)
        t.add_columns("Created", "Offer", "Customer", "Title", "Net", "Draft ID")
        rows = self.store.history()
        for r in rows:
            t.add_row(
                r["created_at"][:16].replace("T", " "),
                r["offer_identifier"],
                r["customer"] or "–",
                r["offer_title"] or "",
                money(r["net_total"], r["currency"]),
                str(r["invoice_id"]),
                key=str(r["invoice_id"]),
            )
        if not rows:
            self.query_one(".bar", Static).update("[b]History[/b]  ·  nothing yet")

    def action_open(self) -> None:
        t = self.query_one(DataTable)
        if t.row_count:
            key = t.coordinate_to_cell_key(t.cursor_coordinate).row_key.value
            open_url(self.svc.web_url("invoices", int(key)))


# --------------------------------------------------------------------------- AI review
class EditItem(ModalScreen[tuple[str, str] | None]):
    """Edit title + description of one suggestion."""

    BINDINGS = [Binding("ctrl+s", "save", "Save"), Binding("escape", "cancel", "Cancel")]

    def __init__(self, title: str, description: str):
        super().__init__()
        self.t, self.d = title, description

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog wide"):
            yield Label("[b]Title[/b]")
            yield Input(self.t, id="e_title")
            yield Label("[b]Description[/b]  [dim](one line = one bullet)[/dim]")
            yield TextArea(self.d, id="e_desc")
            with Horizontal(classes="btns"):
                yield Button("Save  (ctrl+s)", variant="success", id="save")
                yield Button("Cancel  (esc)", id="cancel")

    def action_save(self) -> None:
        self.dismiss(
            (self.query_one("#e_title", Input).value, self.query_one("#e_desc", TextArea).text)
        )

    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed)
    def pressed(self, e: Button.Pressed) -> None:
        self.action_save() if e.button.id == "save" else self.action_cancel()


class AIReviewScreen(Screen):
    """Review AI suggestions per item. Dismisses with list, 'regenerate', 'clear' or None."""

    BINDINGS = [
        Binding("space", "toggle", "Accept/skip"),
        Binding("u", "use_qty", "Use qty"),
        Binding("e", "edit", "Edit"),
        Binding("g", "regenerate", "Regenerate"),
        Binding("x", "clear", "Remove all"),
        Binding("ctrl+s", "save", "Save"),
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, offer: dict, suggestions: list[ai.Suggestion]):
        super().__init__()
        self.offer = offer
        self.sugg = suggestions
        self.items = offer.get("items", [])

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            f"[b]AI suggestions[/b]  ·  {self.offer.get('identifier')}  "
            f"{self.offer.get('title')}  ·  [dim]nothing is sent until you save[/dim]",
            classes="bar",
        )
        with Horizontal(id="main"):
            yield DataTable(id="sugg", cursor_type="row", zebra_stripes=True)
            with VerticalScroll(id="preview"):
                yield Static("", id="detail")
        yield Footer()

    def on_mount(self) -> None:
        t = self.query_one(DataTable)
        t.add_column("✓", key="acc", width=2)
        t.add_column("Item (new title)", key="title")
        t.add_column("Offered", key="off")
        t.add_column("Booked", key="booked")
        t.add_column("Qty", key="qty", width=14)
        t.add_column("Note", key="note")
        for n, s in enumerate(self.sugg):
            t.add_row(*self.cells(s), key=str(n))
        t.focus()

    def cells(self, s: ai.Suggestion) -> list[str]:
        unit = s.unit or ""
        off = f"{s.offered_quantity:g} {unit}" if s.offered_quantity is not None else "–"
        booked = f"{s.booked_hours:g} h" if s.booked_hours is not None else "–"
        if s.quantity is None:
            qty = "[dim]keep[/dim]"
        elif s.use_quantity:
            qty = f"[b green]→ {s.quantity:g} {unit}[/]"
        else:
            qty = f"[dim]{s.quantity:g} (u)[/dim]"
        warn = (
            s.quantity is not None
            and s.offered_quantity
            and abs(s.quantity - float(s.offered_quantity)) > 0.01
        )
        note = f"[yellow]{s.note}[/]" if warn else s.note
        return ["[b green]■[/]" if s.accepted else "□", s.title, off, booked, qty, note]

    def refresh_row(self, n: int) -> None:
        t = self.query_one(DataTable)
        for key, val in zip(
            ["acc", "title", "off", "booked", "qty", "note"], self.cells(self.sugg[n]), strict=True
        ):
            t.update_cell(str(n), key, val)
        self.show_detail(n)

    def current(self) -> int | None:
        t = self.query_one(DataTable)
        return t.cursor_row if t.row_count else None

    @on(DataTable.RowHighlighted)
    def highlighted(self, e: DataTable.RowHighlighted) -> None:
        if e.row_key is not None:
            self.show_detail(int(e.row_key.value))

    def show_detail(self, n: int) -> None:
        s = self.sugg[n]
        orig = self.items[s.index] if s.index < len(self.items) else {}
        old_desc = ai.strip_html(orig.get("description")) or "[dim]–[/dim]"
        lines = [
            "[b u]Before (offer)[/]",
            f"[b]{orig.get('title', '')}[/b]",
            old_desc,
            "",
            "[b u]After (invoice)[/]" + ("" if s.accepted else "  [red](skipped)[/]"),
            f"[b]{s.title}[/b]",
            s.description or "[dim]–[/dim]",
            "",
        ]
        if s.booked_hours is not None:
            lines.append(f"Booked time: [b]{s.booked_hours:g} h[/b]")
        if s.note:
            lines.append(f"[yellow]{s.note}[/]")
        lines.append("\n[dim]space accept · u use qty · e edit · g regenerate[/dim]")
        self.query_one("#detail", Static).update("\n".join(lines))

    def action_toggle(self) -> None:
        n = self.current()
        if n is not None:
            self.sugg[n].accepted = not self.sugg[n].accepted
            self.refresh_row(n)

    def action_use_qty(self) -> None:
        n = self.current()
        if n is None:
            return
        s = self.sugg[n]
        if s.quantity is None:
            self.notify("No hour-based quantity for this item.", severity="warning")
            return
        s.use_quantity = not s.use_quantity
        self.refresh_row(n)

    def action_edit(self) -> None:
        n = self.current()
        if n is None:
            return

        def done(res: tuple[str, str] | None) -> None:
            if res:
                self.sugg[n].title, self.sugg[n].description = res[0].strip(), res[1].strip()
                self.sugg[n].accepted = True
                self.refresh_row(n)

        self.app.push_screen(EditItem(self.sugg[n].title, self.sugg[n].description), done)

    def action_save(self) -> None:
        self.dismiss(self.sugg)

    def action_regenerate(self) -> None:
        self.dismiss("regenerate")

    def action_clear(self) -> None:
        self.dismiss("clear")

    def action_cancel(self) -> None:
        self.dismiss(None)


# --------------------------------------------------------------------------- main
class MocoApp(App):
    TITLE = "MOCO · Offers → Invoice drafts"
    SUB_TITLE = f"v{__version__}"

    CSS = """
    #top { height: 3; padding: 0 1; }
    #top Label { padding: 1 1 0 0; }
    #status { width: 26; }
    #filter { width: 30; }
    #summary { padding: 1 0 0 2; color: $accent; }
    #mode { padding: 1 0 0 2; }
    #main { height: 1fr; }
    #offers { width: 3fr; }
    #preview { width: 2fr; border-left: tall $primary; padding: 0 1; }
    #log { height: 7; border-top: tall $primary; }
    .bar { padding: 1 2; }
    #form { padding: 1 4; max-width: 90; }
    #form Label { padding-top: 1; }
    .intro { padding-bottom: 1; color: $success; }
    .sw { height: 3; margin-top: 1; }
    .sw Label { padding: 1 0 0 1; }
    Confirm { align: center middle; }
    .dialog { width: 64; height: auto; padding: 1 2; border: thick $warning;
              background: $surface; }
    .q { width: 100%; padding-bottom: 1; }
    EditItem { align: center middle; }
    .wide { width: 90; }
    #e_desc { height: 10; }
    .section { padding-top: 1; color: $accent; }
    .btns { height: 3; margin-top: 1; }
    .btns Button { margin-right: 2; }
    """

    BINDINGS = [
        Binding("space", "toggle", "Select"),
        Binding("a", "select_ready", "All ready"),
        Binding("n", "select_none", "None"),
        Binding("c", "create", "Create"),
        Binding("d", "dry_run", "Dry run"),
        Binding("g", "ai", "AI"),
        Binding("o", "open", "Open"),
        Binding("slash", "filter", "Filter"),
        Binding("h", "history", "History"),
        Binding("s", "settings", "Settings"),
        Binding("r", "reload", "Reload"),
        Binding("q", "quit", "Quit"),
    ]

    MAIN_ONLY = {
        "toggle",
        "select_ready",
        "select_none",
        "create",
        "dry_run",
        "ai",
        "open",
        "filter",
        "history",
        "settings",
        "reload",
    }

    def check_action(self, action: str, parameters: tuple) -> bool | None:
        """Main-screen keys are off (and hidden) while another screen is open."""
        if action in self.MAIN_ONLY and len(self.screen_stack) > 1:
            return False
        return True

    def __init__(self, store: Store | None = None):
        super().__init__()
        self.store = store or Store()
        self.cfg = self.store.load_settings()
        self.svc: Service | None = None
        self.offers: dict[int, dict] = {}
        self.order: list[int] = []
        self.state: dict[int, str] = {}
        self.selected: set[int] = set()
        self.details: dict[int, dict] = {}
        self.gen = 0
        self.dry = False

    # ---- layout
    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="top"):
            yield Label("Status:")
            yield Select(
                [(s, s) for s in STATUSES],
                value=self.cfg.offer_status,
                allow_blank=False,
                id="status",
            )
            yield Input(placeholder="/ filter …", id="filter")
            yield Static("", id="summary")
            yield Static("", id="mode")
        with Horizontal(id="main"):
            yield DataTable(id="offers", cursor_type="row", zebra_stripes=True)
            with VerticalScroll(id="preview"):
                yield Static("Move the cursor to an offer to preview it.", id="pv")
        yield RichLog(id="log", markup=True, wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        t = self.query_one("#offers", DataTable)
        t.add_column(" ", key="sel", width=2)
        t.add_column("No.", key="no")
        t.add_column("Customer", key="cust")
        t.add_column("Title", key="title")
        t.add_column("Net", key="net")
        t.add_column("State", key="state", width=16)
        self.show_mode()
        if self.cfg.complete:
            self.connect()
        else:
            self.push_screen(SettingsScreen(self.cfg, first_run=True), self.settings_done)

    def connect(self) -> None:
        self.svc = Service(Moco(self.cfg.domain, self.cfg.api_key), self.store, self.cfg)
        self.sub_title = f"v{__version__}  ·  {self.cfg.domain}.mocoapp.com"
        self.action_reload()

    def settings_done(self, cfg: Settings | None) -> None:
        if cfg is None:
            return
        self.store.save_settings(cfg)
        self.cfg = self.store.load_settings()
        self.query_one("#status", Select).value = self.cfg.offer_status
        self.log_msg(f"Settings saved to [dim]{self.store.path}[/dim]")
        self.connect()

    # ---- helpers
    def log_msg(self, msg: str) -> None:
        self.query_one("#log", RichLog).write(msg)

    def show_mode(self) -> None:
        self.query_one("#mode", Static).update(
            "[b black on yellow] DRY RUN [/]" if self.dry else "[b black on green] LIVE [/]"
        )

    def state_cell(self, oid: int) -> str:
        label, style = STATE[self.state[oid]]
        return f"[{style}]{label}[/]"

    def refresh_row(self, oid: int) -> None:
        t = self.query_one("#offers", DataTable)
        k = str(oid)
        if k in t.rows:
            t.update_cell(k, "sel", "[b green]■[/]" if oid in self.selected else "□")
            t.update_cell(k, "state", self.state_cell(oid))
        self.refresh_summary()

    def refresh_summary(self) -> None:
        ready = sum(1 for s in self.state.values() if s == READY)
        self.query_one("#summary", Static).update(
            f"{len(self.offers)} offers · {ready} ready · [b]{len(self.selected)} selected[/b]"
        )

    def current_id(self) -> int | None:
        t = self.query_one("#offers", DataTable)
        if t.row_count == 0:
            return None
        return int(t.coordinate_to_cell_key(t.cursor_coordinate).row_key.value)

    def matches(self, o: dict) -> bool:
        q = self.query_one("#filter", Input).value.strip().lower()
        if not q:
            return True
        hay = " ".join(
            [
                o.get("identifier") or "",
                o.get("title") or "",
                (o.get("company") or {}).get("name") or "",
            ]
        ).lower()
        return all(part in hay for part in q.split())

    def rebuild_table(self) -> None:
        t = self.query_one("#offers", DataTable)
        t.clear()
        for oid in self.order:
            o = self.offers[oid]
            if not self.matches(o):
                continue
            t.add_row(
                "[b green]■[/]" if oid in self.selected else "□",
                o.get("identifier", ""),
                (o.get("company") or {}).get("name", "–"),
                o.get("title", ""),
                money(o.get("net_total"), o.get("currency")),
                self.state_cell(oid),
                key=str(oid),
            )
        self.refresh_summary()

    # ---- loading
    @on(Select.Changed, "#status")
    def status_changed(self, e: Select.Changed) -> None:
        if self.svc and e.value != getattr(self, "loaded_status", None):
            self.action_reload()

    @on(Input.Changed, "#filter")
    def filter_changed(self) -> None:
        self.rebuild_table()

    @on(Input.Submitted, "#filter")
    def filter_done(self) -> None:
        self.query_one("#offers", DataTable).focus()

    def action_filter(self) -> None:
        self.query_one("#filter", Input).focus()

    def action_reload(self) -> None:
        if not self.svc:
            return
        status = self.query_one("#status", Select).value
        self.loaded_status = status
        self.offers, self.order, self.state = {}, [], {}
        self.selected, self.details = set(), {}
        self.rebuild_table()
        self.query_one("#pv", Static).update("Loading …")
        self.gen += 1
        self.load_offers(status, self.gen)

    @work(thread=True, exclusive=True, group="load")
    def load_offers(self, status: str, gen: int) -> None:
        svc = self.svc
        try:
            offers = svc.api.offers(status)
        except Exception as e:  # noqa: BLE001
            self.call_from_thread(self.log_msg, f"[red]Load failed:[/] {e}")
            return
        if gen != self.gen:
            return
        self.call_from_thread(self.fill, offers, gen)
        for o in offers:
            if gen != self.gen:
                return
            try:
                st = svc.check(o)
            except Exception as e:  # noqa: BLE001
                st = "error"
                self.call_from_thread(self.log_msg, f"[red]{o.get('identifier')}:[/] {e}")
            self.call_from_thread(self.set_state, o["id"], st)
        self.call_from_thread(self.log_msg, f"Loaded {len(offers)} offer(s) · [b]{status}[/b]")

    def fill(self, offers: list[dict], gen: int) -> None:
        if gen != self.gen:
            return
        for o in offers:
            self.offers[o["id"]] = o
            self.order.append(o["id"])
            self.state[o["id"]] = "checking"
        self.rebuild_table()
        if not offers:
            self.query_one("#pv", Static).update("No offers with this status.")

    def set_state(self, oid: int, st: str) -> None:
        if oid in self.offers:
            self.state[oid] = st
            if st != READY:
                self.selected.discard(oid)
            self.refresh_row(oid)

    # ---- preview
    @on(DataTable.RowHighlighted, "#offers")
    def highlighted(self, e: DataTable.RowHighlighted) -> None:
        if e.row_key is not None and e.row_key.value:
            self.load_preview(int(e.row_key.value))

    @work(thread=True, exclusive=True, group="preview")
    def load_preview(self, oid: int) -> None:
        pv = self.query_one("#pv", Static)
        if oid not in self.details:
            self.call_from_thread(pv.update, "Loading …")
            try:
                self.details[oid] = self.svc.api.offer(oid)
            except Exception as e:  # noqa: BLE001
                self.call_from_thread(pv.update, f"[red]{e}[/]")
                return
        if self.current_id() == oid:
            self.call_from_thread(self.show_preview, oid)

    def show_preview(self, oid: int) -> None:
        o = self.details[oid]
        ov = self.store.load_overrides(oid)
        inv = build_invoice(o, self.cfg, overrides=ov)
        src = o.get("items", [])
        ai_titles = {
            v.get("title")
            for i, v in ov.items()
            if v.get("accepted")
            and i < len(src)
            and (
                v.get("title") != src[i].get("title")
                or v.get("description")
                or v.get("use_quantity")
            )
        }
        cur = o.get("currency")
        lines = [
            f"[b]{o.get('identifier')}[/b]  {o.get('title')}",
            f"[dim]{(o.get('company') or {}).get('name', '–')}[/dim]",
            "",
            f"Draft title  {inv['title']}",
            f"Date → due   {inv['date']} → {inv['due_date']}",
            f"VAT          {inv['tax']} %",
            f"Offer net    [b]{money(o.get('net_total'), cur)}[/b]",
            "",
            "[b u]Items on draft[/]",
        ]
        for it in inv["items"]:
            t = it["type"]
            if t == "title":
                lines.append(f"\n[b]{it['title']}[/b]")
            elif t == "item":
                extra = " [yellow](expense)[/]" if it.get("additional") else ""
                if it["title"] in ai_titles:
                    extra += " [magenta]AI[/]"
                if "unit_price" in it:
                    lines.append(
                        f"• {it['title']}{extra}\n  [dim]{it['quantity']} {it.get('unit') or ''}"
                        f" × {it['unit_price']}[/dim]  "
                        f"{money(it['quantity'] * it['unit_price'], cur)}"
                    )
                else:
                    lines.append(f"• {it['title']}{extra}  {money(it['net_total'], cur)}")
            elif t == "subtotal":
                lines.append("[dim]── subtotal ──[/dim]")
        skipped = sum(1 for it in o.get("items", []) if it.get("optional"))
        if skipped and not self.cfg.include_optional:
            lines.append(f"\n[yellow]{skipped} optional item(s) left out[/yellow]")
        if ov:
            lines.append(f"\n[magenta]{len(ai_titles)} item(s) with AI text[/]")
        lines.append("\n[dim]g = AI suggestions · o = open offer in MOCO[/dim]")
        self.query_one("#pv", Static).update("\n".join(lines))

    # ---- selection
    def action_toggle(self) -> None:
        oid = self.current_id()
        if oid is None:
            return
        if self.state.get(oid) != READY:
            self.notify("Only READY offers can be selected.", severity="warning")
            return
        self.selected ^= {oid}
        self.refresh_row(oid)
        t = self.query_one("#offers", DataTable)
        t.move_cursor(row=min(t.cursor_row + 1, t.row_count - 1))

    def action_select_ready(self) -> None:
        for oid in self.order:
            if self.state.get(oid) == READY and self.matches(self.offers[oid]):
                self.selected.add(oid)
                self.refresh_row(oid)

    def action_select_none(self) -> None:
        old, self.selected = self.selected, set()
        for oid in old:
            self.refresh_row(oid)

    # ---- actions
    def action_dry_run(self) -> None:
        self.dry = not self.dry
        self.show_mode()
        self.notify("Dry run ON – nothing will be created." if self.dry else "Live mode.")

    def action_open(self) -> None:
        oid = self.current_id()
        if oid is not None and self.svc:
            open_url(self.svc.web_url("offers", oid))

    def action_ai(self, regenerate: bool = False) -> None:
        oid = self.current_id()
        if oid is None or not self.svc:
            return
        stored = self.store.load_overrides(oid)
        if stored and not regenerate:
            sugg = [ai.Suggestion(**v) for _, v in sorted(stored.items())]
            self.open_review(oid, sugg)
            return
        if not self.cfg.ai_ready:
            self.notify("Set up AI first: press s → AI section.", severity="warning")
            return
        self.log_msg(f"[magenta]AI[/]   {self.offers[oid].get('identifier')}: thinking …")
        self.run_ai(oid)

    @work(thread=True, exclusive=True, group="ai")
    def run_ai(self, oid: int) -> None:
        label = self.offers[oid].get("identifier")
        try:
            sugg = self.svc.suggest(oid)
        except Exception as e:  # noqa: BLE001
            self.call_from_thread(self.log_msg, f"[red]AI[/]   {label}: {e}")
            return
        if not sugg:
            self.call_from_thread(self.log_msg, f"[magenta]AI[/]   {label}: no items to fill")
            return
        self.call_from_thread(self.log_msg, f"[magenta]AI[/]   {label}: {len(sugg)} suggestion(s)")
        self.call_from_thread(self.open_review, oid, sugg)

    def open_review(self, oid: int, sugg: list[ai.Suggestion]) -> None:
        offer = self.details.get(oid) or self.offers[oid]

        def done(result) -> None:
            if result == "regenerate":
                self.action_ai(regenerate=True)
            elif result == "clear":
                self.store.clear_overrides(oid)
                self.log_msg(f"[magenta]AI[/]   {offer.get('identifier')}: suggestions removed")
            elif result is not None:
                self.store.save_overrides(oid, [x.to_dict() for x in result])
                n = sum(1 for x in result if x.accepted)
                self.log_msg(f"[magenta]AI[/]   {offer.get('identifier')}: {n} item(s) accepted")
            if oid in self.details and self.current_id() == oid:
                self.show_preview(oid)
            self.query_one("#offers", DataTable).focus()

        self.push_screen(AIReviewScreen(offer, sugg), done)

    def action_history(self) -> None:
        if self.svc:
            self.push_screen(HistoryScreen(self.store, self.svc))

    def action_settings(self) -> None:
        self.push_screen(SettingsScreen(self.cfg), self.settings_done)

    def action_create(self) -> None:
        if not self.selected:
            self.notify("Nothing selected. Press space or a.", severity="warning")
            return
        n = len(self.selected)
        if self.dry:
            self.create_drafts(list(self.selected), True)
            return
        extra = "\nOffers will be set to 'billed'." if self.cfg.mark_offer_billed else ""
        self.push_screen(
            Confirm(f"Create {n} invoice draft(s) in MOCO?{extra}"),
            lambda ok: ok and self.create_drafts(list(self.selected), False),
        )

    @work(thread=True, exclusive=True, group="create")
    def create_drafts(self, ids: list[int], dry: bool) -> None:
        ok = 0
        for oid in ids:
            label = self.offers[oid].get("identifier")
            try:
                res = self.svc.create_draft(oid, dry_run=dry)
                if res is None:
                    self.call_from_thread(self.set_state, oid, HAS_DRAFT)
                    self.call_from_thread(self.log_msg, f"[cyan]SKIP[/] {label}: already done")
                    continue
                ok += 1
                if dry:
                    self.call_from_thread(
                        self.log_msg, f"[yellow]DRY[/]  {label}: {len(res['items'])} items"
                    )
                    continue
                self.call_from_thread(self.set_state, oid, "created")
                self.call_from_thread(self.log_msg, f"[green]OK[/]   {label} → draft {res['id']}")
            except Exception as e:  # noqa: BLE001
                self.call_from_thread(self.set_state, oid, "error")
                self.call_from_thread(self.log_msg, f"[red]FAIL[/] {label}: {e}")
        verb = "checked (dry run)" if dry else "created"
        self.call_from_thread(self.notify, f"{ok} of {len(ids)} draft(s) {verb}.")
