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
    ("freefq", "https://raw.githubusercontent.com/freefq/free/master/v2"),
    ("pawdroid", "https://raw.githubusercontent.com/Pawdroid/Free-servers/main/sub"),
    ("ermaozi", "https://raw.githubusercontent.com/ermaozi/get_subscribe/main/subscribe/v2ray.txt"),
    ("mahdibland", "https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/sub/sub_merge_base64.txt"),
    ("mfuu-v2ray", "https://raw.githubusercontent.com/mfuu/v2ray/master/merge/merge_base64.txt"),
    ("barry-far1", "https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/All_Configs_Sub.txt"),
    ("yebekhe-reality", "https://raw.githubusercontent.com/yebekhe/TelegramV2rayCollector/main/sub/base64/reality"),
    ("yebekhe-vmess", "https://raw.githubusercontent.com/yebekhe/TelegramV2rayCollector/main/sub/base64/vmess"),
    ("yebekhe-trojan", "https://raw.githubusercontent.com/yebekhe/TelegramV2rayCollector/main/sub/base64/trojan"),
    ("soroush-reality", "https://raw.githubusercontent.com/soroushmirzaei/telegram-configs-collector/main/subscribe/base64/reality"),
    ("soroush-vmess", "https://raw.githubusercontent.com/soroushmirzaei/telegram-configs-collector/main/subscribe/base64/vmess"),
    ("soroush-vless", "https://raw.githubusercontent.com/soroushmirzaei/telegram-configs-collector/main/subscribe/base64/vless"),
    ("soroush-trojan", "https://raw.githubusercontent.com/soroushmirzaei/telegram-configs-collector/main/subscribe/base64/trojan"),
    ("soroush-ss", "https://raw.githubusercontent.com/soroushmirzaei/telegram-configs-collector/main/subscribe/base64/ss"),
    ("lagzian-ss", "https://raw.githubusercontent.com/lagzian/SS-Collector/main/realss.txt"),
    ("sashalsk", "https://raw.githubusercontent.com/sashalsk/V2ray/main/V2ray"),
    ("peasoft", "https://raw.githubusercontent.com/peasoft/NoMoreWalls/master/list_raw.txt"),
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


def select_best_servers(
    new_configs: list[VPNConfig],
    existing: list[dict],
    per_country: int = SERVERS_PER_COUNTRY,
    max_age: int = MAX_AGE_DAYS,
) -> tuple[list[dict], dict]:
    """
    Выбрать лучшие сервера:
    - Из каждой популярной страны берём по per_country штук
    - Новые добавляем, старше max_age дней удаляем
    - Поддерживаем ротацию
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age)).strftime("%Y-%m-%d")

    # Существующие сервера: убираем устаревшие
    fresh_existing = []
    removed_count = 0
    for s in existing:
        if s.get("added_date", "2000-01-01") >= cutoff:
            fresh_existing.append(s)
        else:
            removed_count += 1

    # Fingerprints существующих
    existing_fps = {s["fingerprint"] for s in fresh_existing}

    # Группируем новые конфиги по странам
    by_country: dict[str, list[VPNConfig]] = defaultdict(list)
    for c in new_configs:
        if c.country != "XX" and c.fingerprint not in existing_fps:
            by_country[c.country].append(c)

    # Считаем сколько серверов каждой страны уже есть
    existing_by_country: dict[str, int] = defaultdict(int)
    for s in fresh_existing:
        existing_by_country[s.get("country", "XX")] += 1

    # Добавляем новые из популярных стран
    added = []
    for country_code in POPULAR_COUNTRIES:
        available = by_country.get(country_code, [])
        current_count = existing_by_country.get(country_code, 0)
        need = max(0, per_country - current_count)

        if need > 0 and available:
            # Предпочитаем разные протоколы
            selected = _diverse_select(available, need)
            for cfg in selected:
                server_dict = {
                    "protocol": cfg.protocol,
                    "raw": cfg.raw,
                    "address": cfg.address,
                    "port": cfg.port,
                    "remark": cfg.remark,
                    "country": cfg.country,
                    "fingerprint": cfg.fingerprint,
                    "added_date": today,
                }
                added.append(server_dict)
                existing_fps.add(cfg.fingerprint)

    # Также добавляем из непопулярных стран (если есть уникальные)
    other_countries = set(by_country.keys()) - set(POPULAR_COUNTRIES.keys())
    for cc in sorted(other_countries):
        available = by_country[cc]
        current_count = existing_by_country.get(cc, 0)
        need = max(0, 2 - current_count)  # Для непопулярных — макс 2
        if need > 0 and available:
            selected = _diverse_select(available, need)
            for cfg in selected:
                server_dict = {
                    "protocol": cfg.protocol,
                    "raw": cfg.raw,
                    "address": cfg.address,
                    "port": cfg.port,
                    "remark": cfg.remark,
                    "country": cfg.country,
                    "fingerprint": cfg.fingerprint,
                    "added_date": today,
                }
                added.append(server_dict)
                existing_fps.add(cfg.fingerprint)

    final = fresh_existing + added

    # Статистика
    country_stats = defaultdict(int)
    proto_stats = defaultdict(int)
    for s in final:
        country_stats[s.get("country", "XX")] += 1
        proto_stats[s.get("protocol", "?")] += 1

    stats = {
        "total": len(final),
        "added_today": len(added),
        "removed_expired": removed_count,
        "kept_from_previous": len(fresh_existing),
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
    """Генерируем красивый README.md."""
    today = stats.get("date", "?")

    # Таблица стран
    country_rows = []
    for code, info in sorted(
        stats.get("popular_countries", {}).items(),
        key=lambda x: -x[1]["count"],
    ):
        if info["count"] > 0:
            country_rows.append(f"| {info['name']} | `{code}` | **{info['count']}** |")

    # Другие страны
    popular_codes = set(POPULAR_COUNTRIES.keys())
    other_countries = {
        k: v for k, v in stats.get("countries", {}).items()
        if k not in popular_codes and k != "XX"
    }
    if other_countries:
        for code, count in sorted(other_countries.items(), key=lambda x: -x[1]):
            country_rows.append(f"| {code} | `{code}` | {count} |")

    country_table = "\n".join(country_rows) if country_rows else "| — | — | 0 |"

    # Протоколы
    proto_rows = []
    for proto, count in sorted(stats.get("protocols", {}).items(), key=lambda x: -x[1]):
        proto_rows.append(f"| {proto.upper()} | {count} |")
    proto_table = "\n".join(proto_rows) if proto_rows else "| — | 0 |"

    readme = f"""# 🔐 VPN Auto-Subscription

> Автоматически обновляемая подписка VPN серверов. Новые сервера каждый день!

## 📋 Ссылка подписки

Скопируй и вставь в **V2RayN / Nekoray / Hiddify / Clash / Remnawave / Streisand**:

```
https://raw.githubusercontent.com/YOUR_USERNAME/vpn-auto-sub/main/subscription.txt
```

> ⚠️ Замени `YOUR_USERNAME` на свой логин GitHub после создания репозитория!

## 📊 Статистика

| Метрика | Значение |
|---------|----------|
| 📅 Обновлено | **{today}** |
| 📦 Всего серверов | **{stats.get('total', 0)}** |
| ➕ Добавлено сегодня | **{stats.get('added_today', 0)}** |
| 🗑️ Удалено (устаревших) | **{stats.get('removed_expired', 0)}** |
| 📌 Из прошлого обновления | **{stats.get('kept_from_previous', 0)}** |

### 🌍 Серверы по странам

| Страна | Код | Кол-во |
|--------|-----|--------|
{country_table}

### 🔌 По протоколам

| Протокол | Кол-во |
|----------|--------|
{proto_table}

## 🔄 Автообновление

- GitHub Actions запускается **каждый день в 06:00 и 18:00 UTC**
- Из каждой популярной страны берётся **{SERVERS_PER_COUNTRY} сервера**
- Серверы старше **{MAX_AGE_DAYS} дней** удаляются автоматически
- Новые сервера парсятся из **{len(SOURCES)}+ открытых GitHub репозиториев**

## 📱 Как подключить

### V2RayN (Windows)
1. Подписки → Настройки подписки → ➕
2. Вставь URL подписки
3. Нажми «Обновить»

### Hiddify (Android/iOS)
1. ➕ Добавить профиль → Ссылка на подписку
2. Вставь URL

### Nekoray (Windows/Linux)
1. Программа → Подписки → Новая
2. Вставь URL

### Clash/Mihomo
Используй `raw_configs.txt` или конвертируй через sub-converter

### Remnawave
1. Настройки → Подписки → Добавить
2. Вставь URL подписки

---

🤖 *Автоматически сгенерировано [VPN Auto-Subscription Aggregator]()*
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
