"""LinkedIn Job Scraper — Terminal UI (Textual).

Usage:
    python main.py --tui
    python -m tui.app
"""

from __future__ import annotations

from datetime import UTC, datetime

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    OptionList,
    Select,
    Static,
    TabbedContent,
    TabPane,
)

from db.database import init_db
from db.repository import JobRepository

# Status colors for the pipeline
STATUS_COLORS = {
    "discovered": "white",
    "interested": "dodger_blue",
    "applied": "dark_orange",
    "interviewing": "medium_purple",
    "offer": "green",
    "rejected": "red",
    "archived": "dim",
}

ALL_STATUSES = list(STATUS_COLORS.keys())

TIME_FILTERS = [
    ("Past 24 hours", "r86400"),
    ("Past week", "r604800"),
    ("Past month", "r2592000"),
    ("Any time", ""),
]

EXPERIENCE_LEVELS = [
    ("Any", ""),
    ("Internship", "1"),
    ("Entry level", "2"),
    ("Associate", "3"),
    ("Mid-Senior", "4"),
    ("Director", "5"),
    ("Executive", "6"),
]

JOB_TYPES = [
    ("Any", ""),
    ("Full-time", "F"),
    ("Part-time", "P"),
    ("Contract", "C"),
    ("Internship", "I"),
]


class JobDetailScreen(ModalScreen):
    """Full-screen modal showing job details."""

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("o", "open_url", "Open LinkedIn"),
        Binding("s", "cycle_status", "Change Status"),
    ]

    def __init__(self, job: dict) -> None:
        super().__init__()
        self.job = job

    def compose(self) -> ComposeResult:
        j = self.job
        status_color = STATUS_COLORS.get(j["status"], "white")

        # Parse hiring manager
        hm_name = ""
        hm_url = ""
        if j.get("hiring_manager") and "|" in j["hiring_manager"]:
            parts = j["hiring_manager"].split("|")
            hm_name = parts[0]
            hm_url = parts[1] if len(parts) > 1 else ""

        with VerticalScroll():
            yield Static(
                f"[bold]{j['title']}[/]\n"
                f"{j['company']} — {j['location']}\n"
                f"[{status_color}]{j['status'].upper()}[/]",
                id="detail-header",
            )

            # Key info
            info_lines = []
            if j.get("job_type") and j["job_type"] != "Unknown":
                info_lines.append(f"[bold]Type:[/] {j['job_type']}")
            if j.get("workplace_type") and j["workplace_type"] != "Unknown":
                wp_color = "green" if j["workplace_type"] == "Remote" else "dodger_blue"
                info_lines.append(f"[bold]Workplace:[/] [{wp_color}]{j['workplace_type']}[/]")
            if j.get("seniority_level"):
                info_lines.append(f"[bold]Seniority:[/] {j['seniority_level']}")
            if j.get("applicant_count"):
                info_lines.append(f"[bold]Applicants:[/] {j['applicant_count']}")
            if j.get("posted_date"):
                info_lines.append(f"[bold]Posted:[/] {j['posted_date']}")
            if j.get("salary_raw"):
                info_lines.append(f"[bold]Salary:[/] {j['salary_raw']}")
            if j.get("industries"):
                info_lines.append(f"[bold]Industries:[/] {j['industries']}")
            if j.get("badge"):
                info_lines.append(f"[bold]Badge:[/] [green]{j['badge']}[/]")

            if info_lines:
                yield Static("\n".join(info_lines), id="detail-info")

            # Hiring manager
            if hm_name:
                yield Static(
                    f"\n[bold dodger_blue]Hiring Manager:[/] {hm_name}"
                    + (f"\n  {hm_url}" if hm_url else ""),
                    id="detail-hm",
                )

            # Description
            if j.get("description"):
                desc = j["description"][:3000]
                yield Static(f"\n[bold]Description:[/]\n{desc}", id="detail-desc")
            else:
                yield Static("\n[dim]No description available. Run with enrichment enabled.[/]")

            # Notes
            if j.get("notes"):
                yield Static(f"\n[bold yellow]Notes:[/] {j['notes']}")

            # Metadata
            yield Static(
                f"\n[dim]Job ID: {j['job_id']} | "
                f"First seen: {j.get('first_seen_at', '?')} | "
                f"Last seen: {j.get('last_seen_at', '?')}[/]"
            )

            yield Static(f"\n[dim]URL: {j['url']}[/]")

    def action_open_url(self) -> None:
        import webbrowser

        webbrowser.open(self.job["url"])

    def action_cycle_status(self) -> None:
        current = self.job["status"]
        idx = ALL_STATUSES.index(current) if current in ALL_STATUSES else 0
        new_status = ALL_STATUSES[(idx + 1) % len(ALL_STATUSES)]
        repo = JobRepository()
        repo.update_job_status(self.job["id"], new_status)
        repo.close()
        self.job["status"] = new_status
        self.notify(f"Status → {new_status}")
        self.dismiss()


class ScrapeApp(App):
    """LinkedIn Job Scraper TUI."""

    CSS = """
    #search-panel { height: auto; padding: 1; }
    #search-panel Input { margin-bottom: 1; }
    #search-panel Select { margin-bottom: 1; }
    #stats-bar { height: 3; padding: 0 1; }
    #stats-bar Label { margin-right: 2; }
    #scrape-status { height: auto; min-height: 1; padding: 0 1; }
    DataTable { height: 1fr; }
    #pipeline-container { height: 1fr; }
    .pipeline-col { width: 1fr; height: 1fr; padding: 0 1; }
    .pipeline-col-header { height: 3; }
    .pipeline-card { height: auto; margin-bottom: 1; padding: 1; }
    JobDetailScreen { align: center middle; }
    JobDetailScreen > VerticalScroll {
        width: 90%; height: 90%;
        border: thick $accent;
        padding: 2; background: $surface;
    }
    #detail-header { margin-bottom: 1; }
    #detail-info { margin-bottom: 1; }
    """

    TITLE = "LinkedIn Job Scraper"
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("p", "preview", "Preview Count"),
        Binding("s", "scrape", "Scrape"),
        Binding("e", "export", "Export CSV"),
    ]

    def __init__(self) -> None:
        super().__init__()
        init_db()
        self._scrape_running = False

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent("Search", "Jobs", "Pipeline"):
            with TabPane("Search", id="tab-search"):
                yield from self._compose_search()
            with TabPane("Jobs", id="tab-jobs"):
                yield from self._compose_jobs()
            with TabPane("Pipeline", id="tab-pipeline"):
                yield from self._compose_pipeline()
        yield Footer()

    def _compose_search(self) -> ComposeResult:
        with Vertical(id="search-panel"):
            yield Label("[bold]Search Configuration[/]")
            yield Input(placeholder="Keywords (e.g. AI engineer)", id="inp-keywords")
            yield Input(placeholder="Location (e.g. Dallas, TX)", id="inp-location")
            yield Select(
                [(label, val) for label, val in TIME_FILTERS],
                prompt="Time filter",
                id="sel-time",
                value="r2592000",
            )
            yield Select(
                [(label, val) for label, val in EXPERIENCE_LEVELS],
                prompt="Experience",
                id="sel-exp",
            )
            yield Select(
                [(label, val) for label, val in JOB_TYPES],
                prompt="Job type",
                id="sel-jtype",
            )
            yield Input(placeholder="Max pages (default: 10)", id="inp-maxpages")
            with Horizontal():
                yield Button("Preview Count", id="btn-preview", variant="default")
                yield Button("Scrape Jobs", id="btn-scrape", variant="primary")
            yield Static("", id="scrape-status")

    def _compose_jobs(self) -> ComposeResult:
        with Vertical():
            with Horizontal(id="stats-bar"):
                yield Label("", id="lbl-stats")
                yield Input(
                    placeholder="Search jobs...",
                    id="inp-search-jobs",
                )
                yield Select(
                    [("All", "all")] + [(s.capitalize(), s) for s in ALL_STATUSES],
                    prompt="Status",
                    id="sel-status-filter",
                    value="all",
                )
            table = DataTable(id="jobs-table")
            table.cursor_type = "row"
            yield table

    def _compose_pipeline(self) -> ComposeResult:
        with Horizontal(id="pipeline-container"):
            for status in ALL_STATUSES[:6]:
                with Vertical(classes="pipeline-col"):
                    color = STATUS_COLORS[status]
                    yield Static(
                        f"[bold {color}]{status.upper()}[/]",
                        classes="pipeline-col-header",
                    )
                    yield OptionList(id=f"pipe-{status}")

    def on_mount(self) -> None:
        table = self.query_one("#jobs-table", DataTable)
        table.add_columns(
            "Title",
            "Company",
            "Location",
            "Type",
            "Workplace",
            "Applicants",
            "Posted",
            "Status",
        )
        self._refresh_jobs()
        self._refresh_pipeline()
        self._refresh_stats()

    def _get_search_profile(self):
        from config.settings import SearchProfile

        keywords = self.query_one("#inp-keywords", Input).value.strip()
        location = self.query_one("#inp-location", Input).value.strip()
        time_val = self.query_one("#sel-time", Select).value
        exp_val = self.query_one("#sel-exp", Select).value
        jtype_val = self.query_one("#sel-jtype", Select).value
        max_pages_raw = self.query_one("#inp-maxpages", Input).value.strip()
        max_pages = int(max_pages_raw) if max_pages_raw.isdigit() else 10

        name = keywords.lower().replace(" ", "-")
        if location:
            name += f"-{location.lower().split(',')[0].strip().replace(' ', '-')}"

        return SearchProfile(
            name=name or "default",
            keywords=keywords or "software engineer",
            location=location,
            time_filter=str(time_val) if time_val != Select.BLANK else "r2592000",
            experience_levels=([str(exp_val)] if exp_val and exp_val != Select.BLANK else []),
            job_types=([str(jtype_val)] if jtype_val and jtype_val != Select.BLANK else []),
            max_pages=max_pages,
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-preview":
            self._run_preview()
        elif event.button.id == "btn-scrape":
            if not self._scrape_running:
                self._run_scrape()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        row_key = event.row_key
        repo = JobRepository()
        job = repo.get_job(str(row_key.value))
        repo.close()
        if job:
            self.push_screen(JobDetailScreen(job))

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "sel-status-filter":
            self._refresh_jobs()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "inp-search-jobs":
            self._refresh_jobs()

    def on_screen_resume(self) -> None:
        self._refresh_jobs()
        self._refresh_pipeline()
        self._refresh_stats()

    @work(thread=False)
    async def _run_preview(self) -> None:
        profile = self._get_search_profile()
        if not profile.keywords:
            self.notify("Enter keywords first", severity="warning")
            return

        status = self.query_one("#scrape-status", Static)
        status.update(f"Probing result count for '{profile.keywords}'...")

        from scraper.parallel import _probe_total_results

        total = await _probe_total_results(profile)
        status.update(f"[bold green]~{total}[/] results for [bold]{profile.keywords}[/]")

    @work(thread=False)
    async def _run_scrape(self) -> None:
        profile = self._get_search_profile()
        if not profile.keywords:
            self.notify("Enter keywords first", severity="warning")
            return

        self._scrape_running = True
        btn = self.query_one("#btn-scrape", Button)
        btn.disabled = True
        status = self.query_one("#scrape-status", Static)

        try:
            status.update(f"Probing results for '{profile.keywords}'...")
            from scraper.parallel import parallel_collect

            result = await parallel_collect(profile, enrich=True)

            status.update(f"Saving {len(result.cards)} jobs to database...")
            repo = JobRepository()
            run_id = repo.create_scrape_run(profile.name, profile.keywords, profile.location)
            new_count = 0
            updated_count = 0
            for card in result.cards:
                _, is_new = repo.upsert_job(
                    {
                        "job_id": card.job_id,
                        "title": card.title,
                        "company": card.company,
                        "location": card.location,
                        "url": card.url,
                        "description": card.description,
                        "salary_raw": card.salary,
                        "job_type": card.employment_type or "Unknown",
                        "workplace_type": card.workplace_type or "Unknown",
                        "seniority_level": card.seniority_level,
                        "applicant_count": card.applicant_count,
                        "posted_date": card.posted_date,
                        "badge": card.badge,
                        "job_function": card.job_function,
                        "industries": card.industries,
                        "hiring_manager": (
                            f"{card.hiring_manager_name}|{card.hiring_manager_url}"
                            if card.hiring_manager_name
                            else ""
                        ),
                        "enriched": bool(card.description),
                        "extraction_strategy": "parallel_guest",
                        "scrape_run_id": run_id,
                    }
                )
                if is_new:
                    new_count += 1
                else:
                    updated_count += 1

            repo.complete_scrape_run(
                run_id,
                total_found=result.total_results_probed,
                new_jobs=new_count,
                updated_jobs=updated_count,
                workers_used=result.workers_used,
                elapsed_seconds=result.elapsed_seconds,
            )
            repo.close()

            status.update(
                f"[bold green]Done![/] {new_count} new, {updated_count} updated "
                f"({result.elapsed_seconds:.0f}s, {result.workers_used} workers)"
            )
            self.notify(
                f"{new_count} new jobs scraped in {result.elapsed_seconds:.0f}s",
                severity="information",
            )
            self._refresh_jobs()
            self._refresh_pipeline()
            self._refresh_stats()

        except Exception as e:
            status.update(f"[bold red]Error:[/] {e}")
            self.notify(f"Scrape failed: {e}", severity="error")
        finally:
            self._scrape_running = False
            btn.disabled = False

    def _refresh_jobs(self) -> None:
        table = self.query_one("#jobs-table", DataTable)
        table.clear()

        repo = JobRepository()
        status_filter = self.query_one("#sel-status-filter", Select).value
        search_input = self.query_one("#inp-search-jobs", Input)
        search = search_input.value.strip() if search_input.value else ""

        use_status = str(status_filter) if status_filter not in ("all", Select.BLANK) else None
        jobs = repo.list_jobs(
            status=use_status,
            search=search or None,
            limit=500,
        )
        repo.close()

        for job in jobs:
            wp = job.get("workplace_type", "")
            if wp and wp != "Unknown":
                wp_display = wp
            else:
                wp_display = ""

            status_color = STATUS_COLORS.get(job["status"], "white")

            table.add_row(
                job["title"][:50],
                job["company"][:25],
                job["location"][:20],
                (job.get("job_type", "") or "")[:15],
                wp_display,
                str(job["applicant_count"] or ""),
                job.get("posted_date") or "",
                f"[{status_color}]{job['status']}[/]",
                key=job["job_id"],
            )

    def _refresh_pipeline(self) -> None:
        repo = JobRepository()
        for status in ALL_STATUSES[:6]:
            try:
                option_list = self.query_one(f"#pipe-{status}", OptionList)
                option_list.clear_options()
                jobs = repo.list_jobs(status=status, limit=50)
                for job in jobs:
                    label = f"{job['title'][:30]} @ {job['company'][:15]}"
                    option_list.add_option(label)
            except Exception:
                pass
        repo.close()

    def _refresh_stats(self) -> None:
        repo = JobRepository()
        total = repo.count_jobs()
        counts = repo.get_status_counts()
        repo.close()

        parts = [f"[bold]{total}[/] jobs"]
        for s, c in counts.items():
            color = STATUS_COLORS.get(s, "white")
            parts.append(f"[{color}]{s}: {c}[/]")

        try:
            lbl = self.query_one("#lbl-stats", Label)
            lbl.update(" | ".join(parts))
        except Exception:
            pass

    def action_refresh(self) -> None:
        self._refresh_jobs()
        self._refresh_pipeline()
        self._refresh_stats()
        self.notify("Refreshed")

    def action_preview(self) -> None:
        self._run_preview()

    def action_scrape(self) -> None:
        if not self._scrape_running:
            self._run_scrape()

    def action_export(self) -> None:
        repo = JobRepository()
        jobs = repo.list_jobs(limit=10000)
        repo.close()

        if not jobs:
            self.notify("No jobs to export", severity="warning")
            return

        import csv
        from pathlib import Path

        output_dir = Path("output")
        output_dir.mkdir(exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        path = output_dir / f"jobs_export_{timestamp}.csv"

        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "Job ID",
                    "Title",
                    "Company",
                    "Location",
                    "URL",
                    "Job Type",
                    "Workplace",
                    "Seniority Level",
                    "Applicant Count",
                    "Posted Date",
                    "Salary",
                    "Status",
                    "Notes",
                    "Applied Date",
                    "Response Date",
                    "Description",
                    "Industries",
                    "Badge",
                    "Hiring Manager",
                    "Apply URL",
                    "Easy Apply",
                    "First Seen",
                    "Last Seen",
                ]
            )
            for job in jobs:
                writer.writerow(
                    [
                        job["job_id"],
                        job["title"],
                        job["company"],
                        job["location"],
                        job["url"],
                        job.get("job_type", ""),
                        job.get("workplace_type", ""),
                        job.get("seniority_level", ""),
                        job.get("applicant_count") or "",
                        job.get("posted_date") or "",
                        job.get("salary_raw", ""),
                        job["status"],
                        job.get("notes", ""),
                        job.get("applied_date") or "",
                        job.get("response_date") or "",
                        (job.get("description") or "")[:5000],
                        job.get("industries", ""),
                        job.get("badge", ""),
                        job.get("hiring_manager", ""),
                        job.get("apply_url", ""),
                        job.get("is_easy_apply", False),
                        job.get("first_seen_at", ""),
                        job.get("last_seen_at", ""),
                    ]
                )

        self.notify(f"Exported {len(jobs)} jobs to {path}")


def run_tui() -> None:
    """Entry point for the TUI."""
    app = ScrapeApp()
    app.run()


if __name__ == "__main__":
    run_tui()
