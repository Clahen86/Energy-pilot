"""Italy: every supplier's household electricity offers from the Portale Offerte open data (ARERA / Acquirente Unico,
public, no account), turned into deals with time-of-use rules (tariffs.sched_price).

Sources, all published daily in the same open-data area:
- PO_Offerte_E_MLIBERO_YYYYMMDD.xml - free-market electricity offers (about 20 MB, ~3,400 offers, half for homes).
- PO_Offerte_E_PLACET_YYYYMMDD.csv  - the standardised PLACET offers; also the only place with supplier *names*
  (the XML only has the VAT number), so it doubles as the name lookup.
- PO_Parametri_E_YYYYMMDD.csv      - regulated parameters; we read LAMBDA (grid losses, 0.10).
- "Prezzi storici" CSV (linked from the open-data page under a hashed name) - monthly PUN/PE averages.

Prices in the files are excl. VAT and already include grid losses (ARERA's rules, del. 426/2020). The offers only
price the energy part; grid, system charges, excise and the regulated dispatching charge are the same for every
offer, so deals are "partial" and the engine adds the common part. We add 10 % VAT (Italian homes).

Index-linked offers are PUN (or "PUN Index GME") + spread. The index costs PUN * (1 + LAMBDA) * coefficient. With the
latest monthly PUN we put the whole price in the rate; without it the rate holds the spread only and the deal gets
"index": "PUN" and "index_mult" (what to multiply the PUN by, VAT included) so the engine could add it later.

Code meanings below come from the data itself and ARERA's "Regole per il calcolo degli indicatori sintetici di prezzo"
v2.0 (the XSD isn't public): TIPO_CLIENTE 01 = home; TIPO_OFFERTA 01 fixed, 02 variable, 04 mixed; TIPOLOGIA_FASCE
01 single rate, 03 F1/F2/F3, 91 F1 + F23, 07 peak/off-peak; UNITA_MISURA 01 EUR/year, 02 EUR/kW, 03 EUR/kWh,
05 EUR once; MACROAREA 05 one-off fees."""
from __future__ import annotations

import csv
import io
import logging
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)
SITE = "https://www.ilportaleofferte.it"
BASE = SITE + "/portaleOfferte/resources/opendata/csv"
OPEN_DATA_PAGE = SITE + "/portaleOfferte/it/open-data.page"
NS = "{http://www.acquirenteunico.it/schemas/SII_AU/OffertaRetail/01}"
VAT = 1.10           # IVA on household electricity
LAMBDA = 0.10        # grid-loss factor on the PUN; overwritten from the parameter file when it's there
KW = 3.0             # contracted power for the rare EUR/kW fees - the usual Italian home
MAX_DEALS = 600

WEEK, SAT = [0, 1, 2, 3, 4], [5]
# ARERA's bands. F3 is the catch-all at the end: nights, Sunday (and holidays, which we ignore).
F1_RULES = [(WEEK, 480, 1140)]
F2_RULES = [(WEEK, 420, 480), (WEEK, 1140, 1380), (SAT, 420, 1380)]
PEAK_RULES = [(WEEK, 480, 1200)]  # the power exchange's "peak": Mon-Fri 08-20
BANDS = {"01": ["F0"], "03": ["F1", "F2", "F3"], "91": ["F1", "F23"], "07": ["PEAK", "OFFPEAK"]}
# Which FASCIA_COMPONENTE codes price which band (a component without a band prices all of them).
FASCIA = {"F0": {"01"}, "F1": {"01"}, "F2": {"02", "91"}, "F3": {"03", "91"}, "F23": {"91", "02", "03"},
          "PEAK": {"07"}, "OFFPEAK": {"08"}}


def url_for(day: date) -> str:
    return f"{BASE}/offerteML/{day:%Y_%m}/PO_Offerte_E_MLIBERO_{day:%Y%m%d}.xml"


def placet_url(day: date) -> str:
    return f"{BASE}/offerte/{day:%Y_%m}/PO_Offerte_E_PLACET_{day:%Y%m%d}.csv"


def params_url(day: date) -> str:
    return f"{BASE}/parametri/{day:%Y_%m}/PO_Parametri_E_{day:%Y%m%d}.csv"


def candidates(day: date) -> list[str]:
    """Today's file, then yesterday's - the new one appears some time during the day."""
    return [url_for(day), url_for(day - timedelta(days=1))]


def _num(text: Any) -> float | None:
    try:
        return float(str(text).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None


def _url(u: str) -> str:
    u = (u or "").strip()
    return u if not u or u.startswith("http") else "https://" + u


def _rules(bands: dict[str, float]) -> list[dict[str, Any]]:
    """Band prices -> rules; the last rule is the catch-all band."""
    def mk(spec: list[tuple[list[int], int, int]], rate: float) -> list[dict[str, Any]]:
        return [{"days": list(d), "from": a, "to": b, "rate": rate} for d, a, b in spec]

    if "F0" in bands:
        return [{"days": None, "from": 0, "to": 1440, "rate": bands["F0"]}]
    if "PEAK" in bands:
        return mk(PEAK_RULES, bands["PEAK"]) + [{"days": None, "from": 0, "to": 1440, "rate": bands["OFFPEAK"]}]
    if "F23" in bands:
        return mk(F1_RULES, bands["F1"]) + [{"days": None, "from": 0, "to": 1440, "rate": bands["F23"]}]
    return mk(F1_RULES, bands["F1"]) + mk(F2_RULES, bands["F2"]) + [{"days": None, "from": 0, "to": 1440, "rate": bands["F3"]}]


def _deal(oid: str, name: str, supplier: str, url: str, year_fee: float, bands: dict[str, float],
          index: dict[str, float] | None, idx: str | None, mult: float) -> dict[str, Any] | None:
    """Net prices (EUR/year, EUR/kWh per band, excl. VAT) -> a deal incl. VAT; None when the numbers look broken.
    idx/mult: the index the energy price follows and its multiplier (losses x coefficient), or None for fixed."""
    value = (index or {}).get(idx) if idx else None
    if idx and value is not None:
        bands = {b: v + value * mult for b, v in bands.items()}
    lo, hi = (-0.05, 0.5) if idx and value is None else (0.0, 1.0)  # a bare spread can be 0 or slightly negative
    if not bands or not all(lo <= v <= hi for v in bands.values()) or not 0 <= year_fee <= 600:
        return None
    if not (idx and value is None) and max(bands.values()) <= 0:
        return None
    d: dict[str, Any] = {
        "id": "it:" + oid, "name": name.strip()[:80], "supplier": supplier.strip()[:60], "url": _url(url),
        "monthly": round(year_fee * VAT / 12, 2), "fit": None, "partial": True,
        "periods": [{"from": "01-01", "to": "12-31", "rules": _rules({b: round(v * VAT, 5) for b, v in bands.items()})}]}
    if idx and value is None:
        d["index"], d["index_mult"] = idx, round(mult * VAT, 4)
    return d


def _year_cost(d: dict[str, Any], index: dict[str, float] | None) -> float:
    """A rough year for a 2,700 kWh home - only to keep the cheapest when there are too many."""
    rules = d["periods"][0]["rules"]
    if len(rules) == 1:
        rate = rules[0]["rate"]
    elif len(rules) == 2:  # F1 + F23 or peak/off-peak
        w = 0.45 if rules[0]["to"] == 1200 else 0.33
        rate = w * rules[0]["rate"] + (1 - w) * rules[1]["rate"]
    else:
        rate = 0.33 * rules[0]["rate"] + 0.31 * rules[1]["rate"] + 0.36 * rules[-1]["rate"]
    if d.get("index"):
        rate += d["index_mult"] * ((index or {}).get(d["index"]) or 0.12)
    return d["monthly"] * 12 + 2700 * rate


def _offer(el: ET.Element, names: dict[str, str], index: dict[str, float] | None, today: date,
           lam: float) -> dict[str, Any] | None:
    def t(path: str) -> str:
        return (el.findtext(_p(path)) or "").strip()

    if t("DettaglioOfferta/TIPO_MERCATO") != "01" or t("DettaglioOfferta/TIPO_CLIENTE") != "01":
        return None  # electricity for homes only
    if t("DettaglioOfferta/DOMESTICO_RESIDENTE") == "02" or t("DettaglioOfferta/OFFERTA_SINGOLA") == "NO":
        return None  # non-residents only, or only sold together with gas
    if el.find(_p("ZoneOfferta")) is not None:
        return None  # sold only in some regions/towns
    try:
        if datetime.strptime(t("ValiditaOfferta/DATA_FINE")[:10], "%d/%m/%Y").date() < today:
            return None
    except ValueError:
        pass
    kind, bands_code = t("DettaglioOfferta/TIPO_OFFERTA"), t("TipoPrezzo/TIPOLOGIA_FASCE")
    if kind not in ("01", "02", "04") or bands_code not in BANDS:
        return None
    names_b = BANDS[bands_code]
    per_band = {b: 0.0 for b in names_b}
    year_fee = 0.0
    for c in el.iterfind(_p("ComponenteImpresa")):
        if (c.findtext(_p("MACROAREA")) or "").strip() == "05":
            continue  # one-off activation fees
        # Several entries per band = consumption tiers or time-limited prices: take the first tier (from 0 kWh).
        best: dict[tuple[str, str], tuple[float, float]] = {}
        for ip in c.iterfind(_p("IntervalloPrezzi")):
            price, unit = _num(ip.findtext(_p("PREZZO"))), (ip.findtext(_p("UNITA_MISURA")) or "").strip()
            if price is None:
                return None
            key = (unit, (ip.findtext(_p("FASCIA_COMPONENTE")) or "").strip())
            start = _num(ip.findtext(_p("CONSUMO_DA"))) or 0.0
            if key not in best or start < best[key][0]:
                best[key] = (start, price)
        fasce = {f for (u, f) in best if u == "03"}
        # A component only given for "01" in a multi-band offer is a flat adder (seen in the data), not F1-only.
        flat = len(names_b) > 1 and fasce == {"01"}
        for (unit, f), (_, price) in best.items():
            if unit == "01":
                year_fee += price
            elif unit == "02":
                year_fee += price * KW
            elif unit == "03":
                for b in names_b:
                    if not f or flat or f in FASCIA[b]:
                        per_band[b] += price
    # Supplier-set dispatching ("99 = other") is part of the offer; the regulated kinds are common to all.
    for dsp in el.iterfind(_p("Dispacciamento")):
        v = _num(dsp.findtext(_p("VALORE_DISP")))
        if (dsp.findtext(_p("TIPO_DISPACCIAMENTO")) or "").strip() == "99" and v:
            per_band = {b: x + v for b, x in per_band.items()}
    idx, mult = None, 1.0
    if kind != "01":
        code = t("RiferimentiPrezzoEnergia/IDX_PREZZO_ENERGIA")
        if code or kind == "02":
            # 05 is ARERA's PE; 01/08/12 (12 = "PUN Index GME", the bulk) and anything else follow the PUN.
            idx = "PE" if code == "05" else "PUN"
            mult = (_num(t("RiferimentiPrezzoEnergia/COEFFICIENTE")) or 1.0) * (1 + lam)
    piva, name = t("IdentificativiOfferta/PIVA_UTENTE"), t("DettaglioOfferta/NOME_OFFERTA")
    site = t("DettaglioOfferta/Contatti/URL_SITO_VENDITORE")
    supplier = names.get(piva) or re.sub(r"^(https?://)?(www\.)?", "", site).split("/")[0] or piva
    url = t("DettaglioOfferta/Contatti/URL_OFFERTA") or site
    return _deal(t("IdentificativiOfferta/COD_OFFERTA"), name, supplier, url, year_fee, per_band, index, idx, mult)


def _p(path: str) -> str:
    """'A/B' -> the namespaced path ElementTree wants."""
    return "/".join(NS + s for s in path.split("/"))


def _dedupe_cap(deals: list[dict[str, Any]], index: dict[str, float] | None) -> list[dict[str, Any]]:
    """Suppliers list the same offer under several codes (channels, payment methods): keep one, then the cheapest."""
    seen: set[tuple] = set()
    out = []
    for d in deals:
        key = (d["supplier"].lower(), d["name"].lower(), d["monthly"], d.get("index"),
               tuple((r["from"], r["to"], r["rate"]) for r in d["periods"][0]["rules"]))
        if key not in seen:
            seen.add(key)
            out.append(d)
    if len(out) > MAX_DEALS:
        out = sorted(out, key=lambda d: _year_cost(d, index))[:MAX_DEALS]
    return out


def parse(xml_bytes: bytes, index: dict[str, float] | None = None, *, names: dict[str, str] | None = None,
          today: date | None = None) -> list[dict[str, Any]]:
    """The free-market XML -> household deals. index: {"PUN": EUR/kWh, "PE": ..., "lambda": ...} (any may be
    missing); names: VAT number -> supplier name (supplier_names()). Streams the file and drops each offer once read."""
    today, names = today or date.today(), names or {}
    lam = (index or {}).get("lambda", LAMBDA)
    deals: list[dict[str, Any]] = []
    tag = NS + "offerta"
    for _, el in ET.iterparse(io.BytesIO(xml_bytes), events=("end",)):
        if el.tag != tag:
            continue
        try:
            if d := _offer(el, names, index, today, lam):
                deals.append(d)
        except Exception:  # noqa: BLE001 - one odd offer must not cost the rest
            _LOGGER.debug("Skipped an Italian offer", exc_info=True)
        el.clear()
    return _dedupe_cap(deals, index)


def _csv(data: bytes, delimiter: str = ",") -> list[dict[str, str]]:
    text = data.decode("utf-8-sig", errors="replace")
    return list(csv.DictReader(io.StringIO(text), delimiter=delimiter))


def supplier_names(placet_csv: bytes) -> dict[str, str]:
    """VAT number -> company name, from the PLACET file (every supplier must offer PLACET, so it covers nearly all)."""
    return {r["p_iva"].strip(): r["denominazione"].strip() for r in _csv(placet_csv) if r.get("p_iva") and r.get("denominazione")}


def parse_placet(placet_csv: bytes, index: dict[str, float] | None = None, *, today: date | None = None) -> list[dict[str, Any]]:
    """The PLACET offers for homes, nationwide. A fixed PLACET offer may list single-rate, F1/F23 and F1/F2/F3 prices
    (the customer picks one), so each becomes its own deal. Variable ones are (PUN + alpha) * (1 + lambda)."""
    today = today or date.today()
    lam = (index or {}).get("lambda", LAMBDA)
    out, seen = [], set()
    for r in _csv(placet_csv):
        code = (r.get("cod_offerta") or "").strip()
        if r.get("tipo_cliente") != "domestico" or (r.get("regione") or "").strip() or not code or code in seen:
            continue
        seen.add(code)
        try:
            if datetime.strptime(r.get("data_fine", "")[:10], "%d/%m/%Y").date() < today:
                continue
        except ValueError:
            pass
        common = (r.get("nome_offerta", ""), r.get("denominazione", ""), r.get("url_offerta") or r.get("url_sito_venditore", ""))
        g = {k: _num(v) for k, v in r.items() if k.startswith(("p_", "alpha"))}
        if r.get("tipo_offerta") == "prezzo variabile":
            if g.get("alpha") is not None:
                d = _deal(code, *common, g.get("p_fix_v") or 0.0, {"F0": g["alpha"] * (1 + lam)}, index, "PUN", 1 + lam)
                out += [d] if d else []
            continue
        options = [("mono", {"F0": g.get("p_vol_mono")}), ("f1f23", {"F1": g.get("p_vol_bf1"), "F23": g.get("p_vol_bf23")}),
                   ("f123", {"F1": g.get("p_vol_f1"), "F2": g.get("p_vol_f2"), "F3": g.get("p_vol_f3")})]
        for suffix, bands in options:
            if all(v is not None for v in bands.values()):
                d = _deal(f"{code}:{suffix}", *common, g.get("p_fix_f") or 0.0, bands, index, None, 1.0)  # type: ignore[arg-type]
                out += [d] if d else []
    return out


def parse_index(prices_csv: bytes, params_csv: bytes | None = None) -> dict[str, float]:
    """The latest monthly PUN and PE (EUR/kWh) from the "Prezzi storici" CSV (semicolon, decimal comma, Windows-1252),
    plus LAMBDA from the parameter file."""
    out: dict[str, float] = {}
    rows = list(csv.reader(io.StringIO(prices_csv.decode("cp1252", errors="replace")), delimiter=";"))
    if rows:
        head = [h.split("(")[0].strip().upper() for h in rows[0]]
        for name in ("PUN", "PE"):
            if name in head:
                i = head.index(name)
                vals = [_num(r[i]) for r in rows[1:] if len(r) > i and r[i].strip()]
                vals = [v for v in vals if v is not None]
                if vals and 0 < vals[-1] < 1:
                    out[name] = vals[-1]
    if params_csv:
        for r in _csv(params_csv):
            if (r.get("nome_parametro") or "").strip() == "lambda" and (v := _num(r.get("valore"))) is not None:
                out["lambda"] = v
    return out


async def _get(s: aiohttp.ClientSession, url: str, timeout: int = 60) -> bytes | None:
    try:
        async with s.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as r:
            return await r.read() if r.status == 200 else None
    except Exception:  # noqa: BLE001
        return None


async def fetch(s: aiohttp.ClientSession) -> list[dict[str, Any]]:
    """Today's (or yesterday's) offers as deals, with the latest PUN folded in when it can be found. Never raises."""
    try:
        today = date.today()
        xml, day = None, today
        for day in (today, today - timedelta(days=1), today - timedelta(days=2)):
            xml = await _get(s, url_for(day), timeout=180)
            if xml and xml.lstrip()[:5] == b"<?xml":
                break
            xml = None
        if not xml:
            _LOGGER.info("Italian offers: no open-data file for the last three days")
            return []
        placet = await _get(s, placet_url(day))
        index: dict[str, float] = {}
        page = await _get(s, OPEN_DATA_PAGE)
        # The monthly index prices sit under a hashed file name; find the CSV link on the open-data page.
        m = re.search(rb'href="(/portaleOfferte/resources/cms/documents/[0-9a-f]+\.csv)"', page or b"")
        prices = await _get(s, SITE + m.group(1).decode()) if m else None
        if prices:
            index = parse_index(prices, await _get(s, params_url(day)))
        if "PUN" not in index:
            _LOGGER.info("Italian offers: no PUN found - index-linked offers carry the spread only")
        names = supplier_names(placet) if placet else {}
        deals = parse(xml, index, names=names, today=today)
        if placet:
            deals = _dedupe_cap(parse_placet(placet, index, today=today) + deals, index)
        return deals
    except Exception:  # noqa: BLE001 - no deals is the fallback
        _LOGGER.info("Italian offers: could not fetch", exc_info=True)
        return []
