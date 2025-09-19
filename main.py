# 🔐 라이브러리 및 기본 설정
import discord
from discord.ext import commands
from discord.ui import Button, View
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta, timezone
import random
import os
import json
import sys
import re
import asyncio

KST = timezone(timedelta(hours=9))

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# 🔐 환경변수 확인
DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GOOGLE_CREDS = os.getenv("GOOGLE_CREDS")
SHEET_KEY = os.getenv("SHEET_KEY")

missing = [k for k, v in {
    "DISCORD_BOT_TOKEN": DISCORD_TOKEN,
    "GOOGLE_CREDS": GOOGLE_CREDS,
    "SHEET_KEY": SHEET_KEY
}.items() if not v]
if missing:
    print(f"❌ 누락된 환경변수: {', '.join(missing)}")
    sys.exit(1)

# 🔐 구글 시트 인증
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]
try:
    creds_dict = json.loads(GOOGLE_CREDS)
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    gclient = gspread.authorize(creds)
    sheet = gclient.open_by_key(SHEET_KEY).sheet1  # 기본은 1번째 시트
except Exception as e:
    print("❌ 구글 스프레드시트 인증/접속 실패:", e)
    sys.exit(1)

# 🧰 유틸
def now_kst_str(fmt="%Y-%m-%d %H:%M:%S"):
    return datetime.now(KST).strftime(fmt)

DICE_EMOJI = {
    1: "🎲1", 2: "🎲2", 3: "🎲3",
    4: "🎲4", 5: "🎲5", 6: "🎲6"
}

# 다중 이름 파서: 공백/쉼표 섞여도 처리
def _parse_names_and_amount(args):
    """
    args 예: ("홍길동","김철수","5")  또는 ("홍길동,김철수","5")
    returns: (names:list[str], amount:int)  또는 (None, error_msg)
    """
    if len(args) < 2:
        return None, "⚠️ 최소 1명 이상의 이름과 수치를 입력하세요. 예) `!추가 홍길동 김철수 5`"

    amount_str = args[-1]
    if not amount_str.isdigit():
        return None, "⚠️ 수치는 양의 정수여야 합니다. 예) `!추가 홍길동 김철수 5`"
    amount = int(amount_str)

    raw_names = args[:-1]
    names = []
    for token in raw_names:
        for part in token.split(","):
            nm = part.strip()
            if nm:
                names.append(nm)

    if not names:
        return None, "⚠️ 유효한 이름이 없습니다. 예) `!추가 홍길동 김철수 5`"

    # 같은 이름이 여러 번 입력되면 중복 제거(순서 유지)
    names = list(dict.fromkeys(names))
    return (names, amount), None

@bot.event
async def on_ready():
    print(f'✅ Logged in as {bot.user} ({bot.user.id})')

@bot.command(name="접속", help="현재 봇이 정상 작동 중인지 확인합니다. 만약 봇이 응답하지 않으면 접속 오류입니다. 예) !접속")
async def 접속(ctx):
    timestamp = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    await ctx.send(f"현재 봇이 구동 중입니다.\n{timestamp}")

# ✅ 연결 테스트용 커맨드 (원하면 삭제 가능)
@bot.command(name="시트테스트", help="연결 확인 시트의 A1에 현재 시간을 기록하고 값을 확인합니다. 예) !시트테스트")
async def 시트테스트(ctx):
    try:
        sh = ws("연결 확인")  # '연결 확인' 시트 핸들러
        sh.update_acell("A1", f"✅ 연결 OK @ {now_kst_str()}")
        val = sh.acell("A1").value
        await ctx.send(f"A1 = {val}")
    except Exception as e:
        await ctx.send(f"❌ 시트 접근 실패: {e}")

  # ✅ 다이스 버튼

class DiceButton(Button):
    def __init__(self, sides: int, style: discord.ButtonStyle, owner_id: int):
        super().__init__(label=f"1d{sides}", style=style)
        self.sides = sides
        self.owner_id = owner_id

    async def callback(self, interaction: discord.Interaction):
        # 버튼 제한: 명령어 사용한 사람만
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "이 버튼은 명령어를 사용한 사람만 누를 수 있어요.", ephemeral=True
            )
            return

        roll = random.randint(1, self.sides)
        timestamp = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
        await interaction.response.send_message(
            f"{interaction.user.mention}의 **1d{self.sides}** 결과: **{roll}**\n{timestamp}"
        )

class DiceView(View):
    def __init__(self, owner_id: int, timeout: int = 60):
        super().__init__(timeout=timeout)
        # 버튼 색: 빨강(위험)=1d6, 파랑(기본)=1d10, 초록(성공)=1d100
        self.add_item(DiceButton(6,   discord.ButtonStyle.danger,  owner_id))
        self.add_item(DiceButton(10,  discord.ButtonStyle.primary, owner_id))
        self.add_item(DiceButton(100, discord.ButtonStyle.success, owner_id))
        self.message = None

    async def on_timeout(self):
        # 타임아웃 시 버튼 비활성화
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass

@bot.command(name="다이스", help="버튼으로 1d6/1d10/1d100을 굴립니다. 예) !다이스")
async def 다이스(ctx):
    view = DiceView(owner_id=ctx.author.id)
    msg = await ctx.send(f"{ctx.author.mention} 굴릴 주사위를 선택하세요:", view=view)
    view.message = msg

# ===== 군번(72******) 부여 =====

def _gunbeon_existing_set(sh):
    """'군번' 시트 D열의 기존 군번 집합 반환 (공백/NULL 제외)"""
    vals = sh.col_values(4)  # D열 전체
    return {v.strip() for v in vals if v and v.strip()}

def _gen_unique_gunbeon(existing_ids: set) -> str | None:
    """기존 집합과 중복되지 않는 72****** 군번 생성. 실패 시 None."""
    for _ in range(200):  # 여유롭게 재시도
        candidate = f"72{random.randint(0, 999999):06d}"
        if candidate not in existing_ids:
            return candidate
    return None

@bot.command(
    name="군번",
    help="!군번 이름 → '군번' 시트 B열에서 이름을 찾아 D열에 고유 군번(72******)을 자동 기입합니다."
)
async def 군번(ctx, 이름: str):
    try:
        sh = ws("군번")

        # 이름 행 찾기 (B열)
        row = find_row_by_name(sh, 이름, name_col=2)
        if not row:
            await ctx.send(f"❌ '군번' 시트 B열에서 '{이름}'을(를) 찾지 못했습니다.")
            return

        # 이미 군번이 있으면 재부여하지 않음
        current = (sh.cell(row, 4).value or "").strip()  # D열
        if current:
            timestamp = now_kst_str()
            await ctx.send(f"ℹ️ '{이름}'은(는) 이미 군번 `{current}`가 있습니다. 변경하지 않았습니다.\n{timestamp}")
            return

        # 중복 방지용 기존 집합 수집 후 생성
        existing = _gunbeon_existing_set(sh)
        new_id = _gen_unique_gunbeon(existing)
        if not new_id:
            await ctx.send("❌ 군번 생성 실패: 고유 번호 생성에 연속으로 실패했습니다. 다시 시도해 주세요.")
            return

        # 기입
        sh.update_cell(row, 4, new_id)  # D열에 기록
        mark_last_editor(sh, ctx)

        timestamp = now_kst_str()
        await ctx.send(f"✅ '{이름}'에게 군번 `{new_id}` 부여 완료.\n{timestamp}")

    except Exception as e:
        await ctx.send(f"❌ 군번 처리 실패: {e}")

  bot.run(DISCORD_TOKEN)
