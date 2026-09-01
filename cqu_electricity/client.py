from __future__ import annotations

import re
import secrets
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation
from html import unescape
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

import ddddocr
import requests
from bs4 import BeautifulSoup
from loguru import logger

from .config import Settings
from .models import MeterReading

class CquError(RuntimeError):
    """抓取流程出现可说明的错误。"""


class LoginError(CquError):
    pass


class ParseError(CquError):
    pass


def _rsa_encrypt_pkcs1_v15(password: str, exponent_hex: str, modulus_hex: str) -> str:
    """兼容登录页 RSA.js 的 PKCS#1 v1.5 公钥加密结果。"""
    exponent = int(exponent_hex, 16)
    modulus = int(modulus_hex, 16)
    size = (modulus.bit_length() + 7) // 8
    message = password.encode("utf-8")
    if len(message) > size - 11:
        raise LoginError("查询密码过长，无法使用平台公钥加密")
    padding_length = size - len(message) - 3
    padding = bytes(secrets.randbelow(255) + 1 for _ in range(padding_length))
    encoded = b"\x00\x02" + padding + b"\x00" + message
    encrypted = pow(int.from_bytes(encoded, "big"), exponent, modulus)
    # RSA.js 按 16 位 digit 输出，每个 digit 固定四位十六进制。
    text = format(encrypted, "x")
    return text.zfill((len(text) + 3) // 4 * 4)


def _number(value: Any, label: str) -> Decimal:
    match = re.search(r"-?\d+(?:\.\d+)?", unescape(str(value)).replace(",", ""))
    if not match:
        raise ParseError(f"响应中缺少{label}")
    try:
        return Decimal(match.group())
    except InvalidOperation as exc:
        raise ParseError(f"无法解析{label}: {value!r}") from exc


class CquElectricityClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/128.0 Safari/537.36"
                ),
            }
        )
        self._ocr = ddddocr.DdddOcr(show_ad=False)

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        kwargs.setdefault("timeout", self.settings.request_timeout)
        headers = dict(kwargs.pop("headers", {}))
        page_token = self.session.cookies.get("pageToken")
        if page_token:
            headers["X_REQUESTED_WITH"] = page_token
        if headers:
            kwargs["headers"] = headers
        response = self.session.request(method, url, **kwargs)
        response.raise_for_status()
        return response

    def login(self) -> None:
        root = self.settings.portal_url + "/"
        self._request("GET", root)
        browser_headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Origin": self.settings.portal_url,
            "Referer": root,
        }
        last_message = ""
        for attempt in range(1, self.settings.login_retries + 1):
            captcha_response = self._request(
                "GET",
                urljoin(root, f"Login/GetValidateCode?time={int(time.time() * 1000)}"),
            )
            captcha = re.sub(r"\D", "", self._ocr.classification(captcha_response.content))
            if len(captcha) != 5:
                logger.warning("第 {} 次验证码识别结果格式异常，正在换图", attempt)
                continue

            key_data = self._request(
                "POST",
                urljoin(root, "Common/GetRsaKey"),
                data={"json": "true"},
                headers=browser_headers,
            ).json()
            if not key_data.get("IsSucceed") or "," not in str(key_data.get("Obj", "")):
                raise LoginError("平台未返回有效 RSA 登录公钥")
            exponent, modulus = key_data["Obj"].split(",", 1)
            payload = {
                "sno": self.settings.account,
                "pwd": _rsa_encrypt_pkcs1_v15(self.settings.password, exponent, modulus),
                "remember": "0",
                "yzm": captcha,
                "key": key_data["Msg"],
                "json": "true",
            }
            result = self._request(
                "POST",
                urljoin(root, "Login/NcLogin"),
                data=payload,
                headers=browser_headers,
            ).json()
            if result.get("IsSucceed"):
                logger.info("重庆大学服务大厅登录成功")
                return
            last_message = str(result.get("Msg") or "未知错误")
            if "验证码" not in last_message:
                detail = result.get("Obj")
                suffix = f"（代码：{detail}）" if detail not in (None, "") else ""
                raise LoginError(f"登录失败：{last_message}{suffix}")
            logger.warning("第 {} 次验证码未通过，正在重试", attempt)
        raise LoginError(f"验证码连续 {self.settings.login_retries} 次未通过：{last_message}")

    def fetch(self) -> MeterReading:
        self.login()
        response = self._request("GET", self.settings.electricity_url, allow_redirects=False)
        location = response.headers.get("Location", "") if response.is_redirect else response.url
        self._authenticate_charge(location)
        public = urlparse(self.settings.electricity_url)
        query_url = f"{public.scheme}://{public.netloc}/charge/feeitem/getThirdData"
        result, building_name = self._query_room(query_url)
        response_map = result.get("map") or {}
        combined = {
            **(response_map.get("data") or {}),
            **(response_map.get("showData") or {}),
            "room": self.settings.room,
            "building": building_name,
        }
        return self._extract_json(combined)

    def _query_room(self, query_url: str) -> tuple[dict[str, Any], str]:
        base = {"feeitemid": self.settings.fee_item_id}
        initial = self._request(
            "POST", query_url, data={**base, "type": "select", "level": 0}
        ).json()
        initial_map = initial.get("map") or {}
        levels = initial_map.get("total") or []
        buildings = initial_map.get("data") or []
        if initial.get("code") != 200 or len(levels) < 2 or not buildings:
            raise CquError(f"无法加载楼栋列表：{initial.get('msg') or initial}")

        building_code = str(levels[0].get("code") or "building")
        room_code = str(levels[-1].get("code") or "room")
        building_candidates = self._building_candidates(buildings)
        if not building_candidates:
            wanted = self.settings.building or self.settings.room
            raise CquError(f"楼栋列表中找不到 {wanted!r}")

        matched_room: dict[str, Any] | None = None
        matched_building: dict[str, Any] | None = None
        for building in building_candidates:
            rooms_result = self._request(
                "POST",
                query_url,
                data={
                    **base,
                    "type": "select",
                    "level": 1,
                    building_code: building["value"],
                },
            ).json()
            rooms = (rooms_result.get("map") or {}).get("data") or []
            matched_room = next(
                (
                    room
                    for room in rooms
                    if str(room.get("name", "")).strip().upper() == self.settings.room
                    or str(room.get("value", "")).strip().upper() == self.settings.room
                ),
                None,
            )
            if matched_room:
                matched_building = building
                break

        if not matched_room or not matched_building:
            building_text = self.settings.building or "自动识别的宿舍楼"
            raise CquError(f"{building_text} 中找不到房间 {self.settings.room}")

        final = self._request(
            "POST",
            query_url,
            data={
                **base,
                "type": "IEC",
                "level": len(levels),
                building_code: matched_building["value"],
                room_code: matched_room["value"],
            },
        ).json()
        final_map = final.get("map") or {}
        if final.get("code") != 200 or not final_map.get("showData"):
            raise CquError(f"电费查询失败：{final.get('msg') or final}")
        return final, str(matched_building.get("name") or matched_building["value"])

    def _building_candidates(self, buildings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if self.settings.building:
            wanted = self.settings.building.strip().lower()
            return [
                item
                for item in buildings
                if wanted == str(item.get("name", "")).strip().lower()
                or wanted == str(item.get("value", "")).strip().lower()
            ]

        # 虎溪房号首字母对应园区，首个数字对应楼号；优先查询最可能楼栋。
        garden_by_prefix = {"A": "梅园", "B": "竹园", "C": "松园", "D": "兰园"}
        garden = garden_by_prefix.get(self.settings.room[:1])
        number_match = re.search(r"\d", self.settings.room)
        number = number_match.group() if number_match else ""
        preferred = [
            item
            for item in buildings
            if garden
            and garden in str(item.get("name", ""))
            and number in str(item.get("name", ""))
        ]
        # 未识别时只遍历看起来像宿舍的选项，避免查询商户和教学楼。
        fallback = [
            item
            for item in buildings
            if item not in preferred
            and any(word in str(item.get("name", "")) for word in ("园", "公寓", "宿舍"))
        ]
        return preferred + fallback

    def _authenticate_charge(self, location: str) -> None:
        if not location:
            raise CquError("电费服务没有返回登录 ticket")
        # 某些部署把 ? 和 & 混用，手工兜底提取 ticket。
        query = parse_qs(urlparse(location).query)
        ticket = (query.get("ticket") or [None])[0]
        if not ticket:
            match = re.search(r"(?:[?&])ticket=([^&#]+)", location)
            ticket = match.group(1) if match else None
        # 重庆大学当前部署通过旧大厅的 hallticket Cookie 传递单点登录票据，
        # 跳转 URL 只暴露内网地址，不包含 ticket 查询参数。
        if not ticket:
            ticket = self.session.cookies.get("hallticket")
        if not ticket:
            raise LoginError("服务大厅已登录，但电费子系统未返回认证 ticket")

        public = urlparse(self.settings.electricity_url)
        token_url = f"{public.scheme}://{public.netloc}/blade-auth/token/fwdt"
        result = self._request("POST", token_url, data={"ticket": ticket}).json()
        data = result.get("data") or {}
        token = data.get("access_token")
        if result.get("code") != 200 or not token:
            raise LoginError(f"电费子系统认证失败：{result.get('msg') or '未返回令牌'}")
        authorization = f"bearer {token}"
        self.session.headers["synjones-auth"] = authorization
        # 网页端也把令牌写入 /charge 路径 Cookie；一并设置以兼容不同版本。
        self.session.cookies.set("synjones-auth", authorization, domain=public.hostname, path="/charge")

    def _extract_reading(self, response: requests.Response) -> MeterReading:
        content_type = response.headers.get("Content-Type", "")
        if "json" in content_type:
            return self._extract_json(response.json())

        text = response.text
        if "登录" in text and "电表读数" not in text and "meter" not in text.lower():
            raise LoginError("服务大厅已登录，但电费子系统未建立登录态")
        return self._extract_html(text)

    def _extract_json(self, data: Any) -> MeterReading:
        candidates: list[dict[str, Any]] = []

        def visit(value: Any) -> None:
            if isinstance(value, dict):
                candidates.append(value)
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        visit(data)
        room_key_names = ("room", "roomname", "fjmc", "accountname")
        target = next(
            (
                item
                for item in candidates
                if any(str(item.get(k, "")).upper() == self.settings.room for k in room_key_names)
            ),
            candidates[0] if candidates else {},
        )

        # 第三方水电接口常用 [{name/label: "剩余金额", value: "84.57"}]。
        labelled: dict[str, Any] = {}
        for item in candidates:
            label = item.get("name") or item.get("label") or item.get("title") or item.get("text")
            value = item.get("value") if "value" in item else item.get("data")
            if label not in (None, "") and value not in (None, ""):
                labelled[str(label).strip().lower()] = value

        all_values: dict[str, Any] = {}
        for item in candidates:
            for key, value in item.items():
                if not isinstance(value, (dict, list)) and value not in (None, ""):
                    all_values.setdefault(str(key).strip().lower(), value)

        def pick(*names: str) -> Any:
            lowered = {str(k).strip().lower(): v for k, v in target.items()}
            for name in names:
                normalized = name.lower()
                if normalized in lowered and lowered[normalized] not in (None, ""):
                    return lowered[normalized]
                if normalized in all_values:
                    return all_values[normalized]
                if normalized in labelled:
                    return labelled[normalized]
            raise ParseError(f"接口 JSON 缺少字段：{'/'.join(names)}")

        return MeterReading(
            captured_at=datetime.now(self.settings.timezone),
            room=self.settings.room,
            building=str(
                target.get("building")
                or target.get("buildingname")
                or all_values.get("building")
                or all_values.get("buildingname")
                or self.settings.building
                or ""
            ),
            balance_yuan=_number(
                pick(
                    "balance",
                    "money",
                    "surplusmoney",
                    "remainingamount",
                    "剩余金额",
                    "余额",
                ),
                "余额",
            ),
            meter_reading_kwh=_number(
                pick(
                    "meterreading",
                    "reading",
                    "electricreading",
                    "usedegree",
                    "quantity",
                    "电表读数",
                    "电量读数",
                ),
                "电表读数",
            ),
            subsidy_kwh=self._optional_number(
                {**all_values, **labelled, **target},
                "subsidy",
                "electricallowance",
                "surplusdegree",
                "电剩余补助（度）",
                "电剩余补助",
            ),
            meter_address=str(
                target.get("meteraddress")
                or all_values.get("meteraddress")
                or all_values.get("电表地址")
                or labelled.get("电表地址")
                or ""
            )
            or None,
        )

    @staticmethod
    def _optional_number(data: dict[str, Any], *names: str) -> Decimal | None:
        lowered = {str(k).lower(): v for k, v in data.items()}
        for name in names:
            value = lowered.get(name.lower())
            if value not in (None, ""):
                return _number(value, name)
        return None

    def _extract_html(self, text: str) -> MeterReading:
        soup = BeautifulSoup(text, "html.parser")
        plain = " ".join(soup.stripped_strings)

        def after(labels: tuple[str, ...], required: bool = True) -> str | None:
            for label in labels:
                match = re.search(
                    rf"{re.escape(label)}\s*[：:]?\s*(-?\d+(?:\.\d+)?)", plain, re.I
                )
                if match:
                    return match.group(1)
            if required:
                raise ParseError(f"电费页面中找不到字段：{'/'.join(labels)}")
            return None

        balance = after(("剩余金额", "余额", "balance"))
        meter = after(("电表读数", "电量读数", "meter reading"))
        subsidy = after(("电剩余补助", "剩余补助", "subsidy"), required=False)
        address_match = re.search(r"电表地址\s*[：:]?\s*([0-9A-Za-z-]+)", plain)

        building = self.settings.building or ""
        if self.settings.building is None:
            select = soup.find("select", attrs={"name": re.compile("build", re.I)})
            selected = select.find("option", selected=True) if select else None
            if selected:
                building = selected.get_text(strip=True)

        assert balance is not None and meter is not None
        return MeterReading(
            captured_at=datetime.now(self.settings.timezone),
            room=self.settings.room,
            building=building,
            balance_yuan=Decimal(balance),
            meter_reading_kwh=Decimal(meter),
            subsidy_kwh=Decimal(subsidy) if subsidy is not None else None,
            meter_address=address_match.group(1) if address_match else None,
        )
