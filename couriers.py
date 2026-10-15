"""Разбор файла «курьеры без договора»: делит по ЛП и сортирует.
Отдельный модуль, чтобы не трогать основную логику бота (+1 / ✅)."""
import csv
import io
import json
import os
import zipfile
from collections import Counter, OrderedDict

LP_COL = "ЛП"
REASON_COL = "Причина дожима"
DAYS_COL = "Дней без договора"
SHIFTS_COL = "Смен за 14 дней"


def _norm(name: str) -> str:
    return " ".join(name.upper().split())


def load_lp_groups() -> dict:
    """LP_GROUPS='{"NOVA-DRIVE": -1001111, "CITY DRIVE": -1002222}' -> {норм. имя: chat_id}"""
    raw = os.getenv("LP_GROUPS", "").strip()
    if not raw:
        return {}
    return {_norm(k): int(v) for k, v in json.loads(raw).items()}


def _decode(data: bytes) -> str:
    return data.decode("utf-8-sig")


def read_rows(filename: str, data: bytes):
    """Принимает .csv или .zip с csv. Возвращает (заголовок, строки).
    В zip берётся тот csv, где есть колонка «ЛП» (остальные, например query_2.csv, пропускаются)."""
    if filename.lower().endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            candidates = [(n, z.read(n)) for n in z.namelist() if n.lower().endswith(".csv")]
    else:
        candidates = [(filename, data)]

    for _, raw in candidates:
        reader = csv.reader(io.StringIO(_decode(raw), newline=""))
        header = next(reader, None)
        if header and LP_COL in header:
            return header, [r for r in reader if r]
    raise ValueError(f"В файле нет колонки «{LP_COL}»")


def _num(v, default=0):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def split_by_lp(header, rows):
    """Возвращает {ЛП: (csv-bytes, кол-во, Counter причин)}; в каждой группе строки отсортированы:
    причина дожима (1 → 2 → 3), затем больше дней без договора, затем больше смен за 14 дней."""
    i_lp, i_reason = header.index(LP_COL), header.index(REASON_COL)
    i_days, i_shifts = header.index(DAYS_COL), header.index(SHIFTS_COL)

    groups = OrderedDict()
    for r in rows:
        groups.setdefault(r[i_lp].strip(), []).append(r)

    result = OrderedDict()
    for lp in sorted(groups, key=lambda x: (-len(groups[x]), x)):
        part = sorted(
            groups[lp],
            key=lambda r: (r[i_reason], -_num(r[i_days]), -_num(r[i_shifts])),
        )
        buf = io.StringIO(newline="")
        w = csv.writer(buf)
        w.writerow(header)
        w.writerows(part)
        # utf-8-sig, чтобы Excel сразу правильно показал кириллицу
        result[lp] = (
            buf.getvalue().encode("utf-8-sig"),
            len(part),
            Counter(r[i_reason] for r in part),
        )
    return result


def lookup_group(lp: str, mapping: dict):
    return mapping.get(_norm(lp))
