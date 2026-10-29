from deploy.share_runner import ConnectionHealth


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
