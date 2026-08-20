from pathlib import Path

from app.cli import build_parser
from app.diagnostics import benchmark_directory, diagnose


def test_storage_benchmark_is_bounded_and_cleans_up(tmp_path):
    result = benchmark_directory(tmp_path, size_mb=1)

    assert result["ok"] is True
    assert result["sample_mb"] == 1
    assert result["write_mib_s"] > 0
    assert result["read_mib_s"] > 0
    assert list(Path(tmp_path).glob(".picmanager-bench-*")) == []


def test_diagnose_reports_local_network_without_claiming_an_external_speed(tmp_path):
    report = diagnose([tmp_path], size_mb=1)

    assert len(report["storage"]) == 1
    assert report["network"]["external_speed_tested"] is False
    assert "Wi-Fi link rate" in report["network"]["note"]


def test_cli_exposes_configurable_diagnose_command(tmp_path):
    args = build_parser().parse_args(["diagnose", "--path", str(tmp_path), "--size-mb", "1"])

    assert args.path == [str(tmp_path)]
    assert args.size_mb == 1
    assert args.func.__name__ == "cmd_diagnose"
