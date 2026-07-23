from pathlib import Path

import bigquant
from bigquant import dai


def main() -> None:
    bigquant.init_from_config()

    output_dir = Path("/home/aiuser/work/data_cache")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "cn_stock_bar1d_2024_0102_0105_sample.parquet"

    bars = dai.query(
        """
        SELECT date, instrument, open, high, low, close, volume
        FROM cn_stock_bar1d
        WHERE date >= '2024-01-02' AND date <= '2024-01-05'
        ORDER BY date, instrument
        LIMIT 1000
        """,
        filters={"date": ["2024-01-02", "2024-01-05"]},
    ).df()

    bars.to_parquet(output_path, index=False)
    print(f"rows={len(bars)}")
    print(f"saved={output_path}")


if __name__ == "__main__":
    main()

