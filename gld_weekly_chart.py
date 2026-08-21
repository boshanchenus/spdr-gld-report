#!/usr/bin/env python3
"""Build a weekly SPDR GLD holdings net-change chart.

Default usage downloads the official SPDR GLD Historical Archive workbook:

    python gld_weekly_chart.py

Fallback usage with a local workbook:

    python gld_weekly_chart.py --file historical_archive.xlsx
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import BinaryIO

if "MPLCONFIGDIR" not in os.environ:
    mpl_config_dir = Path(__file__).resolve().parent / ".matplotlib-cache"
    mpl_config_dir.mkdir(exist_ok=True)
    os.environ["MPLCONFIGDIR"] = str(mpl_config_dir)

import matplotlib.pyplot as plt
import pandas as pd
import requests


SPDR_ARCHIVE_URL = (
    "https://api.spdrgoldshares.com/api/v1/historical-archive"
    "?exchange=NYSE&lang=en&product=gld"
)
TELEGRAM_API_URL = "https://api.telegram.org"


@dataclass(frozen=True)
class SourceInfo:
    """Details about the parsed workbook source."""

    sheet_name: str
    date_column: str
    tonnes_column: str


def download_spdr_excel(timeout: int = 30, attempts: int = 3) -> BytesIO:
    """Download the official archive, retrying transient network failures."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; GLDWeeklyChart/1.0; "
            "+https://www.spdrgoldshares.com/)"
        ),
        "Accept": (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,"
            "application/vnd.ms-excel,*/*"
        ),
    }
    last_error: requests.RequestException | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = requests.get(SPDR_ARCHIVE_URL, headers=headers, timeout=timeout)
            response.raise_for_status()
            break
        except requests.RequestException as exc:
            last_error = exc
            if attempt == attempts:
                raise
            delay = 2 ** (attempt - 1)
            print(
                f"Download attempt {attempt}/{attempts} failed; retrying in {delay}s...",
                file=sys.stderr,
            )
            time.sleep(delay)
    else:  # pragma: no cover - defensive; the loop either breaks or raises.
        raise RuntimeError(f"Download failed: {last_error}")

    content_type = response.headers.get("content-type", "").lower()
    if "html" in content_type:
        raise RuntimeError(
            "SPDR endpoint returned HTML instead of an Excel workbook. "
            "Use --file with a locally downloaded archive."
        )

    data = BytesIO(response.content)
    data.seek(0)
    return data


def download_with_cache(cache_file: str | Path) -> tuple[BytesIO | Path, str]:
    """Download current data and retain a last-known-good offline fallback."""
    cache_path = Path(cache_file).expanduser().resolve()
    try:
        downloaded = download_spdr_excel()
        payload = downloaded.getvalue()
        # Do not replace a known-good cache with an HTML error page, truncated
        # ZIP, or an unexpectedly changed workbook.
        load_gld_data(BytesIO(payload))
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = cache_path.with_suffix(cache_path.suffix + ".tmp")
        temporary.write_bytes(payload)
        temporary.replace(cache_path)
        return BytesIO(payload), "official SPDR endpoint"
    except Exception as exc:
        if not cache_path.is_file():
            raise RuntimeError(
                "Could not obtain valid SPDR data and no local cache is available. "
                "Check the internet connection and try again."
            ) from exc
        print(
            f"Warning: live data failed validation ({exc}); "
            f"using cached workbook: {cache_path}",
            file=sys.stderr,
        )
        return cache_path, f"cached workbook {cache_path}"


def _normalize_name(value: object) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip().lower())
    return text


def _clean_number_series(series: pd.Series) -> pd.Series:
    """Convert common Excel-formatted numbers into floats."""
    cleaned = (
        series.astype(str)
        .str.strip()
        .str.replace(",", "", regex=False)
        .str.replace("(", "-", regex=False)
        .str.replace(")", "", regex=False)
        .str.replace(r"[^0-9.\-]", "", regex=True)
    )
    cleaned = cleaned.replace({"": pd.NA, "-": pd.NA, ".": pd.NA})
    return pd.to_numeric(cleaned, errors="coerce")


def _parse_dates(series: pd.Series) -> pd.Series:
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="Could not infer format.*",
            category=UserWarning,
        )
        return pd.to_datetime(series, errors="coerce")


def _score_date_column(series: pd.Series, column_name: object) -> float:
    name = _normalize_name(column_name)
    parsed = _parse_dates(series)
    valid_ratio = parsed.notna().mean()

    score = valid_ratio
    if "date" in name:
        score += 0.35
    if valid_ratio < 0.45:
        score -= 1.0
    return score


def _score_tonnes_column(series: pd.Series, column_name: object) -> float:
    name = _normalize_name(column_name)
    numeric = _clean_number_series(series)
    valid_ratio = numeric.notna().mean()

    score = valid_ratio
    if "tonne" in name or "tonnes" in name or "metric ton" in name:
        score += 1.0
    if "trust" in name or "holding" in name or "gold" in name:
        score += 0.25
    if "change" in name or "flow" in name:
        score -= 0.5
    if "oz" in name or "ounce" in name or "nav" in name or "share" in name:
        score -= 0.35
    if valid_ratio < 0.45:
        score -= 1.0

    median_value = numeric.dropna().median()
    if pd.notna(median_value):
        # GLD holdings are normally hundreds of tonnes. This helps avoid NAV,
        # share, and price columns if their names are ambiguous.
        if 100 <= median_value <= 2000:
            score += 0.35
        elif median_value > 10000:
            score -= 0.35
    return score


def _read_excel_candidates(source: str | Path | BinaryIO | BytesIO) -> list[tuple[str, int, pd.DataFrame]]:
    """Read all sheets with several possible header rows."""
    workbook = pd.ExcelFile(source)
    candidates: list[tuple[str, int, pd.DataFrame]] = []

    for sheet_name in workbook.sheet_names:
        for header_row in range(0, 8):
            try:
                frame = pd.read_excel(workbook, sheet_name=sheet_name, header=header_row)
            except Exception:
                continue

            frame = frame.dropna(how="all").dropna(axis=1, how="all")
            if len(frame) < 10 or len(frame.columns) < 2:
                continue
            candidates.append((sheet_name, header_row, frame))

    return candidates


def _choose_columns(frame: pd.DataFrame) -> tuple[str, str, float] | None:
    date_scores = [
        (column, _score_date_column(frame[column], column)) for column in frame.columns
    ]
    tonnes_scores = [
        (column, _score_tonnes_column(frame[column], column)) for column in frame.columns
    ]

    date_column, date_score = max(date_scores, key=lambda item: item[1])
    tonne_candidates = [
        (column, score) for column, score in tonnes_scores if column != date_column
    ]
    tonnes_column, tonnes_score = max(tonne_candidates, key=lambda item: item[1])

    if date_score < 0.35 or tonnes_score < 0.65:
        return None

    return str(date_column), str(tonnes_column), date_score + tonnes_score


def load_gld_data(source: str | Path | BinaryIO | BytesIO) -> tuple[pd.DataFrame, SourceInfo]:
    """Load, identify, and clean date and GLD holdings tonnes columns."""
    candidates = _read_excel_candidates(source)
    if not candidates:
        raise RuntimeError("No usable worksheets found in the Excel file.")

    best: tuple[float, str, int, pd.DataFrame, str, str] | None = None
    for sheet_name, header_row, frame in candidates:
        choice = _choose_columns(frame)
        if choice is None:
            continue

        date_column, tonnes_column, score = choice
        if best is None or score > best[0]:
            best = (score, sheet_name, header_row, frame, date_column, tonnes_column)

    if best is None:
        raise RuntimeError(
            "Could not identify both a date column and a GLD holdings tonnes column."
        )

    _, sheet_name, _header_row, frame, date_column, tonnes_column = best

    data = pd.DataFrame(
        {
            "date": _parse_dates(frame[date_column]).dt.normalize(),
            "tonnes": _clean_number_series(frame[tonnes_column]),
        }
    )
    data = data.dropna(subset=["date", "tonnes"])
    data = data.sort_values("date")
    data = data.drop_duplicates(subset=["date"], keep="last")
    data = data.reset_index(drop=True)

    if len(data) < 10:
        raise RuntimeError("Not enough valid GLD data rows after cleaning.")

    source_info = SourceInfo(
        sheet_name=sheet_name,
        date_column=date_column,
        tonnes_column=tonnes_column,
    )
    return data, source_info


def _last_on_or_before(data: pd.DataFrame, date_value: pd.Timestamp) -> pd.Series | None:
    matches = data[data["date"] <= date_value]
    if matches.empty:
        return None
    return matches.iloc[-1]


def calc_weekly_changes(data: pd.DataFrame, weeks: int = 6) -> pd.DataFrame:
    """Calculate Monday-Sunday natural-week holdings changes.

    For each natural week, the starting value is the latest available Tonnes
    before that Monday. The ending value is the latest available Tonnes on or
    before that Sunday. This includes Monday's daily change and avoids treating
    Monday's end-of-day snapshot as the weekly start.
    """
    if weeks < 1:
        raise ValueError("--weeks must be at least 1.")

    data = data.sort_values("date").reset_index(drop=True)
    latest_date = data["date"].max()
    latest_week_start = latest_date - pd.Timedelta(days=int(latest_date.weekday()))

    rows = []
    for index in range(weeks):
        week_start = latest_week_start - pd.Timedelta(days=(weeks - index - 1) * 7)
        week_end = week_start + pd.Timedelta(days=6)
        start_cutoff = week_start - pd.Timedelta(days=1)

        start_row = _last_on_or_before(data, start_cutoff)
        end_row = _last_on_or_before(data, week_end)
        if start_row is None or end_row is None:
            raise RuntimeError(
                "Not enough historical data to calculate "
                f"{weeks} weekly changes ending {format_date(latest_date)}."
            )

        start_tonnes = float(start_row["tonnes"])
        ending_tonnes = float(end_row["tonnes"])
        end_data_date = pd.Timestamp(end_row["date"])
        label_end = end_data_date if week_start <= end_data_date <= week_end else week_end
        rows.append(
            {
                "week start": week_start,
                "week end": week_end,
                "start date": start_row["date"],
                "end date": end_row["date"],
                "start tonnes": start_tonnes,
                "weekly change": ending_tonnes - start_tonnes,
                "ending tonnes": ending_tonnes,
                "label start": week_start,
                "label end": label_end,
            }
        )

    return pd.DataFrame(rows)


def format_date(value: pd.Timestamp) -> str:
    """Cross-platform date like 'Jul 9' without strftime %-d."""
    value = pd.Timestamp(value)
    return f"{value.strftime('%b')} {value.day}"


def format_range(start: pd.Timestamp, end: pd.Timestamp) -> str:
    """Compact axis label like 'May 29-Jun 4' or 'Jun 6-12'."""
    start = pd.Timestamp(start)
    end = pd.Timestamp(end)
    if start.year == end.year and start.month == end.month:
        return f"{start.strftime('%b')} {start.day}-{end.day}"
    return f"{format_date(start)}-{format_date(end)}"


def _nice_ylim(values: pd.Series) -> tuple[float, float]:
    max_abs = max(abs(float(values.min())), abs(float(values.max())), 1.0)
    limit = max_abs * 1.35
    return -limit, limit


def plot_weekly_chart(
    weekly: pd.DataFrame,
    output: str | Path = "charts/gld_weekly_net_change.png",
    dpi: int = 220,
) -> None:
    """Render and save the weekly net-change chart as a PNG."""
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    changes = weekly["weekly change"]
    positive_weeks = int((changes > 0).sum())
    net_change = float(changes.sum())
    latest_change = float(changes.iloc[-1])
    latest_end = pd.Timestamp(weekly["end date"].iloc[-1])
    weeks = len(weekly)

    title = (
        "SPDR GLD Weekly Net Change (Tonnes) - "
        f"{weeks} Weeks Ending {format_date(latest_end)}"
    )
    summary = (
        f"Only {positive_weeks} of the last {weeks} weeks showed positive inflows "
        f"(net {net_change:+.2f}T). The latest week was {latest_change:+.2f}T."
    )

    labels = [
        format_range(row["label start"], row["label end"]) for _, row in weekly.iterrows()
    ]
    colors = ["#36bf8a" if value >= 0 else "#ef5b5b" for value in changes]

    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "axes.edgecolor": "#d9dee7",
            "axes.labelcolor": "#28323f",
            "xtick.color": "#566171",
            "ytick.color": "#566171",
        }
    )

    fig = plt.figure(figsize=(9.2, 6.0), facecolor="#f2f5f8")
    ax = fig.add_axes([0.09, 0.18, 0.86, 0.57], facecolor="white")

    fig.text(0.06, 0.92, title, fontsize=15, fontweight="bold", color="#101820")
    fig.text(0.06, 0.865, summary, fontsize=10.2, color="#536070")

    bars = ax.bar(labels, changes, color=colors, width=0.58, zorder=3)
    ax.axhline(0, color="#1f2937", linewidth=1.05, zorder=2)
    ax.grid(axis="y", color="#e8edf3", linewidth=0.8, zorder=1)
    ax.set_ylabel("Tonnes", fontsize=10)
    ax.set_ylim(*_nice_ylim(changes))

    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    ax.spines["left"].set_color("#d9dee7")
    ax.spines["bottom"].set_color("#d9dee7")

    ax.tick_params(axis="x", labelrotation=0, labelsize=8.2, length=0, pad=8)
    ax.tick_params(axis="y", labelsize=8.5, length=0)

    ymin, ymax = ax.get_ylim()
    offset = (ymax - ymin) * 0.035
    for bar, value in zip(bars, changes):
        x_pos = bar.get_x() + bar.get_width() / 2
        if value >= 0:
            y_pos = value + offset
            vertical_alignment = "bottom"
        else:
            y_pos = value - offset
            vertical_alignment = "top"

        ax.text(
            x_pos,
            y_pos,
            f"{value:+.2f}",
            ha="center",
            va=vertical_alignment,
            fontsize=8.5,
            fontweight="bold",
            color="#303946",
        )

    # White card with a subtle border behind title, note, and plot area.
    card = plt.Rectangle(
        (0.025, 0.06),
        0.95,
        0.88,
        transform=fig.transFigure,
        facecolor="white",
        edgecolor="#e1e6ed",
        linewidth=1.0,
        zorder=-1,
    )
    fig.patches.append(card)

    fig.savefig(output, dpi=dpi, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)


def _atomic_write_json(path: Path, value: object) -> None:
    """Write JSON without exposing readers to a partially written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def publish_report(
    weekly: pd.DataFrame,
    output: str | Path,
    publish_dir: str | Path,
) -> tuple[dict[str, object], bool, Path]:
    """Archive the chart and update the static Web App report manifest."""
    output_path = Path(output).expanduser().resolve()
    site_dir = Path(publish_dir).expanduser().resolve()
    reports_dir = site_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    source_date = pd.Timestamp(weekly["end date"].iloc[-1]).strftime("%Y-%m-%d")
    archive_path = reports_dir / f"{source_date}.png"
    manifest_path = site_dir / "reports.json"

    existing_manifest: dict[str, object] = {"reports": []}
    if manifest_path.is_file():
        try:
            loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and isinstance(loaded.get("reports"), list):
                existing_manifest = loaded
        except (OSError, json.JSONDecodeError):
            print("Warning: rebuilding invalid reports.json", file=sys.stderr)

    existing_reports = existing_manifest.get("reports", [])
    assert isinstance(existing_reports, list)
    existing = next(
        (
            item
            for item in existing_reports
            if isinstance(item, dict) and item.get("id") == source_date
        ),
        None,
    )
    is_new = existing is None
    generated_at = (
        str(existing.get("generated_at"))
        if existing and existing.get("generated_at")
        else datetime.now(timezone.utc).isoformat(timespec="seconds")
    )

    latest_change = float(weekly["weekly change"].iloc[-1])
    net_change = float(weekly["weekly change"].sum())
    ending_tonnes = float(weekly["ending tonnes"].iloc[-1])
    report: dict[str, object] = {
        "id": source_date,
        "source_date": source_date,
        "generated_at": generated_at,
        "image": f"reports/{source_date}.png",
        "weeks": int(len(weekly)),
        "latest_change": round(latest_change, 2),
        "net_change": round(net_change, 2),
        "ending_tonnes": round(ending_tonnes, 2),
    }

    shutil.copy2(output_path, archive_path)
    updated = [
        item
        for item in existing_reports
        if not (isinstance(item, dict) and item.get("id") == source_date)
    ]
    updated.append(report)
    updated.sort(
        key=lambda item: str(item.get("source_date", ""))
        if isinstance(item, dict)
        else "",
        reverse=True,
    )
    manifest = {
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "reports": updated,
    }
    # Avoid a daily Git commit when SPDR has not published a new data date.
    if not is_new and existing_manifest.get("reports") == updated:
        manifest["updated_at"] = existing_manifest.get("updated_at", generated_at)
    _atomic_write_json(manifest_path, manifest)
    return report, is_new, archive_path


def send_telegram_photo(
    image_path: str | Path,
    report: dict[str, object],
    web_app_url: str = "",
) -> bool:
    """Send a new report to Telegram when bot credentials are configured."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print(
            "Telegram skipped: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is not set."
        )
        return False

    caption_lines = [
        f"SPDR GLD 报告 · 数据截至 {report['source_date']}",
        f"最新周变化：{float(report['latest_change']):+.2f} 吨",
        f"近 {report['weeks']} 周合计：{float(report['net_change']):+.2f} 吨",
        f"最新持仓：{float(report['ending_tonnes']):.2f} 吨",
    ]
    if web_app_url.strip():
        caption_lines.extend(["", f"查看全部历史：{web_app_url.strip()}"])

    endpoint = f"{TELEGRAM_API_URL}/bot{token}/sendPhoto"
    try:
        with Path(image_path).open("rb") as image_file:
            response = requests.post(
                endpoint,
                data={"chat_id": chat_id, "caption": "\n".join(caption_lines)},
                files={"photo": (Path(image_path).name, image_file, "image/png")},
                timeout=45,
            )
        if not response.ok:
            raise RuntimeError(f"Telegram HTTP {response.status_code}: {response.text[:300]}")
        payload = response.json()
    except requests.RequestException as exc:
        # Never include the endpoint in the exception: it contains the bot token.
        raise RuntimeError(f"Telegram network request failed: {type(exc).__name__}") from exc
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram rejected the report: {payload}")
    print("Telegram report sent successfully.")
    return True


def _print_results(weekly: pd.DataFrame) -> None:
    display = weekly[
        [
            "week start",
            "week end",
            "start date",
            "end date",
            "weekly change",
            "ending tonnes",
        ]
    ].copy()
    for column in ("week start", "week end", "start date", "end date"):
        display[column] = display[column].map(lambda value: pd.Timestamp(value).date())
    display["weekly change"] = display["weekly change"].map(lambda value: f"{value:+.2f}")
    display["ending tonnes"] = display["ending tonnes"].map(lambda value: f"{value:.2f}")
    print(display.to_string(index=False))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a SPDR GLD weekly holdings net-change bar chart."
    )
    parser.add_argument("--file", help="Local SPDR GLD Historical Archive Excel file.")
    parser.add_argument("--weeks", type=int, default=6, help="Number of weeks to plot.")
    parser.add_argument(
        "--output",
        default="charts/gld_weekly_net_change.png",
        help="Output PNG path.",
    )
    parser.add_argument(
        "--cache-file",
        default="charts/spdr_gld_historical_archive.xlsx",
        help="Last-known-good workbook used when the SPDR download is unavailable.",
    )
    parser.add_argument(
        "--publish-dir",
        default="docs",
        help="Static Web App directory where dated reports are archived.",
    )
    parser.add_argument(
        "--no-publish",
        action="store_true",
        help="Generate only the requested output; do not update the Web App archive.",
    )
    parser.add_argument(
        "--send-telegram",
        action="store_true",
        help="Send Telegram only when the official data date creates a new report.",
    )
    args = parser.parse_args(argv)

    try:
        if args.file:
            source: str | Path | BytesIO = Path(args.file)
            print(f"Reading local workbook: {source}")
        else:
            print("Downloading official SPDR GLD Historical Archive workbook...")
            source, source_description = download_with_cache(args.cache_file)
            print(f"Data source: {source_description}")

        data, source_info = load_gld_data(source)
        weekly = calc_weekly_changes(data, weeks=args.weeks)
        plot_weekly_chart(weekly, output=args.output)

        if not args.no_publish:
            report, is_new, archive_path = publish_report(
                weekly, args.output, args.publish_dir
            )
            state = "new" if is_new else "updated existing"
            print(f"Published {state} report: {archive_path}")
            if args.send_telegram:
                if is_new:
                    send_telegram_photo(
                        archive_path,
                        report,
                        os.environ.get("WEB_APP_URL", ""),
                    )
                else:
                    print("Telegram skipped: this data date was already published.")

        print(
            "Parsed workbook using "
            f"sheet={source_info.sheet_name!r}, "
            f"date_column={source_info.date_column!r}, "
            f"tonnes_column={source_info.tonnes_column!r}"
        )
        _print_results(weekly)
        print(f"Saved chart: {args.output}")
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
