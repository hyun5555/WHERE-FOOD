"""Import reviewed evidence without converting missing data into absence claims."""
import argparse
import csv
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
from pydantic import ValidationError
import db
from recommendation import MenuRecord


def import_csv(csv_path, database_path):
    menus = []
    with Path(csv_path).open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        required = {"place_id", "restaurant_name", "menu_name", "price_krw", "menu_evidence"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("필수 CSV 헤더가 없습니다.")
        for line, row in enumerate(reader, 2):
            try:
                record = {key: value for key, value in row.items() if value}
                record["price_krw"] = int(row["price_krw"]) if row["price_krw"] else None
                for key in ("menu_evidence", "tags", "absent_ingredients", "allergy_checks", "atmosphere"):
                    if record.get(key):
                        record[key] = json.loads(record[key])
                menus.append(MenuRecord.model_validate(record))
            except (ValueError, TypeError, ValidationError) as exc:
                raise ValueError(f"CSV {line}행의 값 또는 근거 형식을 확인해주세요.") from exc
    if not menus:
        raise ValueError("CSV에 실제 메뉴 행이 없습니다. 기존 데이터는 변경하지 않았습니다.")
    keys = [(m.place_id, m.menu_name) for m in menus]
    if len(keys) != len(set(keys)):
        raise ValueError("동일한 장소·메뉴가 CSV에 중복되었습니다.")
    db.init_db(database_path)
    db.upsert_menus(database_path, menus)
    return len(menus)


if __name__ == "__main__":
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", nargs="?", default=str(ROOT / "data/menu_items.csv"))
    parser.add_argument("--database", default=os.environ.get("DATABASE_PATH", str(ROOT / "instance/where_food.db")))
    args = parser.parse_args()
    try:
        print(f"메뉴 {import_csv(args.csv, args.database)}개 반영 완료")
    except ValueError as exc:
        parser.exit(1, str(exc) + "\n")
