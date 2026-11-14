"""How this installation is set up - sent with the daily question when sharing is on, so the brand profiles can be
fixed: each inverter/battery and charger with its integration, profile, maker and model, the entities used (what for,
their values), what failed. Entity names are sent with the user's own device name taken out
("select.<device>_export_limiter") unless "Share my setup" is on. Never names of people or places, never history."""

from __future__ import annotations

import re
from typing import Any

BATTERY_ROLES = ("battery_power", "battery_soc", "pv_power", "grid_power", "house_power", "solar_today", "sell_price")
CAR_ROLES = ("ev_power", "ev_plug", "ev_soc")


def _slug(text: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", str(text).lower())).strip("_")


def mask(entity_id: str, reg: dict[str, Any], devices: dict[str, Any]) -> str:
    dom, obj = entity_id.split(".", 1)
    e = reg.get(entity_id) or {}
    d = devices.get(e.get("device_id") or "") or {}
    for n in [x for x in (d.get("name_by_user"), d.get("name")) if x]:
        s = _slug(n)
        if s and (obj == s or obj.startswith(s + "_")):
            return f"{dom}.<device>{obj[len(s):]}"
    if e.get("translation_key") or (e.get("has_entity_name") and e.get("original_name")):
        return f"{dom}.<device>_{_slug(e.get('translation_key') or e.get('original_name'))}"
    return f"{dom}.<name>"


def entity(entity_id: str, use: str, states: dict[str, Any], reg: dict[str, Any], devices: dict[str, Any], full: bool) -> dict[str, Any]:
    st = states.get(entity_id) or {}
    a = st.get("attributes") or {}
    e = reg.get(entity_id) or {}
    out: dict[str, Any] = {"name": entity_id if full else mask(entity_id, reg, devices), "use": use, "platform": e.get("platform")}
    if e.get("translation_key"):
        out["key"] = e["translation_key"]
    for k in ("unit_of_measurement", "device_class", "min", "max", "step"):
        if isinstance(a.get(k), (str, int, float)) and len(str(a[k])) < 30:
            out[k] = a[k]
    if isinstance(a.get("options"), list):
        out["options"] = [str(x)[:40] for x in a["options"][:25]]
    dom = entity_id.split(".")[0]
    if dom in ("select", "switch", "binary_sensor") and st.get("state") is not None:
        out["state"] = str(st["state"])[:40]
    return out


def _bucket(v: Any, edges: list[float], unit: str) -> str | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    lo = 0.0
    for hi in edges:
        if x < hi:
            return f"{lo:g}-{hi:g} {unit}"
        lo = hi
    return f"{lo:g}+ {unit}"


def collect(ov: Any, full: bool) -> dict[str, Any]:
    c = getattr(ov, "controller", None)
    states = ov.ha.states
    reg = getattr(c, "_ent_reg", None) or {}
    devices = getattr(c, "_devices", None) or {}
    s = ov.settings
    out_devices: list[dict[str, Any]] = []
    if c:
        for part in c.parts():
            if part == "generator":
                continue
            ents = list(c.entities.get(part) or [])
            plat = (c.platforms.get(part) if hasattr(c, "platforms") else None)
            roles = BATTERY_ROLES if c.is_battery(part) else CAR_ROLES if part == "car" else ()
            role_ents = [(r, ov.role(r)) for r in roles if part in ("battery", "car") and ov.role(r)]
            if not ents and not role_ents and not plat:
                continue
            # what each control is used for: the intents whose calls use it
            uses: dict[str, set[str]] = {}
            try:
                want = (c.intents() or {}).get(part)
                if want:
                    for intent in ("normal", "hold", "charge", "export") if c.is_battery(part) else ("charge", "stop"):
                        for call in c.calls(part, {**want, "intent": intent}) or []:
                            e = (call.get("data") or {}).get("entity_id")
                            if isinstance(e, str):
                                uses.setdefault(e, set()).add(intent)
                            elif call.get("domain") and call.get("service"):
                                uses.setdefault(f"{call['domain']}.{call['service']}", set()).add(intent)
            except Exception:  # noqa: BLE001
                pass
            first = role_ents[0][1] if role_ents else (ents[0] if ents else None)
            dev = devices.get((reg.get(first or "") or {}).get("device_id") or "") or {}
            rows = [entity(e, role, states, reg, devices, full) for role, e in role_ents]
            rows += [entity(e, "+".join(sorted(uses.get(e, []))) or "control", states, reg, devices, full) for e in ents if e not in dict(role_ents).values()][:30]
            rows += [{"name": k, "use": "+".join(sorted(v)), "platform": k.split(".")[0]} for k, v in uses.items() if k not in states and "." in k and not k.startswith(("number.", "select.", "switch.", "button."))]
            last = (c.last.get(part) or {}) if hasattr(c, "last") else {}
            res = str(last.get("result") or "")
            errs = list(getattr(c, "part_errors", {}).get(part, []))[-3:]
            out_devices.append({
                "kind": "battery" if c.is_battery(part) else "charger", "platform": plat or ((reg.get(first or "") or {}).get("platform")),
                "profile": c.profile_key(part) if c.is_battery(part) else None,
                "manufacturer": str(dev.get("manufacturer") or "")[:60], "model": str(dev.get("model") or "")[:60],
                "ok": (res == "ok") if res and c.mode(part) == "control" else None, "errors": errs, "entities": rows,
                "extra": {"mode": c.mode(part), "changed_back_1h": len((getattr(c, "drift", {}) or {}).get(part, [])),
                          "blocked": bool(c.blocked(part))},
            })
    src = str(ov.source("price") or "") if hasattr(ov, "source") else ""
    if src:
        pe = ov.role("price")
        out_devices.append({"kind": "price", "platform": src.split(":", 1)[1] if src.startswith("integration:") else src,
                            "entities": [entity(pe, "price", states, reg, devices, full)] if pe else []})
    cu = s.get("curtail") or {}
    test = (s.get("curtail_test") or {}).get("result")
    if cu.get("entity"):
        out_devices.append({"kind": "export_limit", "platform": (reg.get(cu["entity"]) or {}).get("platform"), "ok": None if test in (None, "no_sun", "no_setting") else test == "ok",
                            "errors": [f"test: {test}"] if test in ("failed", "rejected") else [],
                            "entities": [entity(cu["entity"], f"stop selling = {cu.get('value')}", states, reg, devices, full)]
                            + [entity(e, f"stop selling = {v}", states, reg, devices, full) for e, v in cu.get("extra") or [] if e in states]})
    st_test = s.get("selftest") or {}
    return {
        "devices": out_devices,
        "features": {"sell_from_battery": bool(s.get("battery_export")), "stop_selling": bool(cu.get("on")), "stop_selling_test": test or "-",
                     "grid_charge": bool(s.get("grid_charge")), "ev_follow_sun": bool(s.get("ev_follow_sun")), "runs_cheaply": bool(s.get("things")),
                     "power_tariff": bool(s.get("power_tariff_price")), "offgrid": bool(s.get("offgrid")), "battery_targets": bool(s.get("battery_targets")),
                     "tariff": str(s.get("price_source") or s.get("tariff") or "spot")[:20]},
        "sizes": {k: v for k, v in {"battery": _bucket(s.get("battery_kwh"), [5, 10, 15, 20, 30], "kWh"),
                                    "fuse": _bucket(s.get("import_limit_kw"), [10, 15, 20, 30], "kW"),
                                    "charger": _bucket(s.get("charger_kw"), [4, 8, 12], "kW")}.items() if v},
        "counts": {k: v for k, v in {"self_test_steps": len(st_test.get("results") or []),
                                     "fixes_by_itself": len(s.get("autofix_log") or [])}.items() if v is not None},
    }
