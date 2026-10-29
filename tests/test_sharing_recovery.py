from deploy.share_runner import ConnectionHealth
from deploy import share_runner
from unittest.mock import Mock


def test_expired_tunnel_restarts_even_when_process_is_alive():
    health = ConnectionHealth(0)
    assert not health.observe(True, 10)
    assert not health.observe(False, 100)
    assert not health.observe(False, 115)
    assert health.observe(False, 130)


def test_transient_failure_recovers_without_restarting():
    health = ConnectionHealth(0)
    assert not health.observe(True, 10)
    assert not health.observe(False, 20)
    assert not health.observe(False, 35)
    assert not health.observe(True, 50)
    assert health.failures == 0
    assert not health.observe(False, 65)


def test_initial_dns_registration_has_a_grace_period():
    health = ConnectionHealth(100)
    for now in (100, 115, 130, 145, 160, 175):
        assert not health.observe(False, now)
    assert health.observe(False, 190)


def test_stopped_core_and_gateway_are_restarted(monkeypatch, tmp_path):
    monkeypatch.setattr(share_runner, "WORK", tmp_path)
    monkeypatch.setattr(share_runner, "ready", lambda url: None)
    monkeypatch.setattr(share_runner, "listening", lambda port: False)
    run, popen = Mock(), Mock()
    monkeypatch.setattr(share_runner.subprocess, "run", run)
    monkeypatch.setattr(share_runner.subprocess, "Popen", popen)
    assert not share_runner.restore_local_services({})
    assert "start.ps1" in run.call_args.args[0][-1]
    assert "run_share.py" in popen.call_args.args[0][-1]


def test_occupied_unhealthy_ports_never_create_duplicate_services(monkeypatch):
    monkeypatch.setattr(share_runner, "ready", lambda url: None)
    monkeypatch.setattr(share_runner, "listening", lambda port: True)
    run, popen = Mock(), Mock()
    monkeypatch.setattr(share_runner.subprocess, "run", run)
    monkeypatch.setattr(share_runner.subprocess, "Popen", popen)
    assert not share_runner.restore_local_services({})
    run.assert_not_called()
    popen.assert_not_called()


def test_healthy_services_remain_untouched(monkeypatch):
    monkeypatch.setattr(share_runner, "ready", lambda url: {"online": True})
    run, popen = Mock(), Mock()
    monkeypatch.setattr(share_runner.subprocess, "run", run)
    monkeypatch.setattr(share_runner.subprocess, "Popen", popen)
    assert share_runner.restore_local_services({})
    run.assert_not_called()
    popen.assert_not_called()
