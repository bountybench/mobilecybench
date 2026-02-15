def test_host_bridge_log_writes_file_without_stdout(monkeypatch, tmp_path, capsys):
    from tools import host_bridge

    logfile = tmp_path / "bridge.log"
    monkeypatch.setattr(host_bridge, "LOGFILE", str(logfile))
    monkeypatch.delenv("MCB_BRIDGE_STDOUT", raising=False)

    host_bridge.log("line1")

    out = capsys.readouterr()
    assert out.out == ""
    assert logfile.read_text(encoding="utf-8") == "line1\n"


def test_host_bridge_log_optionally_prints_stdout(monkeypatch, tmp_path, capsys):
    from tools import host_bridge

    logfile = tmp_path / "bridge.log"
    monkeypatch.setattr(host_bridge, "LOGFILE", str(logfile))
    monkeypatch.setenv("MCB_BRIDGE_STDOUT", "1")

    host_bridge.log("line2")

    out = capsys.readouterr()
    assert "line2" in out.out
    assert logfile.read_text(encoding="utf-8") == "line2\n"
