"""Unit tests for quant_strategy.cli — covers the --file (txt/markdown) input path for `define`."""
import pytest

from quant_strategy import cli


def test_read_strategy_text_file_accepts_txt(tmp_path):
    path = tmp_path / "strategy.txt"
    path.write_text("MA5上穿MA20买入，MA5下穿MA20卖出", encoding="utf-8")

    assert cli._read_strategy_text_file(str(path)) == "MA5上穿MA20买入，MA5下穿MA20卖出"


def test_read_strategy_text_file_accepts_markdown_and_strips_whitespace(tmp_path):
    path = tmp_path / "strategy.md"
    path.write_text("\n# 策略\nMA5上穿MA20买入\n\n", encoding="utf-8")

    assert cli._read_strategy_text_file(str(path)) == "# 策略\nMA5上穿MA20买入"


def test_read_strategy_text_file_rejects_unsupported_extension(tmp_path):
    path = tmp_path / "strategy.json"
    path.write_text("MA5上穿MA20买入", encoding="utf-8")

    with pytest.raises(SystemExit):
        cli._read_strategy_text_file(str(path))


def test_read_strategy_text_file_rejects_missing_file(tmp_path):
    path = tmp_path / "does_not_exist.md"

    with pytest.raises(SystemExit):
        cli._read_strategy_text_file(str(path))


def test_read_strategy_text_file_rejects_empty_file(tmp_path):
    path = tmp_path / "empty.txt"
    path.write_text("   \n", encoding="utf-8")

    with pytest.raises(SystemExit):
        cli._read_strategy_text_file(str(path))


def test_define_parser_requires_exactly_one_of_text_or_file():
    parser = cli.build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["define", "--name", "x"])

    with pytest.raises(SystemExit):
        parser.parse_args(["define", "--text", "a", "--file", "b.md", "--name", "x"])

    args = parser.parse_args(["define", "--file", "strategy.md", "--name", "x"])
    assert args.file == "strategy.md"
    assert args.text is None


def test_screen_parser_requires_strategy_and_defaults_rating_to_buy():
    parser = cli.build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["screen"])

    args = parser.parse_args(["screen", "--strategy", "bot_vol_rally"])
    assert args.strategy == "bot_vol_rally"
    assert args.rating == "BUY"
    assert args.date is None
    assert args.codes is None
    assert args.limit is None
    assert args.lookback_days is None


def test_screen_parser_rejects_invalid_rating_choice():
    parser = cli.build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["screen", "--strategy", "bot_vol_rally", "--rating", "HOLD"])


def test_screen_parser_accepts_codes_limit_and_lookback():
    parser = cli.build_parser()

    args = parser.parse_args([
        "screen", "--strategy", "bot_vol_rally",
        "--codes", "600519.SH,000001.SZ", "--limit", "300",
        "--lookback-days", "200", "--rating", "SELL",
    ])
    assert args.codes == "600519.SH,000001.SZ"
    assert args.limit == 300
    assert args.lookback_days == 200
    assert args.rating == "SELL"
