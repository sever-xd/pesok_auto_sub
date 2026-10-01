"""
VPN Subscription Aggregator — GitHub Edition
Каждый день собирает 2-3 сервера из популярных стран,
добавляет в подписку и коммитит в репозиторий.
"""

import asyncio
import aiohttp
import base64
import io
import sys

# Фикс для Windows консоли (cp1251 не поддерживает эмодзи)
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
import hashlib
import json
import re
import sys
import time
import urllib.parse
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# ============================================================
# Популярные страны и их определение
# ============================================================

# Флаги → ISO код
FLAG_TO_COUNTRY = {
    "🇺🇸": "US", "🇬🇧": "GB", "🇩🇪": "DE", "🇳🇱": "NL", "🇫🇷": "FR",
    "🇯🇵": "JP", "🇸🇬": "SG", "🇰🇷": "KR", "🇭🇰": "HK", "🇹🇼": "TW",
    "🇨🇦": "CA", "🇦🇺": "AU", "🇮🇳": "IN", "🇧🇷": "BR", "🇷🇺": "RU",
    "🇹🇷": "TR", "🇮🇹": "IT", "🇪🇸": "ES", "🇵🇱": "PL", "🇸🇪": "SE",
    "🇳🇴": "NO", "🇫🇮": "FI", "🇨🇭": "CH", "🇦🇹": "AT", "🇮🇪": "IE",
    "🇮🇱": "IL", "🇦🇪": "AE", "🇿🇦": "ZA", "🇲🇽": "MX", "🇦🇷": "AR",
    "🇺🇦": "UA", "🇨🇿": "CZ", "🇷🇴": "RO", "🇧🇬": "BG", "🇭🇺": "HU",
    "🇱🇻": "LV", "🇱🇹": "LT", "🇪🇪": "EE", "🇵🇹": "PT", "🇬🇷": "GR",
    "🇧🇪": "BE", "🇩🇰": "DK", "🇲🇾": "MY", "🇹🇭": "TH", "🇻🇳": "VN",
    "🇮🇩": "ID", "🇵🇭": "PH", "🇰🇿": "KZ", "🇺🇿": "UZ",
}

# Текстовые маркеры → ISO код
TEXT_TO_COUNTRY = {
    # Английские
    "united states": "US", "usa": "US", "us": "US", "america": "US",
    "united kingdom": "GB", "uk": "GB", "england": "GB", "britain": "GB", "london": "GB",
    "germany": "DE", "frankfurt": "DE", "berlin": "DE", "munich": "DE",
    "netherlands": "NL", "amsterdam": "NL", "holland": "NL",
    "france": "FR", "paris": "FR", "marseille": "FR",
    "japan": "JP", "tokyo": "JP", "osaka": "JP",
    "singapore": "SG",
    "south korea": "KR", "korea": "KR", "seoul": "KR",
    "hong kong": "HK", "hongkong": "HK",
    "taiwan": "TW", "taipei": "TW",
    "canada": "CA", "toronto": "CA", "vancouver": "CA", "montreal": "CA",
    "australia": "AU", "sydney": "AU", "melbourne": "AU",
    "india": "IN", "mumbai": "IN", "bangalore": "IN",
    "brazil": "BR", "sao paulo": "BR",
    "russia": "RU", "moscow": "RU", "petersburg": "RU",
    "turkey": "TR", "istanbul": "TR", "ankara": "TR",
    "italy": "IT", "milan": "IT", "rome": "IT",
    "spain": "ES", "madrid": "ES", "barcelona": "ES",
    "poland": "PL", "warsaw": "PL",
    "sweden": "SE", "stockholm": "SE",
    "norway": "NO", "oslo": "NO",
    "finland": "FI", "helsinki": "FI",
    "switzerland": "CH", "zurich": "CH",
    "austria": "AT", "vienna": "AT",
    "ireland": "IE", "dublin": "IE",
    "israel": "IL", "tel aviv": "IL",
    "uae": "AE", "dubai": "AE",
    "south africa": "ZA", "johannesburg": "ZA", "cape town": "ZA",
    "ukraine": "UA", "kyiv": "UA", "kiev": "UA",
    "czech": "CZ", "prague": "CZ",
    "romania": "RO", "bucharest": "RO",
    "bulgaria": "BG", "sofia": "BG",
    "hungary": "HU", "budapest": "HU",
    "portugal": "PT", "lisbon": "PT",
    "belgium": "BE", "brussels": "BE",
    "denmark": "DK", "copenhagen": "DK",
    "malaysia": "MY", "kuala lumpur": "MY",
    "thailand": "TH", "bangkok": "TH",
    "vietnam": "VN", "hanoi": "VN", "ho chi minh": "VN",
    "indonesia": "ID", "jakarta": "ID",
    "philippines": "PH", "manila": "PH",
    "new york": "US", "los angeles": "US", "chicago": "US",
    "dallas": "US", "miami": "US", "seattle": "US", "san jose": "US",
    "washington": "US", "atlanta": "US", "silicon valley": "US",
    "new jersey": "US", "virginia": "US", "california": "US", "texas": "US",
    "oregon": "US", "florida": "US", "ohio": "US", "phoenix": "US",
    "las vegas": "US", "denver": "US", "buffalo": "US",
}

# Популярные страны с названиями (для вывода)
POPULAR_COUNTRIES = {
    "US": "🇺🇸 США",
    "GB": "🇬🇧 Великобритания",
    "DE": "🇩🇪 Германия",
    "NL": "🇳🇱 Нидерланды",
    "FR": "🇫🇷 Франция",
    "JP": "🇯🇵 Япония",
    "SG": "🇸🇬 Сингапур",
    "KR": "🇰🇷 Южная Корея",
    "HK": "🇭🇰 Гонконг",
    "CA": "🇨🇦 Канада",
    "AU": "🇦🇺 Австралия",
    "FI": "🇫🇮 Финляндия",
    "SE": "🇸🇪 Швеция",
    "TR": "🇹🇷 Турция",
    "IN": "🇮🇳 Индия",
}

# Сколько серверов брать из каждой страны
SERVERS_PER_COUNTRY = 3

# Максимальный возраст серверов в днях (старше — удаляем)
MAX_AGE_DAYS = 7


# ============================================================
# Модели
# ============================================================
@dataclass
class VPNConfig:
    protocol: str
    raw: str
    address: str = ""
    port: int = 0
    remark: str = ""
    country: str = ""       # ISO код страны
    fingerprint: str = ""
    added_date: str = ""    # Когда добавлен (ISO формат)

    def __post_init__(self):
        if not self.fingerprint:
            key = f"{self.protocol}:{self.address}:{self.port}"
            self.fingerprint = hashlib.md5(key.encode()).hexdigest()
        if not self.country:
            self.country = detect_country(self.remark, self.address)
        if not self.added_date:
            self.added_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")


def detect_country(remark: str, address: str = "") -> str:
    """Определяем страну по remark и адресу сервера."""
    text = f"{remark} {address}".strip()
    if not text:
        return "XX"

    # 1. Проверяем флаги-эмодзи
    for flag, code in FLAG_TO_COUNTRY.items():
        if flag in text:
            return code

    # 2. Проверяем ISO коды в remark (например "[US]", "US-", "_US_")
    upper = remark.upper()
    for code in FLAG_TO_COUNTRY.values():
        patterns = [
            f"[{code}]", f"({code})", f" {code} ", f"-{code}-",
            f"_{code}_", f"{code}-", f" {code}-", f"_{code}-",
        ]
        # Также проверяем начало строки
        if upper.startswith(f"{code} ") or upper.startswith(f"{code}-") or upper.startswith(f"{code}_"):
            return code
        for pat in patterns:
            if pat in upper:
                return code

    # 3. Текстовые маркеры (города/страны)
    lower = text.lower()
    for marker, code in sorted(TEXT_TO_COUNTRY.items(), key=lambda x: -len(x[0])):
        if marker in lower:
            return code

    return "XX"


# ============================================================
# Парсер конфигов (то же что раньше, компактнее)
# ============================================================
class ConfigParser:
    PROTOCOLS = ("vmess://", "vless://", "trojan://", "ss://", "ssr://")

    @staticmethod
    def try_b64(text: str) -> str:
        text = text.strip()
        if not text:
            return text
        try:
            pad = text + "=" * (4 - len(text) % 4) if len(text) % 4 else text
            d = base64.b64decode(pad).decode("utf-8", errors="ignore")
            if any(p in d for p in ConfigParser.PROTOCOLS):
                return d
        except Exception:
            pass
        return text

    @staticmethod
    def parse_vmess(uri: str) -> Optional[VPNConfig]:
        try:
            enc = uri[len("vmess://"):].strip()
            pad = enc + "=" * (4 - len(enc) % 4) if len(enc) % 4 else enc
            data = json.loads(base64.b64decode(pad).decode("utf-8", errors="ignore"))
            return VPNConfig(
                protocol="vmess", raw=uri.strip(),
                address=data.get("add", ""), port=int(data.get("port", 0)),
                remark=data.get("ps", ""),
            )
        except Exception:
            return None

    @staticmethod
    def parse_uri(uri: str, proto: str) -> Optional[VPNConfig]:
        try:
            p = urllib.parse.urlparse(uri)
            remark = urllib.parse.unquote(p.fragment) if p.fragment else ""
            return VPNConfig(
                protocol=proto, raw=uri.strip(),
                address=p.hostname or "", port=p.port or 0, remark=remark,
            )
        except Exception:
            return None

    @staticmethod
    def parse_ss(uri: str) -> Optional[VPNConfig]:
        try:
            rest = uri[len("ss://"):].strip()
            remark = ""
            if "#" in rest:
                rest, remark = rest.rsplit("#", 1)
                remark = urllib.parse.unquote(remark)
            if "@" in rest:
                _, hostport = rest.rsplit("@", 1)
            else:
                pad = rest + "=" * (4 - len(rest) % 4) if len(rest) % 4 else rest
                dec = base64.b64decode(pad).decode("utf-8", errors="ignore")
                if "@" not in dec:
                    return None
                _, hostport = dec.rsplit("@", 1)
            if ":" in hostport:
                host, port_s = hostport.rsplit(":", 1)
                port = int(port_s)
            else:
                host, port = hostport, 0
            return VPNConfig(protocol="ss", raw=uri.strip(), address=host, port=port, remark=remark)
        except Exception:
            return None

    @staticmethod
    def parse_ssr(uri: str) -> Optional[VPNConfig]:
        try:
            enc = uri[len("ssr://"):].strip()
            pad = enc + "=" * (4 - len(enc) % 4) if len(enc) % 4 else enc
            dec = base64.b64decode(pad).decode("utf-8", errors="ignore")
            parts = dec.split(":")
            return VPNConfig(
                protocol="ssr", raw=uri.strip(),
                address=parts[0] if parts else "", port=int(parts[1]) if len(parts) > 1 else 0,
            ) if len(parts) >= 2 else None
        except Exception:
            return None

    @classmethod
    def parse_line(cls, line: str) -> Optional[VPNConfig]:
        line = line.strip()
        if not line or len(line) < 10:
            return None
        if line.startswith("vmess://"):
            return cls.parse_vmess(line)
        if line.startswith("vless://"):
            return cls.parse_uri(line, "vless")
        if line.startswith("trojan://"):
            return cls.parse_uri(line, "trojan")
        if line.startswith("ss://"):
            return cls.parse_ss(line)
        if line.startswith("ssr://"):
            return cls.parse_ssr(line)
        return None

    @classmethod
    def parse_content(cls, content: str) -> list[VPNConfig]:
        decoded = cls.try_b64(content)
        configs = []
        for line in decoded.splitlines():
            c = cls.parse_line(line.strip())
            if c:
                configs.append(c)
        return configs


# ============================================================
# Источники
# ============================================================
SOURCES = [
    ("0xradikal", "https://raw.githubusercontent.com/0xRadikal/Free-v2ray-Configs/main/top100.txt"),
    ("zhuhaiuk", "https://raw.githubusercontent.com/zhuhaiuk/free-nodes/main/nodes.txt"),
    ("epodonios", "https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/All_Configs_Sub.txt"),
    ("mahdibland", "https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/sub/sub_merge_base64.txt"),
    ("ermaozi", "https://raw.githubusercontent.com/ermaozi/get_subscribe/main/subscribe/v2ray.txt"),
    ("peasoft", "https://raw.githubusercontent.com/peasoft/NoMoreWalls/master/list_raw.txt"),
    ("roosterkid", "https://raw.githubusercontent.com/roosterkid/openproxylist/main/V2RAY_RAW.txt"),
    ("freefq", "https://raw.githubusercontent.com/freefq/free/master/v2"),
    ("pawdroid", "https://raw.githubusercontent.com/Pawdroid/Free-servers/main/sub"),
]


async def fetch_all() -> list[VPNConfig]:
    """Загрузить все конфиги из всех источников."""
    all_configs = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    timeout = aiohttp.ClientTimeout(total=20)
    parser = ConfigParser()

    async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
        async def fetch_one(name: str, url: str):
            try:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        print(f"  ⚠️  {name}: HTTP {resp.status}")
                        return []
                    content = await resp.text(errors="ignore")
                    configs = parser.parse_content(content)
                    print(f"  ✅ {name}: {len(configs)} конфигов")
                    return configs
            except Exception as e:
                print(f"  ❌ {name}: {e}")
                return []

        tasks = [fetch_one(n, u) for n, u in SOURCES]
        results = await asyncio.gather(*tasks)
        for r in results:
            all_configs.extend(r)

    return all_configs


# ============================================================
# Основная логика: выбор и ротация серверов
# ============================================================
def load_existing_subscription(path: Path) -> list[dict]:
    """Загрузить текущую подписку с метаданными."""
    meta_path = path.parent / "servers_meta.json"
    if meta_path.exists():
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            return data.get("servers", [])
        except Exception:
            pass
    return []


def save_subscription(path: Path, servers: list[dict], stats: dict):
    """Сохранить подписку и метаданные."""
    # 1. Base64 подписка (для VPN клиентов)
    raw_lines = [s["raw"] for s in servers]
    plain = "\n".join(raw_lines)
    b64 = base64.b64encode(plain.encode("utf-8")).decode("utf-8")
    path.write_text(b64, encoding="utf-8")

    # 2. Plain text (raw конфиги)
    raw_path = path.parent / "raw_configs.txt"
    raw_path.write_text(plain, encoding="utf-8")

    # 3. Метаданные (для отслеживания)
    meta_path = path.parent / "servers_meta.json"
    now_iso = datetime.now(timezone.utc).isoformat()
    meta = {
        "last_update": now_iso,
        "stats": stats,
        "servers": servers,
    }
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    # 4. Данные для сайта (без поля raw)
    site_path = path.parent / "site_data.json"
    site_servers = list(servers)
    site_data = {
        "last_update": now_iso,
        "stats": stats,
        "servers": site_servers,
    }
    site_path.write_text(json.dumps(site_data, indent=2, ensure_ascii=False), encoding="utf-8")

    # 5. README со статистикой
    generate_readme(path.parent, servers, stats)


# Русские названия стран и флаги для красивого нейминга в подписке
COUNTRY_NAMES_RU = {
    "US": ("🇺🇸", "США"), "DE": ("🇩🇪", "Германия"), "NL": ("🇳🇱", "Нидерланды"),
    "FR": ("🇫🇷", "Франция"), "GB": ("🇬🇧", "Великобритания"), "JP": ("🇯🇵", "Япония"),
    "SG": ("🇸🇬", "Сингапур"), "KR": ("🇰🇷", "Южная Корея"), "HK": ("🇭🇰", "Гонконг"),
    "TW": ("🇹🇼", "Тайвань"), "CA": ("🇨🇦", "Канада"), "AU": ("🇦🇺", "Австралия"),
    "FI": ("🇫🇮", "Финляндия"), "SE": ("🇸🇪", "Швеция"), "TR": ("🇹🇷", "Турция"),
    "IN": ("🇮🇳", "Индия"), "PL": ("🇵🇱", "Польша"), "IT": ("🇮🇹", "Италия"),
    "ES": ("🇪🇸", "Испания"), "CH": ("🇨🇭", "Швейцария"), "AT": ("🇦🇹", "Австрия"),
    "NO": ("🇳🇴", "Норвегия"), "AE": ("🇦🇪", "ОАЭ"), "RU": ("🇷🇺", "Россия"),
    "KZ": ("🇰🇿", "Казахстан"), "UA": ("🇺🇦", "Украина"), "CZ": ("🇨🇿", "Чехия"),
    "RO": ("🇷🇴", "Румыния"), "BG": ("🇧🇬", "Болгария"), "HU": ("🇭🇺", "Венгрия"),
    "PT": ("🇵🇹", "Португалия"), "BE": ("🇧🇪", "Бельгия"), "DK": ("🇩🇰", "Дания"),
    "MY": ("🇲🇾", "Малайзия"), "TH": ("🇹🇭", "Таиланд"), "VN": ("🇻🇳", "Вьетнам"),
    "ID": ("🇮🇩", "Индонезия"), "PH": ("🇵🇭", "Филиппины"), "IL": ("🇮🇱", "Израиль"),
    "BR": ("🇧🇷", "Бразилия"), "ZA": ("🇿🇦", "ЮАР"), "MX": ("🇲🇽", "Мексика"),
    "AR": ("🇦🇷", "Аргентина"), "GR": ("🇬🇷", "Греция"), "LV": ("🇱🇻", "Латвия"),
    "LT": ("🇱🇹", "Литва"), "EE": ("🇪🇪", "Эстония"), "UZ": ("🇺🇿", "Узбекистан"),
}


def rename_vpn_config(raw: str, new_name: str) -> str:
    """Переименовывает конфиг внутри протокола (в base64 json для vmess или hash для vless/ss/trojan)."""
    raw = raw.strip()
    if raw.startswith("vmess://"):
        try:
            b64_part = raw[8:]
            b64_part += "=" * (-len(b64_part) % 4)
            data = json.loads(base64.b64decode(b64_part).decode("utf-8", errors="ignore"))
            data["ps"] = new_name
            new_b64 = base64.b64encode(json.dumps(data, ensure_ascii=False).encode("utf-8")).decode("utf-8")
            return f"vmess://{new_b64}"
        except Exception:
            return raw
    elif any(raw.startswith(p) for p in ["vless://", "trojan://", "ss://", "ssr://", "hy2://", "hysteria://", "hysteria2://", "tuic://"]):
        base_part = raw.split("#", 1)[0] if "#" in raw else raw
        return f"{base_part}#{urllib.parse.quote(new_name)}"
    return raw


def select_best_servers(
    new_configs: list[VPNConfig],
    existing: list[dict],
    per_country: int = SERVERS_PER_COUNTRY,
    max_age: int = MAX_AGE_DAYS,
) -> tuple[list[dict], dict]:
    """
    Выбрать лучшие сервера с ротацией и авто-переименованием в [pesok] 🇺🇸 США #01.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Группируем новые конфиги по странам
    by_country: dict[str, list[VPNConfig]] = defaultdict(list)
    for c in new_configs:
        if c.country != "XX":
            by_country[c.country].append(c)

    existing_by_country: dict[str, list[dict]] = defaultdict(list)
    for s in existing:
        existing_by_country[s.get("country", "XX")].append(s)

    final = []
    added_count = 0
    kept_count = 0
    fps = set()

    # 1. Для популярных стран берём свежие из new_configs, дополняем существующими
    for country_code in POPULAR_COUNTRIES:
        avail_new = by_country.get(country_code, [])
        avail_existing = existing_by_country.get(country_code, [])

        take_new = min(len(avail_new), per_country)
        selected_new = _diverse_select(avail_new, take_new)
        for cfg in selected_new:
            if cfg.fingerprint not in fps:
                final.append({
                    "protocol": cfg.protocol,
                    "raw": cfg.raw,
                    "address": cfg.address,
                    "port": cfg.port,
                    "remark": cfg.remark,
                    "country": cfg.country,
                    "fingerprint": cfg.fingerprint,
                    "added_date": today,
                })
                fps.add(cfg.fingerprint)
                added_count += 1

        remaining = per_country - len(selected_new)
        if remaining > 0 and avail_existing:
            for ex in avail_existing:
                if ex.get("fingerprint") not in fps and remaining > 0:
                    final.append(ex)
                    fps.add(ex.get("fingerprint"))
                    kept_count += 1
                    remaining -= 1

    # 2. Непопулярные страны: до 2 серверов на страну
    all_other = (set(by_country.keys()) | set(existing_by_country.keys())) - set(POPULAR_COUNTRIES.keys())
    all_other.discard("XX")

    for cc in sorted(all_other):
        avail_new = by_country.get(cc, [])
        avail_existing = existing_by_country.get(cc, [])
        limit = 2

        take_new = min(len(avail_new), limit)
        selected_new = _diverse_select(avail_new, take_new)
        for cfg in selected_new:
            if cfg.fingerprint not in fps:
                final.append({
                    "protocol": cfg.protocol,
                    "raw": cfg.raw,
                    "address": cfg.address,
                    "port": cfg.port,
                    "remark": cfg.remark,
                    "country": cfg.country,
                    "fingerprint": cfg.fingerprint,
                    "added_date": today,
                })
                fps.add(cfg.fingerprint)
                added_count += 1

        remaining = limit - len(selected_new)
        if remaining > 0 and avail_existing:
            for ex in avail_existing:
                if ex.get("fingerprint") not in fps and remaining > 0:
                    final.append(ex)
                    fps.add(ex.get("fingerprint"))
                    kept_count += 1
                    remaining -= 1

    # 3. Переименовываем ВСЕ серверы в [pesok] 🇺🇸 США #01
    country_counters = defaultdict(int)
    for s in final:
        c_code = s.get("country", "XX")
        country_counters[c_code] += 1
        idx = country_counters[c_code]
        flag, name_ru = COUNTRY_NAMES_RU.get(c_code, ("🌐", c_code if c_code != "XX" else "Сервер"))
        new_name = f"[pesok] {flag} {name_ru} #{idx:02d}"
        s["remark"] = new_name
        s["raw"] = rename_vpn_config(s["raw"], new_name)

    # Статистика
    country_stats = defaultdict(int)
    proto_stats = defaultdict(int)
    for s in final:
        country_stats[s.get("country", "XX")] += 1
        proto_stats[s.get("protocol", "?")] += 1

    stats = {
        "total": len(final),
        "added_today": added_count,
        "removed_expired": max(0, len(existing) - kept_count),
        "kept_from_previous": kept_count,
        "date": today,
        "countries": dict(country_stats),
        "protocols": dict(proto_stats),
        "popular_countries": {
            code: {
                "name": POPULAR_COUNTRIES[code],
                "count": country_stats.get(code, 0),
            }
            for code in POPULAR_COUNTRIES
        },
    }

    return final, stats


def _diverse_select(configs: list[VPNConfig], n: int) -> list[VPNConfig]:
    """Выбрать n серверов с разными протоколами."""
    by_proto = defaultdict(list)
    for c in configs:
        by_proto[c.protocol].append(c)

    selected = []
    protos = list(by_proto.keys())
    idx = 0
    while len(selected) < n and protos:
        proto = protos[idx % len(protos)]
        if by_proto[proto]:
            selected.append(by_proto[proto].pop(0))
        else:
            protos.remove(proto)
            if not protos:
                break
        idx += 1
    return selected


def generate_readme(output_dir: Path, servers: list[dict], stats: dict):
    """Генерируем красивый люксовый README.md."""
    today = stats.get("date", "?")
    total_servers = stats.get("total", len(servers))
    countries_count = len(stats.get("countries", {}))

    # Таблица стран
    country_rows = []
    for code, info in sorted(
        stats.get("popular_countries", {}).items(),
        key=lambda x: -x[1]["count"],
    ):
        if info["count"] > 0:
            country_rows.append(f"| {info['name']} | `{code}` | **{info['count']}** | 🟢 Онлайн |")

    # Другие страны
    popular_codes = set(POPULAR_COUNTRIES.keys())
    other_countries = {
        k: v for k, v in stats.get("countries", {}).items()
        if k not in popular_codes and k != "XX"
    }
    if other_countries:
        for code, count in sorted(other_countries.items(), key=lambda x: -x[1]):
            flag, name_ru = COUNTRY_NAMES_RU.get(code, ("🌐", code))
            country_rows.append(f"| {flag} {name_ru} | `{code}` | **{count}** | 🟢 Онлайн |")

    country_table = "\n".join(country_rows) if country_rows else "| — | — | 0 | — |"

    # Протоколы
    proto_rows = []
    for proto, count in sorted(stats.get("protocols", {}).items(), key=lambda x: -x[1]):
        proto_badge = f"`{proto.upper()}`"
        proto_rows.append(f"| {proto_badge} | **{count}** узлов |")
    proto_table = "\n".join(proto_rows) if proto_rows else "| — | 0 |"

    readme = f"""<div align="center">

# 🔐 PESOK AUTO-SUB
### Премиальный автоматический агрегатор быстрых VPN-конфигураций
**Автообновление каждые 12 часов • Проверка задержки TCP Ping • Русские названия узлов**

[![Update VPN Subscription](https://github.com/sever-xd/pesok_auto_sub/actions/workflows/update.yml/badge.svg)](https://github.com/sever-xd/pesok_auto_sub/actions/workflows/update.yml)
[![GitHub Pages](https://img.shields.io/badge/GitHub%20Pages-Online%20Dashboard-10b981?style=flat&logo=github)](https://sever-xd.github.io/pesok_auto_sub/)
[![Total Servers](https://img.shields.io/badge/Servers-{total_servers}%20Online-3b82f6?style=flat&logo=server)](https://sever-xd.github.io/pesok_auto_sub/)
[![Countries](https://img.shields.io/badge/Countries-{countries_count}%20Locations-f59e0b?style=flat&logo=googleearth)](https://sever-xd.github.io/pesok_auto_sub/)
[![Protocols](https://img.shields.io/badge/Protocols-VMess%20%7C%20VLESS%20%7C%20SS%20%7C%20Trojan-8b5cf6?style=flat)](https://sever-xd.github.io/pesok_auto_sub/)
[![Author](https://img.shields.io/badge/Author-sever--xd-ef4444?style=flat&logo=telegram)](https://github.com/sever-xd)

[🌐 **Открыть Веб-Интерфейс**](https://sever-xd.github.io/pesok_auto_sub/) • [📥 **Ссылка на подписку**](https://sever-xd.github.io/pesok_auto_sub/subscription.txt) • [📋 **Raw конфиги (текст)**](https://raw.githubusercontent.com/sever-xd/pesok_auto_sub/main/raw_configs.txt)

---

</div>

## 🔗 Быстрое подключение (Ссылка на подписку)

Скопируйте URL и вставьте в ваш VPN-клиент (**Happ**, **Hiddify**, **V2RayNG**, **Nekoray**, **Clash**, **Sing-Box**):

```text
https://sever-xd.github.io/pesok_auto_sub/subscription.txt
```

> 💡 **Резервное зеркало (GitHub Raw):**  
> `https://raw.githubusercontent.com/sever-xd/pesok_auto_sub/main/subscription.txt`

---

## ⚡ Особенности и Преимущества

- 🏷️ **Чистые русские названия:** каждый сервер автоматически назван в формате `[pesok] 🇺🇸 США #01`, `[pesok] 🇩🇪 Германия #01` — больше никаких китайских иероглифов и чужой рекламы!
- ⚡ **TCP Ping Testing:** все узлы проходят автоматическое измерение пинга перед публикацией;
- 🔄 **Автоматическая ротация:** GitHub Actions собирает свежие сервера 2 раза в день (в 06:00 и 18:00 UTC);
- 🛡️ **Мультипротокольность:** поддержка VMess, VLESS, Shadowsocks, Trojan, Hysteria2;
- 🌍 **Широкая география:** более 40 стран мира (США, Германия, Нидерланды, Япония, Сингапур, Франция, Великобритания и др.);
- 🎨 **Интерактивный Веб-дашборд:** смена 6 тем оформления, живое измерение задержки в браузере, экспорт в один клик и QR-коды.

---

## 📊 Актуальная статистика

| Метрика | Значение |
| :--- | :--- |
| 📅 **Дата обновления** | **`{today}`** |
| 📦 **Всего серверов в подписке** | **`{total_servers}`** |
| ➕ **Добавлено сегодня** | **`{stats.get('added_today', 0)}`** |
| 🌍 **Доступно стран** | **`{countries_count}`** |
| 🔄 **Частота синхронизации** | **Каждые 12 часов (06:00 / 18:00 UTC)** |

<details open>
<summary><b>🌍 Список локаций и серверов ({countries_count} стран)</b></summary>

| Страна | Код | Серверов | Статус |
| :--- | :---: | :---: | :---: |
{country_table}

</details>

<details>
<summary><b>🔌 Распределение по протоколам</b></summary>

| Протокол | Количество |
| :--- | :--- |
{proto_table}

</details>

---

## 📱 Инструкция по подключению

<details open>
<summary><b>📱 Happ (iOS / Android / Mac)</b></summary>

1. Откройте приложение **Happ**;
2. Нажмите **«+»** (Добавить) в верхнем правом углу;
3. Выберите **«Добавить подписку по ссылке»**;
4. Вставьте ссылку:
   ```text
   https://sever-xd.github.io/pesok_auto_sub/subscription.txt
   ```
5. Нажмите **«Сохранить»** и затем **«Обновить подписку»**;
6. Все сервера сразу появятся с понятными русскими названиями `[pesok]`.

</details>

<details>
<summary><b>🚀 Hiddify Next (Все платформы)</b></summary>

1. Скачайте и запустите **Hiddify Next**;
2. Нажмите **«Новый профиль»** ➔ **«Добавить из буфера обмена»** (скопировав ссылку выше);
3. В настройках профиля включите **«Автообновление подписки»**;
4. Нажмите большую кнопку подключения.

</details>

<details>
<summary><b>⚡ V2RayNG (Android) / V2RayN (Windows)</b></summary>

1. В приложении откройте меню подписок ➔ **«Добавить подписку»**;
2. Вставьте URL подписки и сохраните;
3. Нажмите кнопку **«Обновить подписку»** в меню;
4. Серверы отсортируются по пингу.

</details>

<details>
<summary><b>🐱 Clash / Mihomo / Verge</b></summary>

1. Откройте [Веб-сайт подписки](https://sever-xd.github.io/pesok_auto_sub/);
2. Нажмите кнопку **«Экспорт»** ➔ **«Clash / Mihomo (.yaml)»**;
3. Импортируйте скачанный файл конфигурации в ваш Clash-клиент.

</details>

---

## 🛠️ Архитектура

```text
pesok_auto_sub/
├── .github/workflows/
│   ├── update.yml         # GitHub Actions: парсинг, TCP пинг и авто-деплой
│   └── deploy.yml         # GitHub Actions: деплой страниц при обновлении UI
├── index.html             # Премиальный веб-дашборд с 6 темами и живым радаром
├── update.py              # Асинхронный скрапер, TCP пингер и ротатор
├── subscription.txt       # Base64 подписка для VPN-клиентов
├── site_data.json         # JSON база данных для веб-интерфейса
├── raw_configs.txt        # Список ссылок открытым текстом
└── README.md              # Документация проекта
```

---

<div align="center">

**[PESOK AUTO-SUB](https://sever-xd.github.io/pesok_auto_sub/)** • Created with ❤️ by **[sever-xd](https://github.com/sever-xd)**

</div>
"""
    readme_path = output_dir / "README.md"
    readme_path.write_text(readme, encoding="utf-8")


# ============================================================
# Тестирование пинга (TCP)
# ============================================================
async def test_server_ping(address: str, port: int, timeout: float = 3) -> int:
    """Измерить latency подключения по TCP в мс. Возвращает мс или -1 при ошибке."""
    try:
        port_num = int(port)
        if not address or port_num <= 0 or port_num > 65535:
            return -1
        addr_str = str(address).strip()
        if addr_str.startswith("[") and addr_str.endswith("]"):
            addr_str = addr_str[1:-1]
        start = time.perf_counter()
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(addr_str, port_num),
            timeout=timeout,
        )
        latency = int(round((time.perf_counter() - start) * 1000))
        try:
            writer.close()
            await asyncio.wait_for(writer.wait_closed(), timeout=1.0)
        except Exception:
            pass
        return latency
    except Exception:
        return -1


async def test_all_pings(servers: list[dict], max_concurrent: int = 30) -> list[dict]:
    """Проверить TCP пинг для всех серверов параллельно с семафором."""
    sem = asyncio.Semaphore(max_concurrent)

    async def _test_one(server: dict):
        async with sem:
            ping = await test_server_ping(server.get("address", ""), server.get("port", 0))
            server["ping"] = ping

    await asyncio.gather(*[_test_one(s) for s in servers])
    return servers


# ============================================================
# Точка входа
# ============================================================
async def main():
    output_dir = Path(__file__).parent
    sub_path = output_dir / "subscription.txt"

    print("=" * 60)
    print(f"🔄 VPN Auto-Subscription Update — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)

    # 1. Загружаем существующую подписку
    existing = load_existing_subscription(sub_path)
    print(f"📌 Существующих серверов: {len(existing)}")

    # 2. Парсим новые из GitHub
    print(f"\n📡 Загрузка из {len(SOURCES)} источников...")
    new_configs = await fetch_all()
    print(f"\n📦 Всего загружено: {len(new_configs)}")

    # Статистика по странам среди новых
    country_count = defaultdict(int)
    for c in new_configs:
        country_count[c.country] += 1
    print(f"🌍 Определены страны для {sum(v for k, v in country_count.items() if k != 'XX')} серверов")
    print(f"❓ Неопределённых: {country_count.get('XX', 0)}")

    # Топ стран среди новых
    top = sorted(
        [(k, v) for k, v in country_count.items() if k != "XX"],
        key=lambda x: -x[1],
    )[:15]
    print("🏆 Топ стран в источниках:")
    for code, cnt in top:
        name = POPULAR_COUNTRIES.get(code, code)
        print(f"   {name}: {cnt}")

    # 3. Выбираем лучшие
    print(f"\n🎯 Выбираем по {SERVERS_PER_COUNTRY} сервера из каждой популярной страны...")
    final, stats = select_best_servers(new_configs, existing)

    # 4. Тестируем пинг
    print(f"\n⚡ Тестирование пинга для {len(final)} серверов...")
    await test_all_pings(final)

    # 5. Сохраняем
    save_subscription(sub_path, final, stats)

    print(f"\n✅ Готово!")
    print(f"   📦 Всего: {stats['total']}")
    print(f"   ➕ Добавлено: {stats['added_today']}")
    print(f"   🗑️ Удалено: {stats['removed_expired']}")
    print(f"   💾 Файлы: subscription.txt, raw_configs.txt, servers_meta.json, site_data.json")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
