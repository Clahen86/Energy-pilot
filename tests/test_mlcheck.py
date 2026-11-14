"""An old CPU: numpy stops with a RuntimeError - the learning models are switched off quietly, once."""

import builtins

from energy_pilot import mlcheck


def test_old_cpu_turns_ml_off(monkeypatch):
    real = builtins.__import__

    def fake(name, *a, **k):
        if name.startswith("sklearn"):
            raise RuntimeError("NumPy was built with baseline optimizations: (X86_V2) but your machine doesn't support: (X86_V2).")
        return real(name, *a, **k)

    monkeypatch.setattr(mlcheck, "_state", {})
    monkeypatch.setattr(builtins, "__import__", fake)
    assert mlcheck.ok() is False
    assert mlcheck.why() == "cpu"
    monkeypatch.setattr(builtins, "__import__", real)
    assert mlcheck.ok() is False  # remembered - not tried again every hour


def test_works_normally(monkeypatch):
    monkeypatch.setattr(mlcheck, "_state", {})
    assert mlcheck.ok() is True and mlcheck.why() is None
