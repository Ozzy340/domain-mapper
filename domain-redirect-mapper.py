#!/usr/bin/env python3
"""
Domain Redirect Mapper

Reads a CSV of domains/subdomains, loads each URL sequentially in a real browser
(Playwright/Chromium) so server and JavaScript redirects are followed, then
exports a CSV showing, for each source URL, the final destination URL, how many
input domains point to that destination domain, and whether the destination is
in the original list.

Output columns:
- source_url
- destination_url
- pointing_to_count  (how many *input* domains point to this destination domain)
- points_to_list_domain (True/False)

By default, counting is done at the *registrable domain* level (e.g.,
sub.example.co.uk -> example.co.uk). You can change this to count by full host
with --count-by host.

Usage:
  python domain_redirect_mapper.py input.csv -o output.csv

CSV format:
  The script accepts either a header named 'url' or 'domain'. If there is no
  header, it treats the *first* column as the URL list.

Setup (first time):
  python -m venv .venv && source .venv/bin/activate  # on Windows: .venv\\Scripts\\activate
  pip install playwright tldextract
  playwright install chromium

Notes:
  - The script is sequential by design (per your requirement).
  - It tries HTTPS first, then falls back to HTTP if needed.
  - Timeouts can be tuned via CLI flags.
"""

import argparse
import asyncio
import csv
import sys
import time
import io
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

# Optional dependency handling for registrable domain extraction
try:
    import tldextract  # type: ignore
    def registrable_domain(hostname: str) -> str:
        if not hostname:
            return ""
        ext = tldextract.extract(hostname)
        if not ext.registered_domain:
            # e.g., localhost or an IP address
            return hostname.lower()
        return ext.registered_domain.lower()
except Exception:
    # Fallback: use netloc as-is (less accurate for multi-level TLDs)
    def registrable_domain(hostname: str) -> str:
        return (hostname or "").lower()


@dataclass
class Row:
    source_url: str
    destination_url: str
    pointing_to_count: int
    points_to_list_domain: bool


def format_hhmmss(total_seconds: float) -> str:
    seconds = max(0, int(total_seconds))
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 99:
        hours = 99
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def build_progress_bar(completed: int, total: int, width: int = 30) -> str:
    if total <= 0:
        return "[{}]".format("." * width)
    if completed >= total:
        return "[{}]".format("=" * width)
    filled = int(width * (completed / total))
    filled = min(filled, width - 1)
    return "[{}>{}]".format("=" * filled, "." * (width - filled - 1))


def truncate_label(label: str, max_len: int = 40) -> str:
    label = label or ""
    if len(label) <= max_len:
        return label
    # Preserve both start and end so TLDs/suffixes remain visible
    if max_len <= 6:
        return label[: max_len]
    prefix_len = (max_len - 3) // 2
    suffix_len = max_len - 3 - prefix_len
    return label[:prefix_len] + "..." + label[-suffix_len:]


def render_progress_line(completed: int, total: int, elapsed_s: float, current_label: str) -> str:
    percent = 0.0 if total == 0 else (completed / total) * 100.0
    avg = 0.0 if completed == 0 else (elapsed_s / completed)
    eta_s = avg * max(0, total - completed)
    bar = build_progress_bar(completed, total)
    elapsed_txt = format_hhmmss(elapsed_s)
    eta_txt = format_hhmmss(eta_s)
    label = truncate_label(current_label, 40)
    return (
        f"{bar} {completed:>4}/{total:<4} {percent:5.1f}% "
        f"elapsed {elapsed_txt} eta {eta_txt} | current: {label}"
    )


def ensure_url_scheme(raw: str) -> Tuple[str, str]:
    """Return a tuple of (https_url, http_url) for a raw domain/URL string.
    If a scheme is present, https_url == http_url == raw.
    """
    raw = raw.strip()
    if not raw:
        return raw, raw
    parsed = urlparse(raw)
    if parsed.scheme:
        return raw, raw
    # treat input as hostname/path-like domain
    return f"https://{raw}", f"http://{raw}"


async def resolve_final_url(page, start_url: str, timeout_ms: int, js_settle_ms: int) -> str:
    """Navigate to start_url and try to capture the final URL after redirects.

    We wait for 'networkidle', then give a small window for JS redirects
    (location changes, meta refresh) by polling the URL for js_settle_ms.
    """
    await page.goto(start_url, timeout=timeout_ms, wait_until="domcontentloaded")
    # Try to wait for network to settle, but don't block forever
    try:
        await page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except Exception:
        pass  # continue regardless; some sites never reach networkidle

    # Poll for JS-driven URL changes for js_settle_ms
    final_url = page.url
    if js_settle_ms > 0:
        remaining = js_settle_ms
        step = 250
        while remaining > 0:
            await page.wait_for_timeout(min(step, remaining))
            current = page.url
            if current != final_url:
                final_url = current
                # Reset small window to catch cascading redirects
                remaining = min(js_settle_ms, remaining + 2 * step)
            remaining -= step
    return final_url


async def process_one(context, raw: str, timeout_ms: int, js_settle_ms: int) -> str:
    """Return the final resolved URL for the given raw url/domain.
    Tries HTTPS first, then HTTP.
    """
    https_url, http_url = ensure_url_scheme(raw)
    page = await context.new_page()
    final_url = ""
    try:
        final_url = await resolve_final_url(page, https_url, timeout_ms, js_settle_ms)
    except Exception:
        # Try HTTP fallback if HTTPS path failed and wasn't already HTTP
        if https_url != http_url:
            try:
                final_url = await resolve_final_url(page, http_url, timeout_ms, js_settle_ms)
            except Exception:
                final_url = ""
        else:
            final_url = ""
    finally:
        await page.close()
    return final_url


def read_input_csv(path: Path) -> List[str]:
    urls: List[str] = []
    text = path.read_text(encoding="utf-8")
    text = text.lstrip("\ufeff")  # strip BOM if present

    # Try robust CSV parsing with restricted delimiters to avoid breaking on ':' in http://
    sniffer = csv.Sniffer()
    sample = text[:2048]
    try:
        dialect = sniffer.sniff(sample, delimiters=",;\t|")
    except Exception:
        dialect = csv.excel

    reader = csv.reader(io.StringIO(text), dialect)
    rows = list(reader)

    # Fallback: if it looks like the first row was split into characters, treat as plain lines
    if rows and len(rows[0]) > 1 and all(len(cell) == 1 for cell in rows[0]):
        lines = [ln.strip() for ln in text.splitlines()]
        lines = [ln for ln in lines if ln]
        if lines and lines[0].strip().lower() in ("url", "domain"):
            lines = lines[1:]
        return lines

    if not rows:
        return urls

    header_like = [c.strip().lower() for c in rows[0]]
    start_idx = 1
    col_idx = 0
    if any(h in ("url", "domain") for h in header_like):
        # Choose first matching header column
        for i, h in enumerate(header_like):
            if h in ("url", "domain"):
                col_idx = i
                break
    else:
        # No header; start from first row
        start_idx = 0
        col_idx = 0

    for r in rows[start_idx:]:
        if not r:
            continue
        cell = (r[col_idx] if col_idx < len(r) else "").strip()
        if cell:
            urls.append(cell)
    return urls


def hostname_from_url(u: str) -> str:
    try:
        parsed = urlparse(u)
        if parsed.netloc:
            return parsed.hostname or parsed.netloc
        # If user passed a bare domain with scheme already included oddly
        return parsed.path
    except Exception:
        return ""


def build_counts(
    sources: List[str],
    destinations: List[str],
    count_by: str,
) -> Tuple[List[Row], Dict[str, int]]:
    """Create output rows and a map of destination-domain -> inbound count.

    count_by: 'registrable' or 'host'
    """
    # Normalize the input domain list for membership checks
    input_hosts = set()
    input_regs = set()
    for raw in sources:
        _, http_url = ensure_url_scheme(raw)
        host = hostname_from_url(http_url).lower()
        if host:
            input_hosts.add(host)
            input_regs.add(registrable_domain(host))

    # Build inbound counts keyed by chosen granularity
    inbound: Dict[str, int] = {}
    dest_keys: List[str] = []
    for dest in destinations:
        host = hostname_from_url(dest).lower() if dest else ""
        key = registrable_domain(host) if count_by == "registrable" else host
        dest_keys.append(key)
        if key:
            inbound[key] = inbound.get(key, 0) + 1

    # Build rows, including points_to_list_domain flag based on registrable match
    rows: List[Row] = []
    for src, dest, key in zip(sources, destinations, dest_keys):
        dest_host = hostname_from_url(dest).lower() if dest else ""
        dest_reg = registrable_domain(dest_host) if dest_host else ""
        points_to_list = dest_reg in input_regs if dest_reg else False
        count = inbound.get(key, 0) if key else 0
        rows.append(Row(
            source_url=src,
            destination_url=dest,
            pointing_to_count=count,
            points_to_list_domain=points_to_list,
        ))
    return rows, inbound


async def main():
    parser = argparse.ArgumentParser(description="Map domains to their final destinations via a real browser.")
    parser.add_argument("input_csv", type=Path, help="Path to input CSV with a 'url' or 'domain' column (or first column).")
    parser.add_argument("-o", "--output-csv", type=Path, default=Path("redirect_map.csv"), help="Where to write the results CSV.")
    parser.add_argument("--timeout", type=int, default=15000, help="Navigation timeout per attempt, in ms. Default: 15000")
    parser.add_argument("--js-settle", type=int, default=2000, help="Extra time to detect JS redirects, in ms. Default: 2000")
    parser.add_argument("--count-by", choices=["registrable", "host"], default="registrable", help="How to group destinations for counting. Default: registrable")
    parser.add_argument("--user-agent", type=str, default="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118 Safari/537.36", help="Browser User-Agent to use.")
    parser.add_argument("--ignore-https-errors", action="store_true", help="Ignore HTTPS certificate errors.")

    args = parser.parse_args()

    urls = read_input_csv(args.input_csv)
    if not urls:
        print("No URLs found in input CSV.", file=sys.stderr)
        sys.exit(2)

    total_urls = len(urls)
    print(f"Found {total_urls} domain(s) to process.")

    try:
        from playwright.async_api import async_playwright  # type: ignore
    except ImportError:
        print("Playwright is not installed. Run: pip install playwright && playwright install chromium", file=sys.stderr)
        sys.exit(3)

    destinations: List[str] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=args.user_agent,
            ignore_https_errors=args.ignore_https_errors,
            java_script_enabled=True,
        )
        # Sequential processing
        start_time = time.time()
        is_tty = sys.stdout.isatty()
        for i, raw in enumerate(urls, 1):
            # Render progress
            elapsed = time.time() - start_time
            progress_line = render_progress_line(i - 1, total_urls, elapsed, f"{raw}")
            if is_tty:
                sys.stdout.write("\r" + progress_line)
                sys.stdout.flush()
            else:
                # Non-TTY: print a clean line to avoid stray carriage returns
                print(progress_line)

            final_url = await process_one(context, raw, args.timeout, args.js_settle)
            if not final_url:
                final_url = ""
            destinations.append(final_url)

            # Per-domain result line with full final URL (scheme included)
            if is_tty:
                sys.stdout.write("\r" + (" " * max(len(progress_line), 80)) + "\r")
                sys.stdout.flush()
            print(f"[{i}/{total_urls}] input: {raw} -> final: {final_url}")

        # Final 100% progress update for TTY only
        if is_tty:
            elapsed = time.time() - start_time
            final_line = render_progress_line(total_urls, total_urls, elapsed, "done")
            sys.stdout.write("\r" + final_line + "\n")
            sys.stdout.flush()
        await context.close()
        await browser.close()

    rows, inbound = build_counts(urls, destinations, args.count_by)

    # Write CSV
    out_path: Path = args.output_csv
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["source_url", "destination_url", "pointing_to_count", "points_to_list_domain"])
        writer.writeheader()
        for r in rows:
            writer.writerow(asdict(r))

    # Summary
    total = len(rows)
    in_list = sum(1 for r in rows if r.points_to_list_domain)
    abs_out = out_path.resolve()
    print(f"\nDone. Processed {total_urls} domain(s). Wrote {total} rows to {abs_out}.")
    print(f"{in_list} source(s) point to a domain in the input list (by registrable match).")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Interrupted by user.")
