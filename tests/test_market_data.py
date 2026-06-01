from pathlib import Path

import pytest

from tdt_rm import (
    FORMAL_DATA_STATUS,
    PROVISIONAL_DATA_STATUS,
    MarketPriceBar,
    derive_price_features,
    ingest_market_data_row,
    ingest_market_data_rows,
    load_market_data_csv,
)


def base_row(**overrides):
    row = {
        "date": "2026-01-05",
        "taiex_close": "94",
        "taiex_ma5": "100",
        "taiex_ma20": "95",
        "taiex_ma60": "90",
        "taiex_ma20_slope": "-1",
        "foreign_spot_net_sell_consecutive_days": "2",
        "usd_twd_3d_change_pct": "0.6",
        "index_down": "true",
        "declining_issues_significantly_gt_advancing": "1",
        "count_main_7_below_ma20": "4",
        "tail_risk": "60",
        "bcd": "70",
    }
    row.update(overrides)
    return row


def test_ingest_market_data_row_maps_aliases_and_builds_scoring_inputs():
    observation = ingest_market_data_row(base_row(), require_eti5=True, require_crash_probability=True)

    assert observation.observed_at.isoformat() == "2026-01-05"
    assert observation.data_status == FORMAL_DATA_STATUS
    assert observation.tcwrs_input.close == 94
    assert observation.tcwrs_input.ma20 == 95
    assert observation.tcwrs_input.index_down is True
    assert observation.eti5_input is not None
    assert observation.eti5_input.close == 94
    assert observation.eti5_input.foreign_spot_net_sell_consecutive_days == 2
    assert observation.tail_risk == 60
    assert observation.bcd == 70
    assert observation.as_dict()["completeness"]["missing_fields"] == []


def test_ingest_market_data_row_accepts_field_map_and_prefixed_eti5_values():
    observation = ingest_market_data_row(
        base_row(
            trade_day="2026/01/06",
            vendor_close="101",
            vendor_ma5="100",
            vendor_ma20="99",
            vendor_ma60="98",
            vendor_slope="0.5",
            eti5_close="97",
            eti5_ma20="100",
        ),
        field_map={
            "observed_at": "trade_day",
            "close": "vendor_close",
            "ma5": "vendor_ma5",
            "ma20": "vendor_ma20",
            "ma60": "vendor_ma60",
            "ma20_slope": "vendor_slope",
        },
        require_eti5=True,
    )

    assert observation.observed_at.isoformat() == "2026-01-06"
    assert observation.tcwrs_input.close == 101
    assert observation.eti5_input is not None
    assert observation.eti5_input.close == 97
    assert observation.eti5_input.ma20 == 100


def test_ingest_market_data_row_reports_optional_missing_as_provisional_trace():
    observation = ingest_market_data_row(base_row(tail_risk="", bcd=""))

    assert observation.data_status == FORMAL_DATA_STATUS
    assert observation.completeness.optional_missing_fields == ("bcd", "tail_risk")
    assert observation.as_dict()["data_status"] == FORMAL_DATA_STATUS


def test_ingest_market_data_row_raises_for_missing_required_tcwrs_field():
    row = base_row()
    del row["taiex_ma60"]

    with pytest.raises(ValueError, match="ma60"):
        ingest_market_data_row(row)


def test_ingest_market_data_rows_sorts_and_converts_to_backtest_observations():
    observations = ingest_market_data_rows(
        [base_row(date="2026-01-07", realized_event="yes"), base_row(date="2026-01-05")]
    )

    assert [observation.observed_at.isoformat() for observation in observations] == [
        "2026-01-05",
        "2026-01-07",
    ]
    assert observations[1].to_backtest_observation().realized_event is True


def test_load_market_data_csv(tmp_path: Path):
    csv_path = tmp_path / "market.csv"
    csv_path.write_text(
        "date,taiex_close,taiex_ma5,taiex_ma20,taiex_ma60,taiex_ma20_slope\n"
        "2026-01-05,94,100,95,90,-1\n",
        encoding="utf-8",
    )

    observations = load_market_data_csv(csv_path)

    assert len(observations) == 1
    assert observations[0].tcwrs_input.close == 94


def test_derive_price_features_builds_required_ma_inputs():
    bars = [MarketPriceBar(observed_at=f"2026-01-{(i % 28) + 1:02d}", close=100 + i, turnover_amount=1_000 + i) for i in range(60)]

    features = derive_price_features(bars)

    assert features["close"] == 159
    assert features["ma5"] == pytest.approx(157)
    assert features["ma20"] == pytest.approx(149.5)
    assert features["ma60"] == pytest.approx(129.5)
    assert features["ma20_slope"] == pytest.approx(1)
    assert features["ma20_turnover"] == pytest.approx(1049.5)


def test_market_data_status_constants_are_spec_labels():
    assert FORMAL_DATA_STATUS == "正式版"
    assert PROVISIONAL_DATA_STATUS == "暫估版"
