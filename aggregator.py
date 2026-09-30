"""
VPN Subscription Aggregator
Автопарсер и генератор подписок VPN серверов с GitHub.

Поддерживает:
- vmess://, vless://, trojan://, ss://, ssr://
- Base64 декодирование подписок
- Автообновление по расписанию
- HTTP сервер для раздачи подписки
- Дедупликация и валидация
"""

import asyncio
import aiohttp
import base64
import hashlib
import json
import logging
import re
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

# ============================================================
# Настройка логирования
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("vpn-aggregator")


# ============================================================
# Модели данных
# ============================================================
@dataclass
class VPNConfig:
    """Один VPN конфиг (сервер)."""
    protocol: str        # vmess, vless, trojan, ss, ssr
    raw: str             # Оригинальная строка конфига
    address: str = ""
    port: int = 0
    remark: str = ""
    fingerprint: str = ""  # Уникальный хеш для дедупликации

    def __post_init__(self):
        if not self.fingerprint:
            # Создаём fingerprint из адреса + порта + протокола
            key = f"{self.protocol}:{self.address}:{self.port}"
            self.fingerprint = hashlib.md5(key.encode()).hexdigest()


@dataclass
class Source:
    """Источник конфигов."""
    name: str
    url: str
    enabled: bool = True
    last_fetch: Optional[datetime] = None
    config_count: int = 0
    error: Optional[str] = None


@dataclass
class AggregatorStats:
    """Статистика агрегатора."""
    total_sources: int = 0
    active_sources: int = 0
    failed_sources: int = 0
    total_configs: int = 0
    unique_configs: int = 0
    last_update: Optional[datetime] = None
    protocols: dict = field(default_factory=dict)


# ============================================================
# Парсер конфигов
# ============================================================
class ConfigParser:
    """Парсер VPN конфигов различных протоколов."""

    SUPPORTED_PROTOCOLS = ("vmess://", "vless://", "trojan://", "ss://", "ssr://")

    @staticmethod
    def try_decode_base64(text: str) -> str:
        """Пробуем декодировать base64, возвращаем оригинал если не получилось."""
        text = text.strip()
        if not text:
            return text
        try:
            # Добавляем padding если нужно
            padded = text + "=" * (4 - len(text) % 4) if len(text) % 4 else text
            decoded = base64.b64decode(padded).decode("utf-8", errors="ignore")
            # Проверяем, есть ли в декодированном тексте протоколы VPN
            if any(proto in decoded for proto in ConfigParser.SUPPORTED_PROTOCOLS):
                return decoded
            return text
        except Exception:
            return text

    @staticmethod
    def parse_vmess(uri: str) -> Optional[VPNConfig]:
        """Парсим vmess:// URI."""
        try:
            encoded = uri[len("vmess://"):].strip()
            padded = encoded + "=" * (4 - len(encoded) % 4) if len(encoded) % 4 else encoded
            data = json.loads(base64.b64decode(padded).decode("utf-8", errors="ignore"))
            return VPNConfig(
                protocol="vmess",
                raw=uri.strip(),
                address=data.get("add", ""),
                port=int(data.get("port", 0)),
                remark=data.get("ps", ""),
            )
        except Exception:
            return None

    @staticmethod
    def parse_vless(uri: str) -> Optional[VPNConfig]:
        """Парсим vless:// URI."""
        try:
            parsed = urllib.parse.urlparse(uri)
            remark = urllib.parse.unquote(parsed.fragment) if parsed.fragment else ""
            return VPNConfig(
                protocol="vless",
                raw=uri.strip(),
                address=parsed.hostname or "",
                port=parsed.port or 0,
                remark=remark,
            )
        except Exception:
            return None

    @staticmethod
    def parse_trojan(uri: str) -> Optional[VPNConfig]:
        """Парсим trojan:// URI."""
        try:
            parsed = urllib.parse.urlparse(uri)
            remark = urllib.parse.unquote(parsed.fragment) if parsed.fragment else ""
            return VPNConfig(
                protocol="trojan",
                raw=uri.strip(),
                address=parsed.hostname or "",
                port=parsed.port or 0,
                remark=remark,
            )
        except Exception:
            return None

    @staticmethod
    def parse_ss(uri: str) -> Optional[VPNConfig]:
        """Парсим ss:// (Shadowsocks) URI."""
        try:
            rest = uri[len("ss://"):].strip()
            # Формат: base64(method:password)@host:port#remark
            # или: method:password@host:port#remark
            remark = ""
            if "#" in rest:
                rest, remark = rest.rsplit("#", 1)
                remark = urllib.parse.unquote(remark)

            if "@" in rest:
                userinfo, hostport = rest.rsplit("@", 1)
            else:
                # Вся строка закодирована в base64
                try:
                    padded = rest + "=" * (4 - len(rest) % 4) if len(rest) % 4 else rest
                    decoded = base64.b64decode(padded).decode("utf-8", errors="ignore")
                    if "@" in decoded:
                        userinfo, hostport = decoded.rsplit("@", 1)
                    else:
                        return None
                except Exception:
                    return None

            # Извлекаем host и port
            if ":" in hostport:
                host, port_str = hostport.rsplit(":", 1)
                port = int(port_str)
            else:
                host = hostport
                port = 0

            return VPNConfig(
                protocol="ss",
                raw=uri.strip(),
                address=host,
                port=port,
                remark=remark,
            )
        except Exception:
            return None

    @staticmethod
    def parse_ssr(uri: str) -> Optional[VPNConfig]:
        """Парсим ssr:// URI."""
        try:
            encoded = uri[len("ssr://"):].strip()
            padded = encoded + "=" * (4 - len(encoded) % 4) if len(encoded) % 4 else encoded
            decoded = base64.b64decode(padded).decode("utf-8", errors="ignore")
            # Формат: host:port:protocol:method:obfs:password/?params
            parts = decoded.split(":")
            if len(parts) >= 2:
                host = parts[0]
                port = int(parts[1])
            else:
                return None

            return VPNConfig(
                protocol="ssr",
                raw=uri.strip(),
                address=host,
                port=port,
                remark="SSR",
            )
        except Exception:
            return None

    @classmethod
    def parse_line(cls, line: str) -> Optional[VPNConfig]:
        """Парсим одну строку конфига."""
        line = line.strip()
        if not line or len(line) < 10:
            return None

        if line.startswith("vmess://"):
            return cls.parse_vmess(line)
        elif line.startswith("vless://"):
            return cls.parse_vless(line)
        elif line.startswith("trojan://"):
            return cls.parse_trojan(line)
        elif line.startswith("ss://"):
            return cls.parse_ss(line)
        elif line.startswith("ssr://"):
            return cls.parse_ssr(line)
        return None

    @classmethod
    def parse_content(cls, content: str) -> list[VPNConfig]:
        """Парсим весь контент (может быть base64 или plain text)."""
        # Пробуем декодировать base64
        decoded = cls.try_decode_base64(content)

        configs = []
        for line in decoded.splitlines():
            line = line.strip()
            if not line:
                continue
            config = cls.parse_line(line)
            if config:
                configs.append(config)

        return configs


# ============================================================
# Сборщик конфигов с GitHub
# ============================================================
class GitHubFetcher:
    """Асинхронный сборщик конфигов с GitHub."""

    def __init__(self, sources: list[Source], timeout: int = 15):
        self.sources = sources
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.parser = ConfigParser()

    async def fetch_source(self, session: aiohttp.ClientSession, source: Source) -> list[VPNConfig]:
        """Загружаем конфиги из одного источника."""
        if not source.enabled:
            return []

        try:
            logger.info(f"  📥 Загрузка: {source.name} ({source.url[:60]}...)")
            async with session.get(source.url, timeout=self.timeout) as resp:
                if resp.status != 200:
                    source.error = f"HTTP {resp.status}"
                    logger.warning(f"  ⚠️  {source.name}: HTTP {resp.status}")
                    return []

                content = await resp.text(errors="ignore")
                configs = self.parser.parse_content(content)

                source.config_count = len(configs)
                source.last_fetch = datetime.now(timezone.utc)
                source.error = None

                logger.info(f"  ✅ {source.name}: найдено {len(configs)} конфигов")
                return configs

        except asyncio.TimeoutError:
            source.error = "Timeout"
            logger.warning(f"  ⏱️  {source.name}: таймаут")
            return []
        except Exception as e:
            source.error = str(e)
            logger.warning(f"  ❌ {source.name}: {e}")
            return []

    async def fetch_all(self) -> list[VPNConfig]:
        """Загружаем конфиги из всех источников."""
        all_configs = []
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/plain, */*",
        }

        async with aiohttp.ClientSession(headers=headers) as session:
            tasks = [self.fetch_source(session, src) for src in self.sources if src.enabled]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, list):
                    all_configs.extend(result)
                elif isinstance(result, Exception):
                    logger.error(f"  ❌ Ошибка при загрузке: {result}")

        return all_configs


# ============================================================
# Авто-поиск новых репозиториев на GitHub
# ============================================================
class GitHubAutoDiscovery:
    """Автоматический поиск новых репозиториев с VPN конфигами."""

    SEARCH_QUERIES = [
        "v2ray free servers",
        "xray free subscription",
        "vmess vless free",
        "v2ray collector subscribe",
        "telegram v2ray collector",
        "free proxy v2ray",
    ]

    # Паттерны для поиска raw ссылок в README
    RAW_PATTERNS = [
        r'https://raw\.githubusercontent\.com/[^\s\)\"\']+(?:v2ray|vmess|vless|trojan|sub|subscribe|clash)[^\s\)\"\']*',
    ]

    async def search_github_repos(self, session: aiohttp.ClientSession, query: str) -> list[dict]:
        """Поиск репозиториев через GitHub API."""
        repos = []
        try:
            url = "https://api.github.com/search/repositories"
            params = {
                "q": query,
                "sort": "updated",
                "order": "desc",
                "per_page": 10,
            }
            async with session.get(url, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    repos = data.get("items", [])
                elif resp.status == 403:
                    logger.warning("GitHub API rate limit exceeded")
        except Exception as e:
            logger.warning(f"GitHub search error: {e}")
        return repos

    async def find_subscription_urls(self, session: aiohttp.ClientSession, repo: dict) -> list[str]:
        """Ищем subscription URL в README репозитория."""
        urls = []
        try:
            owner = repo.get("owner", {}).get("login", "")
            name = repo.get("name", "")
            default_branch = repo.get("default_branch", "main")

            # Пробуем прочитать README
            for readme_name in ["README.md", "readme.md", "README.MD"]:
                readme_url = f"https://raw.githubusercontent.com/{owner}/{name}/{default_branch}/{readme_name}"
                try:
                    async with session.get(readme_url) as resp:
                        if resp.status == 200:
                            content = await resp.text(errors="ignore")
                            for pattern in self.RAW_PATTERNS:
                                found = re.findall(pattern, content)
                                urls.extend(found)
                            break
                except Exception:
                    continue

            # Также пробуем стандартные пути
            common_paths = [
                f"https://raw.githubusercontent.com/{owner}/{name}/{default_branch}/sub",
                f"https://raw.githubusercontent.com/{owner}/{name}/{default_branch}/v2ray",
                f"https://raw.githubusercontent.com/{owner}/{name}/{default_branch}/subscribe",
                f"https://raw.githubusercontent.com/{owner}/{name}/{default_branch}/v2",
            ]
            for path_url in common_paths:
                try:
                    async with session.head(path_url) as resp:
                        if resp.status == 200:
                            urls.append(path_url)
                except Exception:
                    continue

        except Exception as e:
            logger.warning(f"Error scanning repo {repo.get('full_name', '?')}: {e}")

        return list(set(urls))

    async def discover(self) -> list[Source]:
        """Автоматический поиск новых источников."""
        logger.info("🔍 Авто-поиск новых источников на GitHub...")
        discovered = []
        seen_urls = set()

        headers = {
            "User-Agent": "VPN-Sub-Aggregator/1.0",
            "Accept": "application/vnd.github.v3+json",
        }
        timeout = aiohttp.ClientTimeout(total=20)

        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
            for query in self.SEARCH_QUERIES:
                repos = await self.search_github_repos(session, query)
                for repo in repos:
                    sub_urls = await self.find_subscription_urls(session, repo)
                    for url in sub_urls:
                        if url not in seen_urls:
                            seen_urls.add(url)
                            discovered.append(Source(
                                name=f"auto-{repo.get('full_name', 'unknown')}",
                                url=url,
                                enabled=True,
                            ))
                # Пауза между запросами чтобы не попасть в rate limit
                await asyncio.sleep(2)

        logger.info(f"🔍 Обнаружено {len(discovered)} новых источников")
        return discovered


# ============================================================
# Генератор подписки
# ============================================================
class SubscriptionGenerator:
    """Генерация файла подписки."""

    @staticmethod
    def deduplicate(configs: list[VPNConfig]) -> list[VPNConfig]:
        """Удаляем дубликаты по fingerprint."""
        seen = set()
        unique = []
        for config in configs:
            if config.fingerprint not in seen:
                seen.add(config.fingerprint)
                unique.append(config)
        return unique

    @staticmethod
    def generate_plain(configs: list[VPNConfig]) -> str:
        """Генерация plain-text подписки (по одной ссылке на строку)."""
        return "\n".join(c.raw for c in configs)

    @staticmethod
    def generate_base64(configs: list[VPNConfig]) -> str:
        """Генерация base64-encoded подписки (стандартный формат)."""
        plain = SubscriptionGenerator.generate_plain(configs)
        return base64.b64encode(plain.encode("utf-8")).decode("utf-8")

    @staticmethod
    def get_stats(configs: list[VPNConfig]) -> dict:
        """Статистика по протоколам."""
        stats = {}
        for c in configs:
            stats[c.protocol] = stats.get(c.protocol, 0) + 1
        return stats


# ============================================================
# HTTP Сервер для подписки
# ============================================================
class SubscriptionServer:
    """HTTP сервер для раздачи подписки как URL."""

    def __init__(self, host: str, port: int, output_dir: Path):
        self.host = host
        self.port = port
        self.output_dir = output_dir

    async def handle_subscription(self, request):
        """Обработчик запроса подписки (base64)."""
        from aiohttp import web
        sub_file = self.output_dir / "subscription.txt"
        if sub_file.exists():
            content = sub_file.read_text(encoding="utf-8")
            return web.Response(
                text=content,
                content_type="text/plain",
                headers={
                    "subscription-userinfo": f"upload=0; download=0; total=10737418240; expire=0",
                    "profile-update-interval": "1",
                    "content-disposition": "attachment; filename=vpn_subscription",
                },
            )
        return web.Response(text="No subscription data yet", status=503)

    async def handle_raw(self, request):
        """Обработчик запроса raw конфигов (без base64)."""
        from aiohttp import web
        raw_file = self.output_dir / "raw_configs.txt"
        if raw_file.exists():
            content = raw_file.read_text(encoding="utf-8")
            return web.Response(text=content, content_type="text/plain")
        return web.Response(text="No data yet", status=503)

    async def handle_stats(self, request):
        """Обработчик запроса статистики."""
        from aiohttp import web
        stats_file = self.output_dir / "stats.json"
        if stats_file.exists():
            content = stats_file.read_text(encoding="utf-8")
            return web.Response(text=content, content_type="application/json")
        return web.Response(text="{}", content_type="application/json")

    async def handle_index(self, request):
        """Главная страница."""
        from aiohttp import web
        html = """<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>VPN Subscription Aggregator</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
               background: #0a0a0f; color: #e0e0e0; min-height: 100vh; padding: 20px; }
        .container { max-width: 800px; margin: 0 auto; }
        h1 { color: #00d4ff; margin-bottom: 10px; font-size: 28px; }
        .subtitle { color: #666; margin-bottom: 30px; }
        .card { background: #14141f; border: 1px solid #222; border-radius: 12px;
                padding: 20px; margin-bottom: 16px; }
        .card h2 { color: #00d4ff; font-size: 18px; margin-bottom: 10px; }
        .url-box { background: #1a1a2e; border: 1px solid #333; border-radius: 8px;
                   padding: 12px 16px; font-family: monospace; font-size: 14px;
                   word-break: break-all; color: #00ff88; cursor: pointer; }
        .url-box:hover { background: #222240; }
        .label { color: #888; font-size: 13px; margin-bottom: 6px; }
        .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 12px; }
        .stat { text-align: center; padding: 16px; background: #1a1a2e; border-radius: 8px; }
        .stat .value { font-size: 28px; font-weight: bold; color: #00d4ff; }
        .stat .name { font-size: 12px; color: #666; margin-top: 4px; }
        .badge { display: inline-block; padding: 2px 8px; border-radius: 4px;
                 font-size: 12px; margin: 2px; }
        .badge-vmess { background: #1a3a1a; color: #00ff88; }
        .badge-vless { background: #1a1a3a; color: #00aaff; }
        .badge-trojan { background: #3a1a1a; color: #ff6666; }
        .badge-ss { background: #3a3a1a; color: #ffaa00; }
        footer { text-align: center; color: #444; margin-top: 40px; font-size: 13px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🔐 VPN Subscription Aggregator</h1>
        <p class="subtitle">Авто-обновляемые VPN подписки с GitHub</p>

        <div class="card">
            <h2>📋 Ссылка подписки (Base64)</h2>
            <p class="label">Вставьте в V2RayN / Nekoray / Hiddify / Remnawave:</p>
            <div class="url-box" onclick="copyToClipboard(this)" id="sub-url"></div>
        </div>

        <div class="card">
            <h2>📄 Raw конфиги</h2>
            <p class="label">Прямые ссылки без кодирования:</p>
            <div class="url-box" onclick="copyToClipboard(this)" id="raw-url"></div>
        </div>

        <div class="card">
            <h2>📊 Статистика</h2>
            <div class="stats" id="stats-container">
                <div class="stat"><div class="value" id="total-count">-</div><div class="name">Всего</div></div>
                <div class="stat"><div class="value" id="unique-count">-</div><div class="name">Уникальных</div></div>
                <div class="stat"><div class="value" id="sources-count">-</div><div class="name">Источников</div></div>
            </div>
            <div style="margin-top:12px" id="protocols"></div>
            <p class="label" style="margin-top:12px" id="last-update"></p>
        </div>

        <footer>
            Автообновление каждые 30 мин • Данные из открытых GitHub репозиториев
        </footer>
    </div>

    <script>
        const host = window.location.origin;
        document.getElementById('sub-url').textContent = host + '/sub';
        document.getElementById('raw-url').textContent = host + '/raw';

        function copyToClipboard(el) {
            navigator.clipboard.writeText(el.textContent);
            const orig = el.textContent;
            el.textContent = '✅ Скопировано!';
            setTimeout(() => el.textContent = orig, 1500);
        }

        fetch('/stats').then(r=>r.json()).then(data => {
            document.getElementById('total-count').textContent = data.total_configs || '-';
            document.getElementById('unique-count').textContent = data.unique_configs || '-';
            document.getElementById('sources-count').textContent = data.active_sources || '-';
            if (data.protocols) {
                const el = document.getElementById('protocols');
                const badges = {vmess:'badge-vmess', vless:'badge-vless', trojan:'badge-trojan', ss:'badge-ss'};
                el.innerHTML = Object.entries(data.protocols).map(([k,v]) =>
                    `<span class="badge ${badges[k]||''}">${k}: ${v}</span>`
                ).join('');
            }
            if (data.last_update) {
                document.getElementById('last-update').textContent =
                    '🕐 Обновлено: ' + new Date(data.last_update).toLocaleString();
            }
        }).catch(()=>{});
    </script>
</body>
</html>"""
        return web.Response(text=html, content_type="text/html")

    async def start(self):
        """Запуск HTTP сервера."""
        from aiohttp import web
        app = web.Application()
        app.router.add_get("/", self.handle_index)
        app.router.add_get("/sub", self.handle_subscription)
        app.router.add_get("/raw", self.handle_raw)
        app.router.add_get("/stats", self.handle_stats)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)
        await site.start()
        logger.info(f"🌐 HTTP сервер запущен: http://{self.host}:{self.port}")
        logger.info(f"📋 Ссылка подписки: http://localhost:{self.port}/sub")
        logger.info(f"📄 Raw конфиги:     http://localhost:{self.port}/raw")
        logger.info(f"📊 Статистика:      http://localhost:{self.port}/stats")
        return runner


# ============================================================
# Главный агрегатор
# ============================================================
class VPNAggregator:
    """Главный класс агрегатора."""

    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = Path(config_path)
        self.config = self._load_config()
        self.output_dir = self.config_path.parent
        self.sources = self._load_sources()
        self.stats = AggregatorStats()

    def _load_config(self) -> dict:
        """Загрузка конфигурации."""
        if self.config_path.exists():
            with open(self.config_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f)
        return {}

    def _load_sources(self) -> list[Source]:
        """Загрузка источников из конфига."""
        sources = []
        for src in self.config.get("sources", []):
            sources.append(Source(
                name=src.get("name", "unknown"),
                url=src.get("url", ""),
                enabled=src.get("enabled", True),
            ))
        return sources

    async def update(self):
        """Одно обновление: загрузить, распарсить, сохранить."""
        logger.info("=" * 60)
        logger.info("🔄 Начинаем обновление конфигов...")
        logger.info(f"📡 Источников: {len(self.sources)}")

        # Загружаем конфиги
        fetcher = GitHubFetcher(self.sources)
        all_configs = await fetcher.fetch_all()

        logger.info(f"📦 Всего загружено: {len(all_configs)} конфигов")

        # Дедупликация
        generator = SubscriptionGenerator()
        unique_configs = generator.deduplicate(all_configs)
        logger.info(f"✨ Уникальных: {len(unique_configs)} конфигов")

        # Статистика протоколов
        proto_stats = generator.get_stats(unique_configs)
        for proto, count in sorted(proto_stats.items()):
            logger.info(f"   {proto}: {count}")

        # Сохраняем подписку (base64)
        sub_content = generator.generate_base64(unique_configs)
        sub_file = self.output_dir / "subscription.txt"
        sub_file.write_text(sub_content, encoding="utf-8")

        # Сохраняем raw конфиги
        raw_content = generator.generate_plain(unique_configs)
        raw_file = self.output_dir / "raw_configs.txt"
        raw_file.write_text(raw_content, encoding="utf-8")

        # Сохраняем статистику
        now = datetime.now(timezone.utc).isoformat()
        self.stats = AggregatorStats(
            total_sources=len(self.sources),
            active_sources=sum(1 for s in self.sources if s.error is None and s.config_count > 0),
            failed_sources=sum(1 for s in self.sources if s.error is not None),
            total_configs=len(all_configs),
            unique_configs=len(unique_configs),
            last_update=datetime.now(timezone.utc),
            protocols=proto_stats,
        )
        stats_file = self.output_dir / "stats.json"
        stats_data = {
            "total_sources": self.stats.total_sources,
            "active_sources": self.stats.active_sources,
            "failed_sources": self.stats.failed_sources,
            "total_configs": self.stats.total_configs,
            "unique_configs": self.stats.unique_configs,
            "last_update": now,
            "protocols": self.stats.protocols,
            "sources": [
                {
                    "name": s.name,
                    "url": s.url,
                    "enabled": s.enabled,
                    "config_count": s.config_count,
                    "error": s.error,
                    "last_fetch": s.last_fetch.isoformat() if s.last_fetch else None,
                }
                for s in self.sources
            ],
        }
        stats_file.write_text(json.dumps(stats_data, indent=2, ensure_ascii=False), encoding="utf-8")

        logger.info(f"💾 Подписка сохранена: {sub_file}")
        logger.info(f"💾 Raw конфиги: {raw_file}")
        logger.info("✅ Обновление завершено!")
        logger.info("=" * 60)

        return unique_configs

    async def auto_discover_sources(self):
        """Автоматический поиск новых источников."""
        discovery = GitHubAutoDiscovery()
        new_sources = await discovery.discover()

        existing_urls = {s.url for s in self.sources}
        added = 0
        for src in new_sources:
            if src.url not in existing_urls:
                self.sources.append(src)
                existing_urls.add(src.url)
                added += 1
                logger.info(f"  ➕ Новый источник: {src.name} -> {src.url[:60]}...")

        if added:
            logger.info(f"🔍 Добавлено {added} новых источников")
        else:
            logger.info("🔍 Новых источников не обнаружено")

    async def run(self, with_server: bool = True, with_discovery: bool = False):
        """Запуск агрегатора с автообновлением."""
        interval = self.config.get("update_interval", 30) * 60  # в секунды

        # Авто-поиск новых источников (опционально)
        if with_discovery:
            await self.auto_discover_sources()

        # Первое обновление
        await self.update()

        # Запускаем HTTP сервер
        runner = None
        if with_server:
            server_cfg = self.config.get("server", {})
            host = server_cfg.get("host", "0.0.0.0")
            port = server_cfg.get("port", 8080)
            server = SubscriptionServer(host, port, self.output_dir)
            runner = await server.start()

        # Цикл автообновления
        logger.info(f"⏰ Автообновление каждые {interval // 60} мин")
        try:
            while True:
                await asyncio.sleep(interval)
                try:
                    if with_discovery:
                        await self.auto_discover_sources()
                    await self.update()
                except Exception as e:
                    logger.error(f"❌ Ошибка при обновлении: {e}")
        except asyncio.CancelledError:
            pass
        finally:
            if runner:
                await runner.cleanup()


# ============================================================
# Точка входа
# ============================================================
def main():
    import argparse

    parser = argparse.ArgumentParser(description="VPN Subscription Aggregator")
    parser.add_argument("--config", default="config.yaml", help="Путь к конфигу")
    parser.add_argument("--once", action="store_true", help="Обновить один раз и выйти")
    parser.add_argument("--no-server", action="store_true", help="Без HTTP сервера")
    parser.add_argument("--discover", action="store_true", help="Авто-поиск новых источников")
    parser.add_argument("--port", type=int, help="Порт HTTP сервера")
    args = parser.parse_args()

    aggregator = VPNAggregator(args.config)

    if args.port:
        aggregator.config.setdefault("server", {})["port"] = args.port

    if args.once:
        asyncio.run(aggregator.update())
    else:
        asyncio.run(aggregator.run(
            with_server=not args.no_server,
            with_discovery=args.discover,
        ))


if __name__ == "__main__":
    main()
