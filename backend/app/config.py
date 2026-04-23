from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="ignore")

    app_name: str = "GeBIZ Monitor"
    debug: bool = False

    database_url: str = f"sqlite:///{BASE_DIR / 'gebiz.db'}"

    scrape_cron: str = "0 */4 * * *"
    scrape_timezone: str = "Asia/Singapore"
    use_mock_scraper: bool = False

    gebiz_base_url: str = "https://www.gebiz.gov.sg"
    gebiz_list_path: str = "/ptn/opportunity/opportunityListing.xhtml"

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_pass: str | None = None
    smtp_from: str | None = None

    admin_alert_emails: str = ""

    frontend_dir: Path = BASE_DIR.parent / "frontend"

    @property
    def admin_emails(self) -> list[str]:
        return [e.strip() for e in self.admin_alert_emails.split(",") if e.strip()]


settings = Settings()
