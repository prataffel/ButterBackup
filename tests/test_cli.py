import re
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from unittest import mock

import pytest
from loguru import logger
from typer.testing import CliRunner

from butter_backup import cli
from butter_backup import device_managers as dm
from butter_backup.cli import app


def get_random_filename() -> str:
    with NamedTemporaryFile() as named_file:
        return named_file.name


def in_docker_container() -> bool:
    return Path("/.dockerenv").exists()


@pytest.fixture
def runner():
    return CliRunner(mix_stderr=False)


def test_get_default_config_path() -> None:
    with TemporaryDirectory() as tempdir:
        xdg_config_dir = Path(tempdir)
    with mock.patch("os.getenv", {"XDG_CONFIG_HOME": xdg_config_dir}.get):
        config_file = cli.get_default_config_path()
    expected_cfg = xdg_config_dir / cli.DEFAULT_CONFIG_NAME
    assert str(expected_cfg) == config_file


@pytest.mark.parametrize(
    "logmsg",
    [
        "Schläft ein Lied in allen Dingen,",
        "Die da träumen fort und fort,",
        "Und die Welt hebt an zu singen,",
        "Triffst du nur das Zauberwort.",
    ],
)
@pytest.mark.parametrize("logfunc", [logger.warning, logger.error])
def test_setup_logging_logs_errors_and_warnings_by_default(
    logmsg: str, logfunc, capsys
) -> None:
    cli.setup_logging(verbosity=0)
    logfunc(logmsg)
    out, err = capsys.readouterr()
    err_without_linebreak = err[:-1]
    assert out == ""
    assert err_without_linebreak.endswith(logmsg)


def test_setup_logging_does_not_log_more_than_warnings_by_default(capsys) -> None:
    cli.setup_logging(verbosity=0)
    logger.success("This line will not appear anywhere.")
    out, err = capsys.readouterr()
    assert out == ""
    assert err == ""


def test_setup_logging_logs_success(capsys) -> None:
    successmsg = "☕️🤎📰📜⚰️🕰🕯🎻🖋"
    infomsg = "🦖🦕🐊"
    cli.setup_logging(verbosity=1)
    logger.success(successmsg)
    logger.info(infomsg)
    out, err = capsys.readouterr()
    err_without_linebreak = err[:-1]
    assert out == ""
    assert infomsg not in err
    assert err_without_linebreak.endswith(successmsg)


def test_setup_logging_clamps_level(capsys) -> None:
    successmsg = "√-1 2³ Σ π and it was delicious"
    tracemsg = "Trace me if you can!"
    cli.setup_logging(verbosity=1337)
    logger.success(successmsg)
    logger.trace(tracemsg)
    out, err = capsys.readouterr()
    assert out == ""
    assert successmsg in err
    assert tracemsg in err


def test_backup_refuses_missing_config(runner) -> None:
    config_file = Path(get_random_filename())
    result = runner.invoke(app, ["backup", "--config", str(config_file)])
    assert f"{config_file}" in result.stderr
    assert result.exit_code != 0


def test_open_refuses_missing_config(runner) -> None:
    config_file = Path(get_random_filename())
    result = runner.invoke(app, ["open", "--config", str(config_file)])
    assert f"{config_file}" in result.stderr
    assert result.exit_code != 0


@pytest.mark.skip("Impossible to implement!")
def test_open_refuses_missing_xdg_config(runner) -> None:
    # It seems as if this test cannot be implemented at the moment.
    #
    # This test resets XDG_CONFIG_HOME to provoke that get_default_config_path
    # returns a not existing config file. However, get_default_config_path is
    # executed at import time, rendering resetting XDG_CONFIG_HOME effectless.
    with TemporaryDirectory() as xdg_config_dir:
        pass
    with mock.patch("os.getenv", {"XDG_CONFIG_HOME": xdg_config_dir}.get):
        result = runner.invoke(app, ["open"])
    assert xdg_config_dir in result.stderr
    assert result.exit_code != 0


@pytest.mark.skipif(
    in_docker_container(), reason="Test is known to fail in Docker container"
)
def test_close_does_not_close_unopened_device(runner, encrypted_btrfs_device) -> None:
    config, device = encrypted_btrfs_device
    with NamedTemporaryFile() as tempf:
        config_file = Path(tempf.name)
        config_file.write_text(f"[{config.json()}]")
        close_result = runner.invoke(app, ["close", "--config", str(config_file)])
        assert close_result.stdout == ""
        assert close_result.exit_code == 0


@pytest.mark.skipif(
    in_docker_container(), reason="Test is known to fail in Docker container"
)
def test_open_close_roundtrip(runner, encrypted_device) -> None:
    config, device = encrypted_device
    expected_cryptsetup_map = Path(f"/dev/mapper/{config.UUID}")
    with NamedTemporaryFile() as tempf:
        config_file = Path(tempf.name)
        config_file.write_text(f"[{config.json()}]")
        open_result = runner.invoke(app, ["open", "--config", str(config_file)])
        expected_msg = f"Gerät {config.UUID} wurde in (?P<mount_dest>/[^ ]+) geöffnet."
        match = re.fullmatch(expected_msg, open_result.stdout.strip())
        assert match is not None
        mount_dest = Path(match.group("mount_dest"))
        assert any(
            mount_dest in destinations
            for destinations in dm.get_mounted_devices().values()
        )
        assert expected_cryptsetup_map.exists()
        runner.invoke(app, ["close", "--config", str(config_file)])
        assert not expected_cryptsetup_map.exists()
        assert not dm.is_mounted(mount_dest)
        assert not mount_dest.exists()
