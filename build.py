"""One command: raw files -> checks -> consolidation -> dashboard, PDF report, visuals.

    python build.py
"""
import subprocess
import time
from pathlib import Path

from pipeline.run import run
from render import dashboard, report, shoot, showcase

OUT = Path(__file__).resolve().parent / "output"
SHOW = OUT / "portfolio"


def main():
    t0 = time.perf_counter()
    SHOW.mkdir(parents=True, exist_ok=True)
    r = run()
    dash = shoot.screenshot(dashboard.build(r), OUT / "dashboard.png")
    pdf = shoot.pdf(report.build(r), OUT / "investor_report_sept2026.pdf")
    subprocess.run(["pdftoppm", "-r", "150", "-png", "-f", "1", "-l", "1", "-singlefile", str(pdf), str(OUT / "report_p1")], check=True)
    total = time.perf_counter() - t0

    shoot.screenshot(showcase.cover(r, dash, OUT / "report_p1.png"), SHOW / "01_cover.png")
    shoot.screenshot(dashboard.build(r), SHOW / "02_dashboard.png")
    shoot.screenshot(showcase.messy_to_clean(r), SHOW / "03_data_quality.png")
    shoot.screenshot(showcase.architecture(r), SHOW / "04_architecture.png")
    (SHOW / "05_investor_report_sept2026.pdf").write_bytes(pdf.read_bytes())
    print(f"data pipeline {r['runtime_s']:.2f}s · full build incl. PDF {total:.1f}s")


if __name__ == "__main__":
    main()
