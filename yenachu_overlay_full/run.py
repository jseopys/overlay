import argparse
import datetime
import logging
import json
import re
import requests
import threading
import time
from websocket import WebSocket as WS
import api
from cmd_type import CHZZK_CHAT_CMD


class ChzzkChat:
    """치지직 채팅 + 실시간 이모티콘 URL 조회 + Node 오버레이로 전송 (안 끊기는 안정화 버전)"""

    def __init__(self, streamer, cookies, logger):
        self.streamer = streamer
        self.cookies = cookies
        self.logger = logger
        self.sock = None
        self.sid = None
        self.running = True

        # 기본 정보 가져오기
        self.userIdHash = api.fetch_userIdHash(self.cookies)
        self.chatChannelId = api.fetch_chatChannelId(self.streamer, self.cookies)
        self.channelName = api.fetch_channelName(self.streamer)
        self.accessToken, self.extraToken = api.fetch_accessToken(self.chatChannelId, self.cookies)

        # 오버레이용 Node 서버 연결
        self.overlay_ws_url = "ws://118.42.157.55:3000"  # 🔸 Node에서 사용하는 포트 맞춰줘야 함
        self.overlay_ws = None
        self._connect_overlay_ws()

    # ─────────────── 오버레이 연결 ───────────────
    def _connect_overlay_ws(self):
        from websocket import WebSocket
        try:
            self.overlay_ws = WebSocket()
            self.overlay_ws.connect(self.overlay_ws_url)
            print(f"✅ 오버레이 중계 서버 연결됨: {self.overlay_ws_url}")
        except Exception as e:
            print(f"❌ 오버레이 서버 연결 실패: {e}")
            self.overlay_ws = None

    def _send_overlay(self, payload: dict):
        """Node.js로 데이터 전송"""
        if not self.overlay_ws:
            self._connect_overlay_ws()
        if not self.overlay_ws:
            return
        try:
            msg = json.dumps(payload, ensure_ascii=False)
            self.overlay_ws.send(msg)
            print(f"➡️ Node로 전송됨: {msg[:120]}...")
        except Exception as e:
            print(f"⚠️ 오버레이 전송 실패: {e}")
            self._connect_overlay_ws()

    # ─────────────── 이모티콘 URL 매핑 ───────────────
    def _fetch_emote_info(self, emote_name):
        """직접 정의한 이모티콘 URL 매핑"""
        CUSTOM_EMOTES = {
            "yenachuKirby": "https://nng-phinf.pstatic.net/glive/subscription/emoji/0f4b2c8313c813a863f4c202c8dff57b/1/HIP_1745304196251.gif?type=f60_60",
            "yenachuHIP2": "https://nng-phinf.pstatic.net/glive/subscription/emoji/0f4b2c8313c813a863f4c202c8dff57b/1/yenachuHIP2_1744810859470.gif?type=f60_60",
            "yenachuHello": "https://nng-phinf.pstatic.net/glive/subscription/emoji/0f4b2c8313c813a863f4c202c8dff57b/1/yenachuHello_1744811499913.gif?type=f60_60",
            "yenachuFist": "https://nng-phinf.pstatic.net/glive/subscription/emoji/0f4b2c8313c813a863f4c202c8dff57b/1/yenachuFist_1745304170649.gif?type=f60_60",
            "yenachuFighting": "https://nng-phinf.pstatic.net/glive/subscription/emoji/0f4b2c8313c813a863f4c202c8dff57b/1/yenachuFighting_1744811680914.gif?type=f60_60",
            "yenachuHi": "https://nng-phinf.pstatic.net/glive/subscription/emoji/0f4b2c8313c813a863f4c202c8dff57b/1/Hi_1745304000060.png?type=f60_60",
            "yenachuBye": "https://nng-phinf.pstatic.net/glive/subscription/emoji/0f4b2c8313c813a863f4c202c8dff57b/1/Bye_1745304011139.png?type=f60_60",
            "yenachuZzzz": "https://nng-phinf.pstatic.net/glive/subscription/emoji/0f4b2c8313c813a863f4c202c8dff57b/1/Zzzz_1745304025181.png?type=f60_60",
            "yenachuHi3": "https://nng-phinf.pstatic.net/glive/subscription/emoji/0f4b2c8313c813a863f4c202c8dff57b/1/Sad_1745304044056.png?type=f60_60",
            "yenachuHeart": "https://nng-phinf.pstatic.net/glive/subscription/emoji/0f4b2c8313c813a863f4c202c8dff57b/1/GGang_1745304091739.png?type=f60_60",
        }

        # 등록된 이모티콘만 반환
        url = CUSTOM_EMOTES.get(emote_name)
        if url:
            return url
        else:
            print(f"⚠️ 등록되지 않은 이모티콘: {emote_name}")
            return None

    # ─────────────── keepalive ───────────────
    def _keepalive(self):
        """30초마다 ping 전송"""
        if not self.running:
            return
        try:
            if self.sock:
                self.sock.send(json.dumps({"ver": "2", "cmd": CHZZK_CHAT_CMD['ping']}))
        except Exception as e:
            print(f"⚠️ keepalive ping 실패: {e}")
        threading.Timer(30, self._keepalive).start()

    # ─────────────── 채팅 연결 ───────────────
    def connect(self):
        """치지직 채팅 서버 연결"""
        try:
            self.chatChannelId = api.fetch_chatChannelId(self.streamer, self.cookies)
            self.accessToken, self.extraToken = api.fetch_accessToken(self.chatChannelId, self.cookies)

            sock = WS()
            sock.connect('wss://kr-ss1.chat.naver.com/chat')
            print(f'{self.channelName} 채팅창 연결 중...', end="")

            default = {"ver": "2", "svcid": "game", "cid": self.chatChannelId}

            # 접속 요청
            sock.send(json.dumps({
                **default,
                "cmd": CHZZK_CHAT_CMD['connect'],
                "tid": 1,
                "bdy": {"uid": self.userIdHash, "devType": 2001, "accTkn": self.accessToken, "auth": "SEND"}
            }))
            sock_response = json.loads(sock.recv())
            self.sid = sock_response['bdy']['sid']

            # 최근 메시지 요청
            sock.send(json.dumps({
                **default,
                "cmd": CHZZK_CHAT_CMD['request_recent_chat'],
                "tid": 2,
                "sid": self.sid,
                "bdy": {"recentMessageCount": 30}
            }))
            sock.recv()
            print('연결 완료 ✅')

            self.sock = sock
            self._keepalive()  # ping 타이머 시작

        except Exception as e:
            print(f"❌ 채팅 서버 연결 실패: {e}")
            time.sleep(5)
            self.connect()

    # ─────────────── 실행 루프 ───────────────
    def run(self):
        emote_pattern = re.compile(r"\{\:([A-Za-z0-9_]+)\:\}")
        while self.running:
            try:
                raw = self.sock.recv()
                data = json.loads(raw)
                cmd = data.get('cmd')

                # ping/pong
                if cmd == CHZZK_CHAT_CMD['ping']:
                    self.sock.send(json.dumps({"ver": "2", "cmd": CHZZK_CHAT_CMD['pong']}))
                    continue

                if cmd not in [CHZZK_CHAT_CMD['chat'], CHZZK_CHAT_CMD['donation']]:
                    continue

                for chat in data.get('bdy', []):
                    msg = chat.get("msg", "")
                    if not msg:
                        continue

                    nickname = "익명"
                    if chat.get("uid") != "anonymous":
                        try:
                            profile = json.loads(chat.get("profile", "{}"))
                            nickname = profile.get("nickname", nickname)
                        except Exception:
                            pass

                    now = datetime.datetime.fromtimestamp(chat['msgTime'] / 1000)
                    now_str = now.strftime('%Y-%m-%d %H:%M:%S')
                    self.logger.info(f"[{now_str}] {nickname}: {msg}")

                    # 이모티콘 추출
                    emotes = emote_pattern.findall(msg)
                    emote_objs = []
                    for name in emotes:
                        url = self._fetch_emote_info(name)
                        if url:
                            emote_objs.append({"name": name, "url": url})

                    # Node로 전송
                    if emote_objs:
                        self._send_overlay({
                            "type": "emote",
                            "user": nickname,
                            "emotes": emote_objs,
                            "raw": msg
                        })

            except Exception as e:
                print(f"⚠️ 연결 오류 발생: {e}, 5초 후 재연결 시도 중...")
                try:
                    self.sock.close()
                except:
                    pass
                time.sleep(5)
                try:
                    self.connect()
                except Exception as e2:
                    print(f"❌ 재연결 실패: {e2}")


def get_logger():
    formatter = logging.Formatter('%(message)s')
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    fh = logging.FileHandler('chat.log', mode="w", encoding="utf-8")
    fh.setFormatter(formatter)
    logger.addHandler(fh)
    sh = logging.StreamHandler()
    sh.setFormatter(formatter)
    logger.addHandler(sh)
    return logger


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--streamer_id', type=str, default='6a6da7669b9c07536e11e804a1e494f2')
    args = parser.parse_args()

    with open('cookies.json', encoding='utf-8') as f:
        cookies = json.load(f)

    logger = get_logger()
    chat = ChzzkChat(args.streamer_id, cookies, logger)
    chat.connect()
    chat.run()
