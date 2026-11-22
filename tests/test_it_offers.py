"""Italy: Portale Offerte open data -> household deals with ARERA's F1/F2/F3 bands."""
from __future__ import annotations

from datetime import date, datetime

from energy_pilot.it_offers import candidates, parse, parse_index, parse_placet, supplier_names, url_for
from energy_pilot.tariffs import sched_price

TODAY = date(2026, 11, 22)


def offer(code: str, *, cliente: str = "01", tipo: str = "01", fasce: str = "01", comps: str = "", extra: str = "") -> str:
    return f"""<offerta>
  <IdentificativiOfferta><PIVA_UTENTE>01234567890</PIVA_UTENTE><COD_OFFERTA>{code}</COD_OFFERTA></IdentificativiOfferta>
  <DettaglioOfferta><TIPO_MERCATO>01</TIPO_MERCATO><OFFERTA_SINGOLA>SI</OFFERTA_SINGOLA><TIPO_CLIENTE>{cliente}</TIPO_CLIENTE>
    <DOMESTICO_RESIDENTE>03</DOMESTICO_RESIDENTE><TIPO_OFFERTA>{tipo}</TIPO_OFFERTA><NOME_OFFERTA>Offerta {code}</NOME_OFFERTA>
    <Contatti><URL_SITO_VENDITORE>www.esempio.it</URL_SITO_VENDITORE><URL_OFFERTA>https://esempio.it/{code}</URL_OFFERTA></Contatti>
  </DettaglioOfferta>
  {extra}
  <ValiditaOfferta><DATA_INIZIO>01/11/2026_00:00:00</DATA_INIZIO><DATA_FINE>31/12/2026_23:59:59</DATA_FINE></ValiditaOfferta>
  <TipoPrezzo><TIPOLOGIA_FASCE>{fasce}</TIPOLOGIA_FASCE></TipoPrezzo>
  <Dispacciamento><TIPO_DISPACCIAMENTO>14</TIPO_DISPACCIAMENTO><NOME>CdispD</NOME></Dispacciamento>
  <ComponenteImpresa><NOME>Quota fissa</NOME><TIPOLOGIA>01</TIPOLOGIA><MACROAREA>01</MACROAREA>
    <IntervalloPrezzi><PREZZO>120</PREZZO><UNITA_MISURA>01</UNITA_MISURA></IntervalloPrezzi></ComponenteImpresa>
  {comps}
</offerta>"""


def energy(*bands: tuple[str, float]) -> str:
    rows = "".join(f"<IntervalloPrezzi><FASCIA_COMPONENTE>{f}</FASCIA_COMPONENTE><PREZZO>{p}</PREZZO>"
                   f"<UNITA_MISURA>03</UNITA_MISURA></IntervalloPrezzi>" for f, p in bands)
    return f"<ComponenteImpresa><NOME>Prezzo</NOME><TIPOLOGIA>01</TIPOLOGIA><MACROAREA>04</MACROAREA>{rows}</ComponenteImpresa>"


XML = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<ListaOfferteMercatoLibero xmlns="http://www.acquirenteunico.it/schemas/SII_AU/OffertaRetail/01">
{offer("MONO", comps=energy(("01", 0.10)))}
{offer("TRI", fasce="03", comps=energy(("01", 0.15), ("02", 0.12), ("03", 0.09)))}
{offer("PUN", tipo="02", fasce="01", comps=energy(("01", 0.02)),
       extra="<RiferimentiPrezzoEnergia><IDX_PREZZO_ENERGIA>12</IDX_PREZZO_ENERGIA></RiferimentiPrezzoEnergia>")}
{offer("BIZ", cliente="02", comps=energy(("01", 0.05)))}
{offer("ZONA", comps=energy(("01", 0.05)), extra="<ZoneOfferta><REGIONE>04</REGIONE></ZoneOfferta>")}
{offer("BROKEN", comps=energy(("01", 7.5)))}
</ListaOfferteMercatoLibero>""".encode()

PLACET = (b"denominazione,codice_fiscale,p_iva,url_sito_venditore,telefono,nome_offerta,cod_offerta,url_offerta,"
          b"modalita_attivazione,modalita_pagamento,data_inizio,data_fine,tipo_cliente,tipo_offerta,p_fix_f,p_fix_v,"
          b"p_vol_f1,p_vol_f2,p_vol_f3,p_vol_bf1,p_vol_bf23,p_vol_mono,alpha,regione,provincia,comune\n"
          b"Esempio Energia SpA,x,01234567890,https://esempio.it,,PLACET Fissa,PF1,,,,01/11/2026,31/12/2026,domestico,"
          b"prezzo fisso,96,,,,,,,0.2,,,,\n"
          b"Esempio Energia SpA,x,01234567890,https://esempio.it,,PLACET Variabile,PV1,,,,01/11/2026,31/12/2026,domestico,"
          b"prezzo variabile,,60,,,,,,,0.01,,,\n")


def rate(deal: dict, when: datetime) -> float:
    return sched_price(deal, when)


def by_id(deals: list[dict]) -> dict[str, dict]:
    return {d["id"]: d for d in deals}


WED_9, WED_730, WED_20, SAT_10, SAT_2330, SUN_12 = (datetime(2026, 11, 18, 9), datetime(2026, 11, 18, 7, 30),
                                                     datetime(2026, 11, 18, 20), datetime(2026, 11, 21, 10),
                                                     datetime(2026, 11, 21, 23, 30), datetime(2026, 11, 22, 12))


def test_urls():
    assert url_for(date(2026, 11, 22)).endswith("/offerteML/2026_11/PO_Offerte_E_MLIBERO_20261122.xml")
    assert candidates(date(2026, 12, 1))[1].endswith("/2026_11/PO_Offerte_E_MLIBERO_20261130.xml")


def test_schema_filters_and_vat():
    deals = by_id(parse(XML, names=supplier_names(PLACET), today=TODAY))
    assert set(deals) == {"it:MONO", "it:TRI", "it:PUN"}  # no business, regional or broken offers
    d = deals["it:MONO"]
    assert d["supplier"] == "Esempio Energia SpA" and d["url"] == "https://esempio.it/MONO"
    assert d["fit"] is None and d["partial"] is True
    assert d["monthly"] == round(120 * 1.10 / 12, 2)  # EUR/year excl. VAT -> a month incl. VAT
    assert d["periods"][0]["from"] == "01-01" and d["periods"][0]["to"] == "12-31"
    assert rate(d, WED_9) == rate(d, SUN_12) == round(0.10 * 1.10, 5)


def test_bands():
    tri = by_id(parse(XML, today=TODAY))["it:TRI"]
    f1, f2, f3 = (round(x * 1.10, 5) for x in (0.15, 0.12, 0.09))
    assert rate(tri, WED_9) == f1          # weekday daytime
    assert rate(tri, WED_730) == f2        # weekday 07-08
    assert rate(tri, WED_20) == f2         # weekday evening
    assert rate(tri, SAT_10) == f2         # Saturday daytime
    assert rate(tri, SAT_2330) == f3       # night
    assert rate(tri, SUN_12) == f3         # all Sunday


def test_index_linked():
    with_pun = by_id(parse(XML, {"PUN": 0.12, "lambda": 0.10}, today=TODAY))["it:PUN"]
    assert rate(with_pun, WED_9) == round((0.12 * 1.10 + 0.02) * 1.10, 5) and "index" not in with_pun
    bare = by_id(parse(XML, today=TODAY))["it:PUN"]
    assert rate(bare, WED_9) == round(0.02 * 1.10, 5)
    assert bare["index"] == "PUN" and bare["index_mult"] == round(1.10 * 1.10, 4)


def test_placet():
    deals = by_id(parse_placet(PLACET, {"PUN": 0.12}, today=TODAY))
    fixed, var = deals["it:PF1:mono"], deals["it:PV1"]
    assert fixed["monthly"] == round(96 * 1.10 / 12, 2) and rate(fixed, SUN_12) == round(0.2 * 1.10, 5)
    assert rate(var, WED_9) == round((0.12 + 0.01) * 1.10 * 1.10, 5) and var["monthly"] == round(60 * 1.10 / 12, 2)


def test_index_file():
    prices = "AnnoMese;PUN (€/kWh);PSV (€/Smc);PE (€/kWh)\n202608;0,1;0,5;0,15\n202609;0,2;0,6;\n".encode("cp1252")  # the real file is Windows-1252
    params = b"nome_parametro,valore,descrizione\nlambda,0.100000,perdite\n"
    assert parse_index(prices, params) == {"PUN": 0.2, "PE": 0.15, "lambda": 0.1}


def test_garbage_gives_nothing():
    assert parse(b"<?xml version='1.0'?><x/>") == []
