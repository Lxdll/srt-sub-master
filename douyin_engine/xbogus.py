# Copyright (C) 2021 Evil0ctal
#
# Derived from Evil0ctal/Douyin_TikTok_Download_API and distributed under
# Apache License 2.0. The vendored implementation was obtained through
# jiji262/douyin-downloader at commit
# 2e373df6fe474368804909f337fd26ee5139ce5d.

from __future__ import annotations

import base64
import hashlib
import time
from typing import Optional


class XBogus:
    def __init__(self, user_agent: Optional[str] = None) -> None:
        self._array = [
            None, None, None, None, None, None, None, None,
            None, None, None, None, None, None, None, None,
            None, None, None, None, None, None, None, None,
            None, None, None, None, None, None, None, None,
            None, None, None, None, None, None, None, None,
            None, None, None, None, None, None, None, None,
            0, 1, 2, 3, 4, 5, 6, 7, 8, 9, None, None, None, None, None, None,
            None, None, None, None, None, None, None, None,
            None, None, None, None, None, None, None, None,
            None, None, None, None, None, None, None, None,
            None, None, None, None, 10, 11, 12, 13, 14, 15,
        ]
        self._character = (
            "Dkdpgh4ZKsQB80/Mfvw36XI1R25-WUAlEi7NLboqYTOPuzmFjJnryx9HVGcaStCe="
        )
        self._ua_key = b"\x00\x01\x0c"
        self._user_agent = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/139.0.0.0 Safari/537.36"
        )

    @property
    def user_agent(self) -> str:
        return self._user_agent

    def _md5_str_to_array(self, value: str) -> list[int]:
        if len(value) == 32 and all(char in "0123456789abcdef" for char in value):
            return list(bytes.fromhex(value))
        return [ord(char) for char in value]

    def _md5(self, value: str | list[int]) -> str:
        data = self._md5_str_to_array(value) if isinstance(value, str) else value
        digest = hashlib.md5()
        digest.update(bytes(data))
        return digest.hexdigest()

    def _md5_encrypt(self, value: str) -> list[int]:
        hashed = self._md5(self._md5_str_to_array(self._md5(value)))
        return self._md5_str_to_array(hashed)

    @staticmethod
    def _rc4_encrypt(key: bytes, data: bytes) -> bytearray:
        state = list(range(256))
        cursor = 0
        encrypted = bytearray()
        for index in range(256):
            cursor = (cursor + state[index] + key[index % len(key)]) % 256
            state[index], state[cursor] = state[cursor], state[index]
        index = cursor = 0
        for byte in data:
            index = (index + 1) % 256
            cursor = (cursor + state[index]) % 256
            state[index], state[cursor] = state[cursor], state[index]
            encrypted.append(byte ^ state[(state[index] + state[cursor]) % 256])
        return encrypted

    @staticmethod
    def _encode_payload(
        a: int,
        b: int,
        c: int,
        e: int,
        d: int,
        t: int,
        f: int,
        r: int,
        n: int,
        o: int,
        i: int,
        underscore: int,
        x: int,
        u: int,
        s: int,
        ell: int,
        v: int,
        h: int,
        p: int,
    ) -> str:
        values = [
            a,
            int(i),
            b,
            underscore,
            c,
            x,
            e,
            u,
            d,
            s,
            t,
            ell,
            f,
            v,
            r,
            h,
            n,
            p,
            o,
        ]
        return bytes(values).decode("ISO-8859-1")

    def _calculation(self, first: int, second: int, third: int) -> str:
        value = ((first & 255) << 16) | ((second & 255) << 8) | (third & 255)
        return (
            self._character[(value & 16515072) >> 18]
            + self._character[(value & 258048) >> 12]
            + self._character[(value & 4032) >> 6]
            + self._character[value & 63]
        )

    def build(self, url: str) -> tuple[str, str, str]:
        ua_hash = self._md5_str_to_array(
            self._md5(
                base64.b64encode(
                    self._rc4_encrypt(
                        self._ua_key, self._user_agent.encode("ISO-8859-1")
                    )
                ).decode("ISO-8859-1")
            )
        )
        empty_hash = self._md5_str_to_array(
            self._md5(
                self._md5_str_to_array("d41d8cd98f00b204e9800998ecf8427e")
            )
        )
        url_hash = self._md5_encrypt(url)
        timestamp = int(time.time())
        constant = 536919696
        values = [
            64,
            0,
            1,
            12,
            url_hash[14],
            url_hash[15],
            empty_hash[14],
            empty_hash[15],
            ua_hash[14],
            ua_hash[15],
            timestamp >> 24 & 255,
            timestamp >> 16 & 255,
            timestamp >> 8 & 255,
            timestamp & 255,
            constant >> 24 & 255,
            constant >> 16 & 255,
            constant >> 8 & 255,
            constant & 255,
        ]
        checksum = values[0]
        for value in values[1:]:
            checksum ^= int(value)
        values.append(checksum)
        odd = values[::2]
        even = values[1::2]
        merged = odd + even
        raw = (
            chr(2)
            + chr(255)
            + self._rc4_encrypt(
                "ÿ".encode("ISO-8859-1"),
                self._encode_payload(*merged).encode("ISO-8859-1"),
            ).decode("ISO-8859-1")
        )
        encoded = ""
        for index in range(0, len(raw), 3):
            encoded += self._calculation(
                ord(raw[index]), ord(raw[index + 1]), ord(raw[index + 2])
            )
        return f"{url}&X-Bogus={encoded}", encoded, self._user_agent
